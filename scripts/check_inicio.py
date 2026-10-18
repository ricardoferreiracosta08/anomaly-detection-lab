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

O trecho é mostrado em duas partes, separadas em EVAL_SKIP_SECONDS (padrão 60):
  0–60 s    acomodação: a troca aquecimento → roteiro (fora da avaliação da Fase 1)
  60 s–1ª anomalia   ruído real que conta na avaliação
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


def count_initial(d, scenario, split=None):
    """Alertas online antes da 1ª janela anômala, no total e nas duas partes do trecho:
    [0, split) acomodação e [split, 1ª anomalia). Chaves: pontos, pontos_1, pontos_2,
    online_X, online_X_1, online_X_2."""
    split = float(os.environ.get("EVAL_SKIP_SECONDS", "60") or 0) if split is None else split
    first = min(a for a, _ in ANOMALY_PHASES[scenario])
    off = pd.to_numeric(d["offset_seconds"], errors="coerce")
    ini = d[off < first]
    p1, p2 = ini[off[off < first] < split], ini[off[off < first] >= split]
    out = {"inicio_s": first, "split_s": split, "pontos": len(ini), "pontos_1": len(p1), "pontos_2": len(p2)}
    for c in sorted(c for c in d.columns if c.startswith("online_")):
        f = lambda x: int((pd.to_numeric(x[c], errors="coerce").fillna(0) > 0.5).sum())
        out[c], out[c + "_1"], out[c + "_2"] = f(ini), f(p1), f(p2)
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
    dets = sorted({k for _, r in rows for k in r if k.startswith("online_") and not k.endswith(("_1", "_2"))})
    if not dets:
        sys.exit("✗ os CSVs não têm colunas online_* (o detector online estava rodando?)")

    split = rows[0][1]["split_s"]
    print(f"Alertas online antes da 1ª anomalia — {directory}")
    print(f"cada célula: [0, {split:.0f}) s acomodação (fora da avaliação) | [{split:.0f} s, 1ª anomalia) conta na avaliação")
    print(f"{'execução':<22}{'início':>7}" + "".join(f"{d[7:]:>13}" for d in dets))
    tot = {d: [0, 0, 0, 0] for d in dets}
    for name, r in rows:
        cells = []
        for d in dets:
            if d in r:
                cells.append(f"{r[d + '_1']}/{r['pontos_1']} | {r[d + '_2']}/{r['pontos_2']}")
                t = tot[d]; t[0] += r[d + "_1"]; t[1] += r["pontos_1"]; t[2] += r[d + "_2"]; t[3] += r["pontos_2"]
            else:
                cells.append("—")
        print(f"{name:<22}{r['inicio_s']:>6}s" + "".join(f"{c:>13}" for c in cells))
    pct = lambda a, n: f"{100 * a / n:.0f}%" if n else "—"
    print(f"{'total':<22}{'':>7}" + "".join(f"{pct(t[0], t[1]) + ' | ' + pct(t[2], t[3]):>13}" for t in (tot[d] for d in dets)))
    print("Critério (docs/PILOTOS.md): perto de 0% (alguns alertas isolados são esperados com K = 2).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Alertas online antes da 1ª janela anômala")
    ap.add_argument("dir", nargs="?", default="/datasets")
    main(ap.parse_args().dir)
