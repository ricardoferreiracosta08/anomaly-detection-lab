#!/usr/bin/env bash
# =============================================================================
# experiment.sh — Orquestra as rodadas do experimento (chamado pelo Makefile)
#
#   bin/experiment.sh phase1   Fase 1: cenários × REPS, HPA no modo A
#                              → datasets/<cen>_runN.csv + results/k6/<cen>_runN.json
#   bin/experiment.sh phase3   Fase 3: modos do HPA × cenários × REPS
#                              → datasets_hpa/<modo>_<cen>_runN.csv
#                                results/hpa/k6/<modo>_<cen>_runN.json
#                                results/hpa/hpa_results.csv (1 linha por execução)
#
# Rigor (material da disciplina):
#   - ordem aleatória das execuções dentro de cada repetição, com semente fixa
#     (RANDOM_SEED) e plano salvo em results/*plan*.csv            [PF 4]
#   - mesma condição inicial antes de cada execução: espera o HPA voltar ao
#     mínimo de réplicas + COOLDOWN                                  [AR 32–35]
#   - retomável/idempotente: execução já concluída é pulada (marcadores em
#     results/.done/); apagar o marcador força refazer aquela execução
#
# Só usa docker (k6 e análise em container) e kubectl (já exigido pelo lab).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "✗ .env não encontrado (cp .env.example .env)"; exit 1; }
# Lê o .env SEM sobrescrever o que já veio do ambiente: assim funcionam tanto
#   make experiment REPS=1            (make exporta as variáveis)
#   REPS=2 bin/experiment.sh phase1   (chamada direta)
while IFS= read -r line || [ -n "$line" ]; do
    [[ $line =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]] || continue
    key=${BASH_REMATCH[1]}
    [ -n "${!key+x}" ] && continue
    eval "export $line"
done < .env

PHASE="${1:-}"
[[ "$PHASE" == "phase1" || "$PHASE" == "phase3" ]] || { echo "uso: $0 phase1|phase3"; exit 2; }

