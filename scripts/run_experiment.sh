#!/bin/bash
# =============================================================================
# run_experiment.sh — Executa protocolo experimental completo
# 3 cenários × 3 rodadas = 9 datasets anotados
#
# PPGCC/UFMA — Ricardo F. Costa — 2026
#
# Uso:
#   chmod +x scripts/run_experiment.sh
#   ./scripts/run_experiment.sh [BASE_URL]
#
# Pré-requisitos:
#   - Cluster K3D rodando (make up)
#   - k6 instalado
#   - Python com requests instalado (make pip-install)
#   - Port-forward ativo (localhost:8080 → app, localhost:9090 → prometheus)
# =============================================================================

set -e

BASE_URL="${1:-http://localhost:8080}"
PROM_URL="${2:-http://localhost:9090}"
DATASETS_DIR="datasets"
RESULTS_DIR="results"
ROUNDS=3
COOLDOWN=120  # 2 minutos entre rodadas para baseline estabilizar
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Cenários e durações (segundos)
declare -A SCENARIOS
SCENARIOS[burst]=720
SCENARIOS[rampup]=780
SCENARIOS[shift]=960

declare -A K6_SCRIPTS
K6_SCRIPTS[burst]="k6-scripts/burst-anomaly.js"
K6_SCRIPTS[rampup]="k6-scripts/rampup-irregular.js"
K6_SCRIPTS[shift]="k6-scripts/load-shifting.js"

# ── Funções auxiliares ───────────────────────────────────────────────────────

log() {
    echo "[$(date +%H:%M:%S)] $1"
}

check_prereqs() {
    log "Verificando pré-requisitos..."

    # k6
    if ! command -v k6 &>/dev/null; then
        echo "ERRO: k6 não encontrado. Instale: brew install k6 / snap install k6"
        exit 1
    fi

    # Python
    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        echo "ERRO: Python não encontrado."
        exit 1
    fi
    PYTHON=$(command -v python3 || command -v python)

    # App respondendo
    if ! curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
        echo "ERRO: App não responde em $BASE_URL/health"
        echo "  Execute: make up && make port-forward"
        exit 1
    fi

    # Prometheus respondendo
    if ! curl -sf "$PROM_URL/-/ready" > /dev/null 2>&1; then
        echo "ERRO: Prometheus não responde em $PROM_URL"
        echo "  Execute: make port-forward"
        exit 1
    fi

    log "✓ Todos os pré-requisitos OK"
}

wait_cooldown() {
    local seconds=$1
    log "Cooldown: aguardando ${seconds}s para estabilizar baseline..."
    
    # Gerar carga leve durante cooldown para manter métricas fluindo
    for i in $(seq 1 $((seconds / 5))); do
        curl -sf "$BASE_URL/api/v1/items?limit=5" > /dev/null 2>&1 || true
        sleep 5
    done
}

run_scenario() {
    local scenario=$1
    local round=$2
    local duration=${SCENARIOS[$scenario]}
    local script=${K6_SCRIPTS[$scenario]}
    local output_csv="${DATASETS_DIR}/${scenario}_run${round}.csv"
    local k6_json="${RESULTS_DIR}/k6_${scenario}_run${round}_${TIMESTAMP}.json"

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "  CENÁRIO: ${scenario} | RODADA: ${round}/3"
    log "  Script K6: ${script}"
    log "  Duração: ${duration}s (~$((duration/60))min)"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Registrar timestamp de início
    local start_ts=$(date +%s)
    log "Início: $(date -d @$start_ts '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r $start_ts '+%Y-%m-%d %H:%M:%S')"

    # Executar K6
    log "Executando k6..."
    k6 run \
        --env BASE_URL="$BASE_URL" \
        --out json="$k6_json" \
        --summary-trend-stats="avg,min,med,max,p(90),p(95),p(99)" \
        "$script" || {
            log "⚠ K6 terminou com warnings (normal em cenários de stress)"
        }

    local end_ts=$(date +%s)
    local actual_duration=$((end_ts - start_ts))
    log "K6 finalizado. Duração real: ${actual_duration}s"

    # Aguardar Prometheus consolidar (15s de buffer)
    log "Aguardando 15s para Prometheus consolidar métricas..."
    sleep 15

    # Exportar métricas para CSV anotado
    log "Exportando métricas → ${output_csv}..."
    $PYTHON scripts/export_metrics.py \
        --scenario "$scenario" \
        --duration "$actual_duration" \
        --start "$start_ts" \
        --output "$output_csv"

    # Validar CSV gerado
    if [ -f "$output_csv" ]; then
        local lines=$(wc -l < "$output_csv")
        local anomalous=$(awk -F',' 'NR>1 && $NF==1{c++}END{print c+0}' "$output_csv")
        log "✓ CSV gerado: ${lines} linhas, ${anomalous} anômalos"
    else
        log "✗ ERRO: CSV não foi gerado!"
        return 1
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║  Protocolo Experimental — Detecção de Anomalias em K8s      ║"
    echo "║  3 cenários × 3 rodadas = 9 datasets                       ║"
    echo "║  Tempo estimado: ~2h30min                                   ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""

    check_prereqs

    mkdir -p "$DATASETS_DIR" "$RESULTS_DIR"

    local total_start=$(date +%s)
    local run_count=0
    local total_runs=$((3 * ROUNDS))

    for scenario in burst rampup shift; do
        for round in $(seq 1 $ROUNDS); do
            run_count=$((run_count + 1))
            log ""
            log "═══ PROGRESSO: ${run_count}/${total_runs} ═══"

            run_scenario "$scenario" "$round"

            # Cooldown entre rodadas (exceto a última)
            if [ $run_count -lt $total_runs ]; then
                wait_cooldown $COOLDOWN
            fi
        done
    done

    local total_end=$(date +%s)
    local total_elapsed=$(( (total_end - total_start) / 60 ))

    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║  COLETA COMPLETA                                            ║"
    echo "║                                                             ║"
    echo "║  Datasets gerados:                                          ║"

    for scenario in burst rampup shift; do
        for round in $(seq 1 $ROUNDS); do
            local f="${DATASETS_DIR}/${scenario}_run${round}.csv"
            if [ -f "$f" ]; then
                local lines=$(wc -l < "$f")
                printf "║    %-45s %5s linhas  ║\n" "$f" "$lines"
            fi
        done
    done

    echo "║                                                             ║"
    echo "║  Tempo total: ${total_elapsed} minutos                             ║"
    echo "║                                                             ║"
    echo "║  Próximo passo:                                             ║"
    echo "║    make detect                                              ║"
    echo "║    → Executa EWMA + IF + LOF sobre os 9 datasets            ║"
    echo "║    → Gera results/detection_results.csv                     ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
}

main
