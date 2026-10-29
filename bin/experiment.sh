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
#   - aquecimento (WARMUP_SECONDS, k6-scripts/warmup.js): carga constante com o
#     mix da fase normal do cenário, logo antes do roteiro, para a referência
#     do detector online não ser feita de silêncio (piloto 2, docs/PILOTOS.md).
#     Não gera CSV nem entra na avaliação; registro em results/warmup_log.csv
#   - Fase 3: espera, cooldown e aquecimento sempre com o HPA no modo A; o modo
#     da execução só é aplicado depois da conferência das réplicas, logo antes
#     do roteiro → toda execução começa com o mínimo de réplicas, em qualquer modo
#   - a app é reiniciada antes de cada execução (estado limpo: 100 itens por pod)
#   - troca aquecimento → roteiro com as rampas sobrepostas (carga constante)
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
# aquecimento: padrão = referência + gap do detector = (60 + 6) × 5 s = 330 s; 0 desliga
STEP_S="${DETECTOR_STEP_SECONDS:-5}"; STEP_S="${STEP_S%.*}"
WARMUP_SECONDS="${WARMUP_SECONDS:-$(( (${DETECTOR_WINDOW:-60} + ${DETECTOR_GAP:-6}) * STEP_S ))}"
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
# VUs do aquecimento = nível no fim da 1ª rampa de cada roteiro (30 s → 10, 10, 30)
declare -A WARMUP_VUS=( [burst]=10 [rampup]=10 [shift]=30 )

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

# ── réplicas: disponíveis, desejadas pelo HPA e mínimo (globais cur/des/min) ─
read_replicas() {
    cur=$(kubectl -n "$NS" get deploy fastapi-app -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "?")
    des=$(kubectl -n "$NS" get hpa fastapi-hpa -o jsonpath='{.status.desiredReplicas}' 2>/dev/null || echo "?")
    min=$(kubectl -n "$NS" get hpa fastapi-hpa -o jsonpath='{.spec.minReplicas}' 2>/dev/null || echo 2)
}

# ── condição inicial: HPA de volta ao mínimo de réplicas ──────────────────
wait_baseline() {
    local t0 now last=0
    t0=$(date +%s)
    while true; do
        read_replicas
        [[ "$cur" == "$min" && "$des" == "$min" ]] && break
        now=$(date +%s)
        if (( now - last >= 60 )); then   # só informa o progresso; não muda a espera
            log "… aguardando réplicas voltarem ao mínimo (atual=$cur desejado=$des mínimo=$min; $((now - t0))s de ${BASELINE_TIMEOUT}s)"
            last=$now
        fi
        if (( now - t0 > BASELINE_TIMEOUT )); then
            log "⚠ réplicas não voltaram ao mínimo em ${BASELINE_TIMEOUT}s (atual=$cur desejado=$des); seguindo"
            break
        fi
        sleep 10
    done
    log "→ condição inicial: $cur réplica(s); cooldown ${COOLDOWN}s"
    sleep "$COOLDOWN"
}

