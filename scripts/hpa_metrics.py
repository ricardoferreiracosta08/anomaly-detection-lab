"""
hpa_metrics.py — Métricas de desempenho do HPA por execução (Fase 3)
PPGCC/UFMA — Ricardo F. Costa — 2026

Para uma execução (modo do HPA × cenário × repetição), consulta o Prometheus e
calcula UMA linha de métricas (o Yi de cada métrica para o IC da média):

  reaction_time_s     início da janela anômala → 1º aumento das réplicas DESEJADAS
                      pelo HPA (média nas janelas em que houve reação)
  ready_time_s        início da janela → 1º aumento das réplicas DISPONÍVEIS depois da
                      reação (mesmas janelas do reaction_time_s; pods da reação prontos)
  windows_no_reaction janelas anômalas sem nenhum scale-up (censuradas)
  p95_anom_ms         p95 da latência (lado servidor) dentro das janelas anômalas
  slo_viol_anom_pct   % de requisições > SLO_SECONDS dentro das janelas anômalas
  slo_viol_all_pct    % de requisições > SLO_SECONDS na execução inteira
  pod_seconds         custo: ∫ réplicas disponíveis dt  (pods × segundos)
  scaleups            nº de aumentos das réplicas desejadas
  false_scaleups      aumentos fora de qualquer janela anômala (+ tolerância)
  k6_p95_ms, k6_error_rate   do summary do k6 (lado cliente), se informado

Janelas anômalas = ground truth do export_metrics.py (mesmo roteiro do k6).
Requer kube-state-metrics (k8s/monitoring/kube-state-metrics.yaml).
Com --series, grava também as séries de réplicas (desejadas e disponíveis) da execução:
o Prometheus guarda só 7 dias, e sem elas as métricas do HPA não poderiam ser revistas.

Uso:
  python hpa_metrics.py --mode B --scenario burst --run 3 --start <unix> --duration 720 \\
      --k6-summary /results/hpa/k6/B_burst_run3.json --output /results/hpa/hpa_results.csv \\
      --series /results/hpa/series/B_burst_run3.csv
  # recalcular todas as linhas de um hpa_results.csv (enquanto o Prometheus tiver os dados):
  python hpa_metrics.py --recalc /recalc/hpa_results.csv --k6-dir /recalc/k6 \\
      --output /recalc/hpa_results_recalc.csv --series-dir /recalc/series
"""
import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import requests

from export_metrics import ANOMALY_PHASES, K6_END_SECONDS
from prom_queries import NAMESPACE

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
SLO_SECONDS = float(os.environ.get("SLO_SECONDS", "0.5"))     # critério de aceitação: 500 ms
GRACE_SECONDS = float(os.environ.get("REACTION_GRACE_SECONDS", "60"))
STEP = 5
DEPLOY, HPA = "fastapi-app", "fastapi-hpa"

FIELDS = ["mode", "scenario", "run", "start", "duration",
          "reaction_time_s", "ready_time_s", "windows_no_reaction", "n_windows",
          "p95_anom_ms", "slo_viol_anom_pct", "slo_viol_all_pct",
          "pod_seconds", "scaleups", "false_scaleups", "k6_p95_ms", "k6_error_rate"]


# =============================================================================
# Funções puras (testáveis sem Prometheus)
# =============================================================================

def value_at(series, t):
    """Último valor da série com timestamp <= t (None se não houver)."""
    v = None
    for ts, val in series:
        if ts <= t:
            v = val
        else:
            break
    return v


def first_increase(series, t0, t_end):
    """Atraso (s) entre t0 e o 1º instante em (t0, t_end] com valor > valor em t0."""
    base = value_at(series, t0)
    if base is None:
        return None
    for ts, val in series:
        if t0 < ts <= t_end and val > base:
            return ts - t0
    return None


def increases(series):
    """Instantes em que a série aumentou em relação ao ponto anterior."""
    return [series[i][0] for i in range(1, len(series)) if series[i][1] > series[i - 1][1]]


