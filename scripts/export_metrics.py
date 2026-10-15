"""
export_metrics.py — Exporta métricas do Prometheus para CSV anotado
PPGCC/UFMA — Ricardo F. Costa — 2026

Uso:
  python scripts/export_metrics.py --scenario burst --duration 720 --output datasets/burst_run1.csv

O script:
  1. Consulta Prometheus via HTTP API (range query)
  2. Coleta: latência p95, CPU, memória, request rate, error rate
  3. Anota ground truth baseado nas fases do cenário K6
  4. Salva CSV com timestamp, métricas e label
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

from prom_queries import queries, online_alert_query, NAMESPACE

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
STEP = "5s"  # Granularidade de 5 segundos (match com scrape_interval)
ONLINE_DETECTORS = [d.strip() for d in os.environ.get(
    "DETECTOR_ALGOS", "EWMA,IF,LOF,DBSCAN,AE").split(",") if d.strip()]

# ── Queries Prometheus (fonte única em prom_queries.py) ─────────────────────
QUERIES = queries(NAMESPACE)

# ── Ground Truth: fases anômalas por cenário ────────────────────────────────
# Cada cenário define em quais intervalos (segundos desde início) a carga é anômala.
# Esses intervalos correspondem às stages dos scripts K6.

ANOMALY_PHASES = {
    "burst": [
        # Fase normal: 0-150s (warmup + baseline)
        # Burst 1: 150-185s (ramp+sustain+drop)
        (150, 185),
        # Normal: 185-305s
        # Burst 2: 305-345s
        (305, 345),
        # Normal: 345-465s
        # Burst 3: 465-500s
        (465, 500),
        # Cooldown: 500-620s
    ],
    "rampup": [
        # Baseline: 0-30s
        # Cada degrau é progressivamente anômalo a partir do 3º
        # Degrau 3 (salto grande): 175-210s
        (175, 210),
        # Degrau 4 (acima do anterior): 280-320s
        (280, 320),
        # Degrau 5 (aceleração): 335-380s
        (335, 380),
        # Pico máximo: 395-465s
        (395, 465),
    ],
    "shift": [
        # Baseline (normal read-heavy): 0-150s
        # Shift para CPU-heavy: 150-300s
        (150, 300),
        # Recovery: 300-420s
        # Shift para write-heavy: 420-570s
        (420, 570),
        # Recovery breve: 570-660s
        # Shift mixed caótico: 660-810s
        (660, 810),
        # Cooldown: 810-930s
    ],
}


def query_prometheus_range(query: str, start: float, end: float, step: str) -> list:
    """Executa range query no Prometheus e retorna lista de (timestamp, value)."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": step},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data["status"] != "success" or not data["data"]["result"]:
        return []

    # Pega a primeira série (já agregada)
    values = data["data"]["result"][0]["values"]
    return [(float(ts), float(val)) for ts, val in values]


def is_anomalous(offset_seconds: float, scenario: str) -> int:
    """Retorna 1 se o ponto está em fase anômala, 0 caso contrário."""
    phases = ANOMALY_PHASES.get(scenario, [])
    for start, end in phases:
        if start <= offset_seconds <= end:
            return 1
    return 0


def export(scenario: str, duration: int, output: str, start_time: float = None):
    """Exporta métricas do Prometheus para CSV."""
    if start_time is None:
        # Assume que o teste acabou agora
        end_ts = time.time()
        start_ts = end_ts - duration
    else:
        start_ts = start_time
        end_ts = start_ts + duration

    print(f"Exportando métricas de {datetime.fromtimestamp(start_ts)} "
          f"a {datetime.fromtimestamp(end_ts)}")
    print(f"Cenário: {scenario} | Duração: {duration}s | Step: {STEP}")

    # Coletar todas as métricas
    all_data = {}
    for name, query in QUERIES.items():
        print(f"  Coletando {name}...")
        series = query_prometheus_range(query, start_ts, end_ts, STEP)
        for ts, val in series:
            if ts not in all_data:
                all_data[ts] = {"timestamp": ts}
            all_data[ts][name] = val
        print(f"    → {len(series)} pontos")

    if not all_data:
        print("ERRO: Nenhum dado coletado. Verifique se o Prometheus está rodando.")
        sys.exit(1)

    # Alertas do detector online (se estiver rodando no cluster) → online_<DET>
    online_cols = []
    for det in ONLINE_DETECTORS:
        try:
            series = query_prometheus_range(online_alert_query(det), start_ts, end_ts, STEP)
        except requests.RequestException:
            series = []
        if not series:
            continue
        col = f"online_{det}"
        online_cols.append(col)
        for ts, val in series:
            if ts in all_data:
                all_data[ts][col] = val
    if online_cols:
        print(f"  Alertas online incluídos: {', '.join(online_cols)}")

    # Ordenar por timestamp e anotar ground truth
    rows = sorted(all_data.values(), key=lambda x: x["timestamp"])
    for row in rows:
        offset = row["timestamp"] - start_ts
        row["offset_seconds"] = round(offset, 1)
        row["label"] = is_anomalous(offset, scenario)
        row["datetime"] = datetime.fromtimestamp(row["timestamp"]).isoformat()

    # Escrever CSV
    fieldnames = [
        "datetime", "timestamp", "offset_seconds",
        "latency_p95", "cpu_percent", "memory_mb",
        "request_rate", "error_rate", "label"
    ] + online_cols

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    n_anomalous = sum(1 for r in rows if r["label"] == 1)
    print(f"\n✓ Exportado: {output}")
    print(f"  Total de pontos: {len(rows)}")
    print(f"  Pontos anômalos: {n_anomalous} ({100*n_anomalous/len(rows):.1f}%)")
    print(f"  Pontos normais:  {len(rows)-n_anomalous}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exporta métricas Prometheus → CSV anotado")
    parser.add_argument("--scenario", required=True, choices=["burst", "rampup", "shift"])
    parser.add_argument("--duration", type=int, default=720, help="Duração em segundos")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saída")
    parser.add_argument("--start", type=float, default=None, help="Unix timestamp de início")
    args = parser.parse_args()

    export(args.scenario, args.duration, args.output, args.start)
