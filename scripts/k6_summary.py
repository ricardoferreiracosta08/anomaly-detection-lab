"""
k6_summary.py — Consolida os summaries do k6 (1 JSON por execução) em CSV
PPGCC/UFMA — Ricardo F. Costa — 2026

Cada execução do k6 grava, via handleSummary + SUMMARY_FILE, um JSON com
data.metrics. Este script extrai, por execução, a latência (http_req_duration:
avg, min, med, max, p90, p95, p99), volume (http_reqs) e erros (http_req_failed).

Nomes aceitos:  burst_run3.json  (Fase 1)   |   B_burst_run3.json  (Fase 3, modo B)

Uso:
  python k6_summary.py --input /results/k6 --output /results/k6_summary.csv
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"^(?:(?P<mode>[A-Z])_)?(?P<scenario>burst|rampup|shift)_run(?P<run>\d+)\.json$")
STATS = ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"]


def parse(path: Path) -> dict:
    m = PATTERN.match(path.name)
    if not m:
        return {}
    data = json.loads(path.read_text())
    metrics = data.get("metrics", data)
    dur = metrics.get("http_req_duration", {}).get("values", {})
    reqs = metrics.get("http_reqs", {}).get("values", {})
    failed = metrics.get("http_req_failed", {}).get("values", {})
    row = {
        "mode": m.group("mode") or "",
        "scenario": m.group("scenario"),
        "run": f"run{int(m.group('run'))}",
        "http_reqs": reqs.get("count", ""),
        "http_reqs_rate": round(reqs.get("rate", 0.0), 3) if reqs else "",
        "http_req_failed_rate": round(failed.get("rate", 0.0), 6) if failed else "",
    }
    for s in STATS:
        v = dur.get(s)
        row[f"http_req_duration_{s}"] = round(v, 3) if isinstance(v, (int, float)) else ""
    return row


def main():
    ap = argparse.ArgumentParser(description="Summaries do k6 → CSV por execução")
    ap.add_argument("--input", required=True, help="Diretório com <cenario>_runN.json")
    ap.add_argument("--output", required=True, help="CSV de saída")
    args = ap.parse_args()

    rows = [r for p in sorted(Path(args.input).glob("*.json")) if (r := parse(p))]
    if not rows:
        print(f"Nenhum summary do k6 em {args.input} (esperado: burst_run1.json, ...)")
        sys.exit(1)
    rows.sort(key=lambda r: (r["mode"], r["scenario"], int(r["run"][3:])))
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"✓ {len(rows)} execuções → {args.output}")


if __name__ == "__main__":
    main()
