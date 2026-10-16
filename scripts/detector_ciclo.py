"""
detector_ciclo.py — Custo do detector online no cluster: ciclo e CPU do pod
PPGCC/UFMA — Ricardo F. Costa — 2026

  make detector-ciclo            (últimos 70 min)
  make detector-ciclo MIN=30

Lê do Prometheus o histograma detector_step_seconds (publicado pelo online_detector) na
janela pedida e mostra média, p50, p95, p99 e a fração de ciclos acima de 1, 2 e 5 s.
O ciclo precisa ficar bem abaixo de DETECTOR_STEP_SECONDS (5 s); com o LSTM (6º detector)
o replay com 0,5 núcleo deu p95 = 1,13 s (docs/validacao/lstm_qualificacao_ciclo.csv).
Os percentis vêm dos baldes do histograma (0,05; 0,1; 0,25; 0,5; 1; 2; 5 s): são
interpolados dentro do balde, não exatos.

Mostra também a CPU do pod online-detector (container "detector", em núcleos; limite 0,5):
média, p95 e máximo da taxa de 1 min, amostrada a cada 15 s. O pod roda nos mesmos núcleos
da aplicação (CLUSTER_CPUS): é o "custo da observação" (docs/DETECTOR_ONLINE.md, seção 5).
"""
import argparse
import os
import sys

import requests

PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
NS = os.environ.get("NAMESPACE", "anomaly-lab")


def q(expr):
    r = requests.get(f"{PROM}/api/v1/query", params={"query": expr}, timeout=10).json()
    res = r.get("data", {}).get("result", [])
    return float(res[0]["value"][1]) if res else float("nan")


def main(minutes, step_limit):
    w = f"{minutes}m"
    b = f'detector_step_seconds_bucket{{namespace="{NS}"}}'
    n = q(f'sum(increase(detector_step_seconds_count{{namespace="{NS}"}}[{w}]))')
    if not n or n != n:
        sys.exit(f"✗ sem ciclos do detector nos últimos {minutes} min (o pod está rodando? make detector-logs)")
    mean = q(f'sum(increase(detector_step_seconds_sum{{namespace="{NS}"}}[{w}]))') / n
    pct = {p: q(f"histogram_quantile({p}, sum by (le) (increase({b}[{w}])))") for p in (0.5, 0.95, 0.99)}
    acima = {s: 1 - q(f'sum(increase({b[:-1]}, le="{s}"}}[{w}]))') / n for s in ("1.0", "2.0", "5.0")}  # rótulos do prometheus_client
    print(f"Ciclo do detector online, últimos {minutes} min ({n:.0f} ciclos)")
    print(f"  média {mean:.3f} s · p50 {pct[0.5]:.3f} s · p95 {pct[0.95]:.3f} s · p99 {pct[0.99]:.3f} s")
    print("  acima de 1 s: {:.1%} · acima de 2 s: {:.1%} · acima de 5 s: {:.1%}".format(acima["1.0"], acima["2.0"], acima["5.0"]))
    cpu = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{NS}", container="detector"}}[1m]))'
    c_avg = q(f"avg_over_time(({cpu})[{w}:15s])")
    c_p95 = q(f"quantile_over_time(0.95, ({cpu})[{w}:15s])")
    c_max = q(f"max_over_time(({cpu})[{w}:15s])")
    print(f"  CPU do pod online-detector: média {c_avg:.3f} · p95 {c_p95:.3f} · máx {c_max:.3f} núcleo(s) (limite 0,5)")
    ok = pct[0.95] < step_limit / 2
    print(f"  {'✓' if ok else '⚠'} p95 {'bem abaixo' if ok else 'perto ou acima'} do limite "
          f"(DETECTOR_STEP_SECONDS = {step_limit:.0f} s; critério: p95 < {step_limit / 2:.1f} s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tempo de ciclo do detector online (Prometheus)")
    ap.add_argument("--minutes", type=int, default=70)
    ap.add_argument("--step", type=float, default=float(os.environ.get("DETECTOR_STEP_SECONDS", "5") or 5))
    a = ap.parse_args()
    main(a.minutes, a.step)