REPS="${REPS:-10}"
COOLDOWN="${COOLDOWN:-120}"
BASELINE_TIMEOUT="${BASELINE_TIMEOUT:-900}"
RANDOM_SEED="${RANDOM_SEED:-2026}"
SCENARIOS="${SCENARIOS:-burst,rampup,shift}"; SCENARIOS="${SCENARIOS//,/ }"
HPA_MODES="${HPA_MODES:-A,B,C}"; HPA_MODES="${HPA_MODES//,/ }"
DOCKER_NET="${DOCKER_NET:-host}"
# núcleos do k6 e da análise (vazio = sem fixação); o cluster fica em CLUSTER_CPUS via 'make cpu-pin'
CPUSET=(); [ -n "${LOADGEN_CPUS:-}" ] && CPUSET=(--cpuset-cpus "$LOADGEN_CPUS")
NS="${NAMESPACE:-anomaly-lab}"
# ROLE=client: kubectl fala com o cluster da VPS pela VPN
if [ -n "${KUBECONFIG_FILE:-}" ]; then
    case "$KUBECONFIG_FILE" in /*) export KUBECONFIG="$KUBECONFIG_FILE" ;; *) export KUBECONFIG="$PWD/$KUBECONFIG_FILE" ;; esac
fi

declare -A SCRIPT=( [burst]=burst-anomaly.js [rampup]=rampup-irregular.js [shift]=load-shifting.js )
declare -A DURATION=( [burst]=720 [rampup]=780 [shift]=960 )

mkdir -p datasets datasets_hpa results/k6 results/hpa/k6 results/.done
chmod 777 datasets datasets_hpa results results/k6 results/hpa results/hpa/k6 2>/dev/null || true

log() { echo "[$(date +%H:%M:%S)] $*"; }

# ── ordem aleatória reprodutível (Fisher–Yates com semente) ───────────────
shuffle() {   # shuffle <semente> itens...
    local seed=$1; shift
    local -a a=("$@"); local i j tmp
    RANDOM=$seed
    for ((i=${#a[@]}-1; i>0; i--)); do
        j=$((RANDOM % (i+1))); tmp=${a[i]}; a[i]=${a[j]}; a[j]=$tmp
    done
    echo "${a[@]}"
}

# ── condição inicial: HPA de volta ao mínimo de réplicas ──────────────────
wait_baseline() {
    local t0 now cur
    t0=$(date +%s)
    while true; do
        cur=$(kubectl -n "$NS" get deploy fastapi-app -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "?")
        des=$(kubectl -n "$NS" get hpa fastapi-hpa -o jsonpath='{.status.desiredReplicas}' 2>/dev/null || echo "?")
        min=$(kubectl -n "$NS" get hpa fastapi-hpa -o jsonpath='{.spec.minReplicas}' 2>/dev/null || echo 2)
        [[ "$cur" == "$min" && "$des" == "$min" ]] && break
        now=$(date +%s)
        if (( now - t0 > BASELINE_TIMEOUT )); then
            log "⚠ réplicas não voltaram ao mínimo em ${BASELINE_TIMEOUT}s (atual=$cur desejado=$des); seguindo"
            break
        fi
        sleep 10
    done
    log "→ condição inicial: $cur réplica(s); cooldown ${COOLDOWN}s"
    sleep "$COOLDOWN"
}

apply_mode() {   # apply_mode A|B|C|D
    log "→ HPA modo $1"
    make -s hpa-mode HPA_MODE="$1" >/dev/null
}

run_k6() {   # run_k6 <cenario> <arquivo_summary_no_container>
    docker run --rm --network "$DOCKER_NET" "${CPUSET[@]}" \
        -v "$PWD/k6-scripts:/scripts:ro" -v "$PWD/results:/results" \
        -e BASE_URL="$APP_URL" -e SUMMARY_FILE="$2" \
        "$K6_IMAGE" run --quiet --summary-trend-stats="avg,min,med,max,p(90),p(95),p(99)" \
        "/scripts/${SCRIPT[$1]}" 2>&1 | tail -8 || true
}

analysis() {   # roda um script do container de análise
    docker run --rm --network "$DOCKER_NET" "${CPUSET[@]}" \
        -v "$PWD/datasets:/datasets" -v "$PWD/datasets_hpa:/datasets_hpa" -v "$PWD/results:/results" \
        -e PROMETHEUS_URL="$PROM_URL" -e NAMESPACE="$NS" \
        -e DETECTOR_ALGOS="${DETECTOR_ALGOS:-EWMA,IF,LOF,DBSCAN,AE}" \
        -e SLO_SECONDS="${SLO_SECONDS:-0.5}" \
        "$ANALYSIS_IMAGE" "$@"
}

one_run() {   # one_run <modo|-> <cenario> <rep>
    local mode=$1 sc=$2 rep=$3 key start csv summ
    if [ "$mode" = "-" ]; then
        key="${sc}_run${rep}"; csv="/datasets/${key}.csv"; summ="/results/k6/${key}.json"
    else
        key="${mode}_${sc}_run${rep}"; csv="/datasets_hpa/${key}.csv"; summ="/results/hpa/k6/${key}.json"
    fi
    if [ -f "results/.done/${PHASE}_${key}" ]; then
        log "✓ $key já concluída (pulando)"; return
    fi
    [ "$mode" != "-" ] && apply_mode "$mode"
    wait_baseline
    log "══════ $key (${DURATION[$sc]}s) → $APP_URL ══════"
    start=$(date +%s)
    run_k6 "$sc" "$summ"
    if [ ! -s "results${summ#/results}" ]; then   # k6 não terminou: execução inválida, será refeita
        log "✗ $key inválida (k6 sem resumo; queda de conexão?). Será refeita na próxima chamada."
        return
    fi
    sleep 15   # último scrape + janela de rate()
    analysis export_metrics.py --scenario "$sc" --duration "${DURATION[$sc]}" --start "$start" --output "$csv"
    if [ "$mode" != "-" ]; then
        analysis hpa_metrics.py --mode "$mode" --scenario "$sc" --run "$rep" --start "$start" \
            --duration "${DURATION[$sc]}" --k6-summary "$summ" --output /results/hpa/hpa_results.csv
    fi
    echo "$PHASE,$key,$mode,$sc,$rep,$start,$(date +%s)" >> results/experiment_log.csv
    touch "results/.done/${PHASE}_${key}"
}

[ -f results/experiment_log.csv ] || echo "phase,key,mode,scenario,rep,start,end" > results/experiment_log.csv

if [ "$PHASE" = "phase1" ]; then
    apply_mode A
    plan=results/run_plan_phase1.csv; echo "rep,ordem" > "$plan"
    for rep in $(seq 1 "$REPS"); do
        order=$(shuffle $((RANDOM_SEED + rep)) $SCENARIOS)
        echo "$rep,${order// /;}" >> "$plan"
        for sc in $order; do one_run - "$sc" "$rep"; done
    done
    log "✓ Fase 1 concluída: $(ls datasets/*.csv 2>/dev/null | wc -l) CSVs em datasets/"
else
    combos=(); for m in $HPA_MODES; do for sc in $SCENARIOS; do combos+=("$m:$sc"); done; done
    plan=results/run_plan_phase3.csv; echo "rep,ordem" > "$plan"
    for rep in $(seq 1 "$REPS"); do
        order=$(shuffle $((RANDOM_SEED + 1000 + rep)) "${combos[@]}")
        echo "$rep,${order// /;}" >> "$plan"
        for c in $order; do one_run "${c%%:*}" "${c##*:}" "$rep"; done
    done
    apply_mode A
    log "✓ Fase 3 concluída: results/hpa/hpa_results.csv"
fi
