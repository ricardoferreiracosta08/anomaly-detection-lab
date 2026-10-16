"""
check_inicio.py — Alertas do detector online ANTES da 1ª anomalia de cada execução
PPGCC/UFMA — Ricardo F. Costa — 2026

  make check-inicio                    (datasets/)
  make check-inicio DIR=datasets_hpa   (Fase 3)

Antes da primeira janela anômala do cenário não há anomalia (label = 0): todo
alerta online_* ali é falso positivo. Com a referência do detector feita de
silêncio, esse trecho ficava 53–87% em alerta (piloto 2, docs/PILOTOS.md). Com o
aquecimento e o piso do σ, o esperado é perto de zero (alguns isolados com K = 2).

O início da 1ª janela vem de ANOMALY_PHASES (export_metrics.py), não é fixo.
O cenário é lido do nome do arquivo: <cenario>_runN.csv ou <modo>_<cenario>_runN.csv.
"""
import argparse
import glob
import os
import re
import sys

import pandas as pd

from export_metrics import ANOMALY_PHASES


def scenario_of(path):
    m = re.match(r"^(?:[A-Z]_)?([a-z]+)_run\d+\.csv$", os.path.basename(path))
    return m.group(1) if m and m.group(1) in ANOMALY_PHASES else None


def count_initial(d, scenario):
    """{'pontos': n, 'online_X': alertas, ...} no trecho antes da 1ª janela anômala."""
    first = min(a for a, _ in ANOMALY_PHASES[scenario])
    ini = d[pd.to_numeric(d["offset_seconds"], errors="coerce") < first]
    out = {"inicio_s": first, "pontos": len(ini)}
    for c in sorted(c for c in d.columns if c.startswith("online_")):
        out[c] = int((pd.to_numeric(ini[c], errors="coerce").fillna(0) > 0.5).sum())
    return out


def main(directory):
    files = sorted(glob.glob(os.path.join(directory, "*.csv")))
    if not files:
        sys.exit(f"✗ nenhum CSV em {directory}")
    rows = []
    for f in files:
        sc = scenario_of(f)
        if sc is None:
            print(f"  (pulando {os.path.basename(f)}: cenário não reconhecido no nome)")
            continue
        r = count_initial(pd.read_csv(f), sc)
        rows.append((os.path.basename(f), r))
    if not rows:
        sys.exit("✗ nenhum CSV com nome <cenario>_runN.csv ou <modo>_<cenario>_runN.csv")
    dets = sorted({k for _, r in rows for k in r if k.startswith("online_")})
    if not dets:
        sys.exit("✗ os CSVs não têm colunas online_* (o detector online estava rodando?)")

    print(f"Alertas online antes da 1ª anomalia (alertas / pontos) — {directory}")
    print(f"{'execução':<26}{'início':>7}" + "".join(f"{d[7:]:>10}" for d in dets))
    tot = {d: [0, 0] for d in dets}
    for name, r in rows:
        cells = []
        for d in dets:
            if d in r:
                cells.append(f"{r[d]}/{r['pontos']}")
                tot[d][0] += r[d]; tot[d][1] += r["pontos"]
            else:
                cells.append("—")
        print(f"{name:<26}{r['inicio_s']:>6}s" + "".join(f"{c:>10}" for c in cells))
    print(f"{'total':<26}{'':>7}" + "".join(
        f"{(100 * a / n if n else 0):>9.0f}%" for a, n in (tot[d] for d in dets)))
    print("Critério (docs/PILOTOS.md): perto de 0% (alguns alertas isolados são esperados com K = 2).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Alertas online antes da 1ª janela anômala")
    ap.add_argument("dir", nargs="?", default="/datasets")
    main(ap.parse_args().dir)