def reaction_metrics(desired, available, start, windows, grace=GRACE_SECONDS, count_until=None):
    """Tempo de reação, tempo até Ready, janelas sem reação, scale-ups e falsos.
    count_until (unix): scale-ups falsos só contam até aqui (fim do k6 + grace; decisão 17).
    Depois disso não há carga do roteiro; None = janela inteira."""
    react, ready, no_react = [], [], 0
    for a, b in windows:
        t0, t_end = start + a, start + b + grace
        r = first_increase(desired, t0, t_end)
        if r is None:
            no_react += 1
            continue
        react.append(r)
        # pronto = pods pedidos NESTA reação disponíveis: mesmas janelas e só depois do pedido
        # (pods de um scale-up anterior à janela ficando prontos não contam como reação)
        q = first_increase(available, t0 + r, t_end)
        if q is not None:
            ready.append(r + q)
    ups = increases(desired)
    in_window = lambda t: any(start + a <= t <= start + b + grace for a, b in windows)
    false_ups = sum(1 for t in ups if not in_window(t) and (count_until is None or t <= count_until))
    mean = lambda xs: round(float(np.mean(xs)), 2) if xs else float("nan")
    return {"reaction_time_s": mean(react), "ready_time_s": mean(ready),
            "windows_no_reaction": no_react, "n_windows": len(windows),
            "scaleups": len(ups), "false_scaleups": false_ups}


def save_series(path, desired, available, start):
    """Séries de réplicas da execução (uma linha por passo de 5 s), para rever métricas depois."""
    d, a = dict(desired), dict(available)
    fmt = lambda v: "" if v is None else f"{v:g}"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "offset_seconds", "desired", "available"])
        for t in sorted(set(d) | set(a)):
            w.writerow([int(t), int(t - start), fmt(d.get(t)), fmt(a.get(t))])


def pod_seconds(available, start, end):
    """Integral (degraus) das réplicas disponíveis no intervalo [start, end]."""
    pts = [(t, v) for t, v in available if start <= t <= end]
    if len(pts) < 2:
        return float("nan")
    total = sum(pts[i][1] * (pts[i + 1][0] - pts[i][0]) for i in range(len(pts) - 1))
    return round(total, 1)


# =============================================================================
# Prometheus
# =============================================================================

def prom_range(query, start, end, step=STEP):
    r = requests.get(f"{PROMETHEUS_URL}/api/v1/query_range",
                     params={"query": query, "start": start, "end": end, "step": step}, timeout=30)
    r.raise_for_status()
    res = r.json()["data"]["result"]
    return [(float(t), float(v)) for t, v in res[0]["values"]] if res else []


def prom_instant(query, t):
    r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query, "time": t}, timeout=30)
    r.raise_for_status()
    res = r.json()["data"]["result"]
    return float(res[0]["value"][1]) if res else float("nan")


def latency_in_windows(start, windows, ns=NAMESPACE):
    """p95 (ms) por janela e % de requisições acima do SLO, somando as janelas."""
    p95s, over, total = [], 0.0, 0.0
    le = f"{SLO_SECONDS:g}"
    for a, b in windows:
        w = f"{int(b - a)}s"
        t = start + b
        p95 = prom_instant(f'histogram_quantile(0.95, sum by (le) (increase('
                           f'http_request_duration_seconds_bucket{{namespace="{ns}"}}[{w}])))', t)
        if math.isfinite(p95):
            p95s.append(p95 * 1000)
        cnt = prom_instant(f'sum(increase(http_request_duration_seconds_count{{namespace="{ns}"}}[{w}]))', t)
        ok = prom_instant(f'sum(increase(http_request_duration_seconds_bucket{{namespace="{ns}", le="{le}"}}[{w}]))', t)
        if math.isfinite(cnt) and math.isfinite(ok) and cnt > 0:
            total += cnt
            over += max(cnt - ok, 0.0)
    p95 = round(float(np.mean(p95s)), 1) if p95s else float("nan")
    pct = round(100 * over / total, 3) if total > 0 else float("nan")
    return p95, pct


def slo_whole_run(start, duration, ns=NAMESPACE):
    w, t, le = f"{int(duration)}s", start + duration, f"{SLO_SECONDS:g}"
    cnt = prom_instant(f'sum(increase(http_request_duration_seconds_count{{namespace="{ns}"}}[{w}]))', t)
    ok = prom_instant(f'sum(increase(http_request_duration_seconds_bucket{{namespace="{ns}", le="{le}"}}[{w}]))', t)
    return round(100 * max(cnt - ok, 0) / cnt, 3) if cnt and math.isfinite(cnt) and cnt > 0 else float("nan")