# ── anomaly_level do detector do modo B, como o HPA o veria (via Adapter) ──
level_b() {
    local raw
    raw=$(kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/$NS/anomaly_level?labelSelector=detector%3D${HPA_B_DETECTOR:-IF}%2Ctarget%3D${TARGET_APP:-fastapi}" 2>/dev/null \
        | grep -o '"value":"[^"]*"' | head -1 | cut -d'"' -f4) || raw=""
    if [ -z "$raw" ]; then echo "?"; return; fi
    # quantidade do Kubernetes: "667m" = 0,667; "1" = 1
    LC_ALL=C awk -v v="$raw" 'BEGIN { if (v ~ /m$/) { sub(/m$/, "", v); v = v / 1000 } printf "%.3f", v }'
}

# ── estado limpo: reinicia a app antes de cada execução ──────────────────
# A app guarda os itens em memória, por pod, e cada POST do k6 acrescenta um; /report,
# /search e o GET leve percorrem todos. Sem reiniciar, cada execução herdava o estado das
# anteriores (piloto 3: 4.055 e 3.850 itens por pod, contra 100 da semente) → viés de ordem.
restart_app() {
    log "→ reiniciando a app (pods novos, 100 itens por pod)"
    kubectl -n "$NS" rollout restart deploy/fastapi-app >/dev/null
    kubectl -n "$NS" rollout status deploy/fastapi-app --timeout=300s >/dev/null \
        || log "⚠ o rollout da app não terminou em 300 s; seguindo para a espera pelas réplicas"
}

# ── itens por pod e p95 do aquecimento, pelo Prometheus: "112;108 23.4" ──
# Itens = app_items_total por pod. p95 = latência nos últimos 4 min do aquecimento (ms),
# lida antes da descida e antes do modo: mede só o ambiente (drift), não o tratamento;
# serve para conferir o equilíbrio entre A, B e C na Fase 3 (decisão 14).
# Uma chamada só: as conferências cabem nos CHECK_MARGIN s antes da troca.
items_and_p95() {
    analysis -c "
import requests
def q(expr):
    return requests.get('$PROM_URL/api/v1/query', params={'query': expr}, timeout=5).json()['data']['result']
try:
    r = q('app_items_total{namespace=\"$NS\"}')
    items = ';'.join(str(int(float(x['value'][1]))) for x in sorted(r, key=lambda x: x['metric'].get('pod', '')))
except Exception:
    items = '?'
try:
    p95 = '%.1f' % (1000 * float(q('histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{namespace=\"$NS\"}[4m])) by (le))')[0]['value'][1]))
except Exception:
    p95 = '?'
print(items or '?', p95)
" 2>/dev/null || echo "? ?"
}

# ── aquecimento: carga normal constante (HPA no modo A), com sobreposição na troca ─
# warmup_start dispara o k6 do aquecimento em segundo plano; warmup_handoff espera até
# RAMP_DOWN s antes do fim dele, confere réplicas/anomaly_level/itens, aplica o modo e
# volta na hora de o roteiro começar. O roteiro sobe (0 → VUs em 30 s) enquanto o
# aquecimento desce (VUs → 0 em 30 s): carga total constante na troca (piloto 3: sem
# isso, AE/DBSCAN/LOF alarmavam de 15 a 45 s).
RAMP_DOWN="${WARMUP_OVERLAP:-30}"   # = 1ª rampa dos três roteiros (30 s); 0 = sem sobreposição
CHECK_MARGIN=15     # s antes da troca reservados para as conferências e o apply_mode
WARM_PID=""; WARM_T0=0
warmup_start() {   # warmup_start <cenario>
    local sc=$1 vus=${WARMUP_VUS[$1]}
    WARM_PID=""
    (( WARMUP_SECONDS > 0 )) || { log "→ aquecimento desligado (WARMUP_SECONDS=0)"; return; }
    log "→ aquecimento: $vus VUs por ${WARMUP_SECONDS}s, HPA no modo A, descida nos últimos ${RAMP_DOWN}s (mix da fase normal do $sc; não gera CSV)"
    WARM_T0=$(date +%s)
    ( docker run --rm --network "$DOCKER_NET" "${CPUSET[@]}" \
        -v "$PWD/k6-scripts:/scripts:ro" \
        -e BASE_URL="$APP_URL" -e SCENARIO="$sc" -e VUS="$vus" \
        -e WARMUP_SECONDS="$WARMUP_SECONDS" -e RAMP_DOWN="$RAMP_DOWN" \
        "$K6_IMAGE" run --quiet /scripts/warmup.js 2>&1 | tail -2 || true ) &
    WARM_PID=$!
}

warmup_handoff() {   # warmup_handoff <cenario> <key> <modo|->
    local sc=$1 key=$2 mode=$3 vus=${WARMUP_VUS[$1]} ok lvl items p95 handoff now
    if [ -n "$WARM_PID" ]; then
        handoff=$(( WARM_T0 + WARMUP_SECONDS - RAMP_DOWN ))
        now=$(date +%s)
        if (( handoff - CHECK_MARGIN > now )); then sleep $(( handoff - CHECK_MARGIN - now )); fi
    fi
    read_replicas
    lvl=$(level_b)
    read -r items p95 <<< "$(items_and_p95)"
    if [[ "$cur" == "$min" && "$des" == "$min" ]]; then
        ok=1; log "✓ fim do aquecimento: réplicas no mínimo ($cur); anomaly_level ${HPA_B_DETECTOR:-IF} = $lvl; itens por pod = $items; p95 = ${p95} ms"
    else
        ok=0; log "⚠ o HPA escalou durante o aquecimento (atual=$cur desejado=$des mínimo=$min): $key começa fora da condição inicial"
    fi
    # anomaly_level do B ≥ 0,5 aqui = o B escalaria assim que aplicado; itens iguais = mesmo estado da app
    local header="phase,key,scenario,vus,seconds,end,available,desired,min,at_min,b_detector,anomaly_level_b,items_per_pod,warmup_p95_ms"
    if [ -f results/warmup_log.csv ] && [ "$(head -1 results/warmup_log.csv)" != "$header" ]; then
        mv results/warmup_log.csv "results/warmup_log.antigo.$(date +%s).csv"   # formato anterior: guarda à parte
    fi
    [ -f results/warmup_log.csv ] || echo "$header" > results/warmup_log.csv
    echo "$PHASE,$key,$sc,$vus,$WARMUP_SECONDS,$(date +%s),$cur,$des,$min,$ok,${HPA_B_DETECTOR:-IF},$lvl,$items,$p95" >> results/warmup_log.csv
    # o modo da execução só entra agora (Fase 3); no A nada muda
    if [ "$mode" != "-" ] && [ "$mode" != "A" ]; then apply_mode "$mode"; fi
    if [ -n "$WARM_PID" ]; then
        now=$(date +%s)
        if (( now > handoff )); then
            log "⚠ conferências passaram da troca em $(( now - handoff ))s: sobreposição das rampas menor que ${RAMP_DOWN}s"
        else
            sleep $(( handoff - now ))
        fi
    fi
}

warmup_wait() {
    [ -n "$WARM_PID" ] && { wait "$WARM_PID" || true; }
    WARM_PID=""
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
        -e DETECTOR_ALGOS="${DETECTOR_ALGOS:-EWMA,IF,LOF,DBSCAN,AE,LSTM}" \
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
    # condição inicial e aquecimento sempre no modo A (Fase 1 já está em A);
    # o modo da execução só entra depois da conferência das réplicas, logo antes do roteiro
    [ "$mode" != "-" ] && apply_mode A
    if [ "${RESTART_APP:-1}" = "1" ]; then restart_app; else log "→ app NÃO reiniciada (RESTART_APP=0)"; fi
    wait_baseline
    warmup_start "$sc"
    warmup_handoff "$sc" "$key" "$mode"
    log "══════ $key (${DURATION[$sc]}s) → $APP_URL ══════"
    start=$(date +%s)
    run_k6 "$sc" "$summ"
    warmup_wait
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
PHASE_T0=$(date +%s)

# ── custo da observação: ciclo e CPU do detector durante a fase inteira ───
save_detector_cost() {
    local t0 mins
    # desde a 1ª execução desta fase (inclusive de chamadas anteriores, se foi retomada)
    t0=$(awk -F, -v p="$PHASE" '$1 == p { print $6 }' results/experiment_log.csv | sort -n | head -1)
    t0=${t0:-$PHASE_T0}
    mins=$(( ($(date +%s) - t0) / 60 + 6 ))   # + aquecimento da 1ª execução
    log "→ custo do detector na fase (últimos $mins min) → results/detector_ciclo_${PHASE}.txt"
    make -s detector-ciclo MIN="$mins" 2>&1 | tee "results/detector_ciclo_${PHASE}.txt" || true
}

if [ "$PHASE" = "phase1" ]; then
    apply_mode A
    plan=results/run_plan_phase1.csv; echo "rep,ordem" > "$plan"
    for rep in $(seq 1 "$REPS"); do
        order=$(shuffle $((RANDOM_SEED + rep)) $SCENARIOS)
        echo "$rep,${order// /;}" >> "$plan"
        for sc in $order; do one_run - "$sc" "$rep"; done
    done
    save_detector_cost
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
    save_detector_cost
    log "✓ Fase 3 concluída: results/hpa/hpa_results.csv"
fi