def k6_values(path):
    if not path or not Path(path).exists():
        return float("nan"), float("nan")
    m = json.loads(Path(path).read_text()).get("metrics", {})
    p95 = m.get("http_req_duration", {}).get("values", {}).get("p(95)", float("nan"))
    err = m.get("http_req_failed", {}).get("values", {}).get("rate", float("nan"))
    return round(p95, 1), err


def collect(mode, scenario, run, start, duration, k6_summary=None, ns=NAMESPACE, series=None):
    end = start + duration
    windows = ANOMALY_PHASES[scenario]
    desired = prom_range(f'max(kube_horizontalpodautoscaler_status_desired_replicas'
                         f'{{namespace="{ns}", horizontalpodautoscaler="{HPA}"}})', start, end)
    available = prom_range(f'max(kube_deployment_status_replicas_available'
                           f'{{namespace="{ns}", deployment="{DEPLOY}"}})', start, end)
    if not desired or not available:
        print("ERRO: sem réplicas no Prometheus. kube-state-metrics está rodando? (make status)")
        sys.exit(1)
    if series:
        save_series(series, desired, available, start)
    row = {"mode": mode, "scenario": scenario, "run": f"run{run}", "start": int(start), "duration": duration}
    # scale-ups falsos até o fim do k6 + grace; custo (pod_seconds) até o fim da janela (decisão 17)
    row.update(reaction_metrics(desired, available, start, windows,
                                count_until=start + K6_END_SECONDS[scenario] + GRACE_SECONDS))
    row["p95_anom_ms"], row["slo_viol_anom_pct"] = latency_in_windows(start, windows, ns)
    row["slo_viol_all_pct"] = slo_whole_run(start, duration, ns)
    row["pod_seconds"] = pod_seconds(available, start, end)
    row["k6_p95_ms"], row["k6_error_rate"] = k6_values(k6_summary)
    return row


def upsert(path, row):
    """Grava/substitui a linha (mode, scenario, run): rodar de novo não duplica."""
    rows = []
    if Path(path).exists():
        rows = [r for r in csv.DictReader(open(path))
                if (r["mode"], r["scenario"], r["run"]) != (row["mode"], row["scenario"], row["run"])]
    rows.append({k: row.get(k, "") for k in FIELDS})
    rows.sort(key=lambda r: (r["mode"], r["scenario"], int(str(r["run"])[3:])))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Métricas do HPA por execução (Fase 3)")
    ap.add_argument("--mode")
    ap.add_argument("--scenario", choices=list(ANOMALY_PHASES))
    ap.add_argument("--run", type=int)
    ap.add_argument("--start", type=float, help="Unix timestamp do início do k6")
    ap.add_argument("--duration", type=int)
    ap.add_argument("--k6-summary", default=None)
    ap.add_argument("--output", required=True)
    ap.add_argument("--series", default=None, help="CSV com as réplicas desejadas e disponíveis")
    ap.add_argument("--recalc", default=None, help="hpa_results.csv: recalcula cada linha pelo Prometheus")
    ap.add_argument("--k6-dir", default=None, help="com --recalc: pasta com <modo>_<cen>_runN.json")
    ap.add_argument("--series-dir", default=None, help="com --recalc: pasta das séries")
    a = ap.parse_args()
    if a.recalc:
        jobs = [(r["mode"], r["scenario"], int(r["run"][3:]), float(r["start"]), int(float(r["duration"])))
                for r in csv.DictReader(open(a.recalc))]
    elif None in (a.mode, a.scenario, a.run, a.start, a.duration):
        ap.error("informe --mode, --scenario, --run, --start e --duration (ou --recalc)")
    else:
        jobs = [(a.mode, a.scenario, a.run, a.start, a.duration)]
    for mode, sc, run, start, dur in jobs:
        key = f"{mode}_{sc}_run{run}"
        k6 = f"{a.k6_dir}/{key}.json" if a.recalc and a.k6_dir else a.k6_summary
        series = f"{a.series_dir}/{key}.csv" if a.recalc and a.series_dir else a.series
        r = collect(mode, sc, run, start, dur, k6, series=series)
        upsert(a.output, r)
        print("✓ " + (f"{key}: " if a.recalc else "") + " | ".join(f"{k}={r[k]}" for k in FIELDS[5:]))
