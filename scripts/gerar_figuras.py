"""Figuras do artigo a partir dos resultados reais.

  fase1_f1.pdf        F1 por detector e cenário, online x offline, com IC 95%
  fase3_replicas.pdf  réplicas pedidas e latência p95 médias por modo, 3 cenários

Uso:
  python3 scripts/gerar_figuras.py --ic-fase1 <fase1_corrigido/stats/phase1/1_IC_detectores.csv> \
      --fase3 <pasta com results/hpa/series e datasets_hpa> --saida <pasta>
"""
import argparse, glob, os
import pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--ic-fase1", required=True)
ap.add_argument("--fase3", required=True)
ap.add_argument("--saida", default="figs")
a = ap.parse_args()
os.makedirs(a.saida, exist_ok=True)

INK2 = "#52514e"
MODE = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
SC = ["burst", "rampup", "shift"]
GAB = {"burst": [(150, 185), (305, 345), (465, 500)],
       "rampup": [(175, 210), (280, 320), (335, 380), (395, 465)],
       "shift": [(150, 300), (420, 570), (660, 810)]}
FIM = {"burst": 633, "rampup": 575, "shift": 925}  # fim do k6 + 15 s
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 7.5,
                     "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.5,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": INK2, "legend.frameon": False})

# F1 por detector, online x offline
d = pd.read_csv(a.ic_fase1); d = d[d.metrica == "f1"]
dets = ["LSTM", "IF", "AE", "DBSCAN", "LOF", "EWMA"]
fig, axs = plt.subplots(1, 3, figsize=(6.3, 2.35), sharey=True)
for ax, sc in zip(axs, SC):
    for i, det in enumerate(dets):
        for nome, off, mk, fc, col in [(det + "_online", 0.13, "o", MODE["A"], MODE["A"]),
                                       (det, -0.13, "s", "white", INK2)]:
            r = d[(d.scenario == sc) & (d.detector == nome)].iloc[0]
            ax.errorbar(r.media, i + off, xerr=[[r.media - r.IC_inf], [r.IC_sup - r.media]], fmt=mk,
                        ms=4.5, color=col, mfc=fc, mec=col, ecolor=col, elinewidth=1, capsize=1.8)
    ax.set_title(sc); ax.set_xlim(-0.03, 0.7); ax.set_xlabel("F1 (média e IC 95%)")
axs[0].set_yticks(range(len(dets)), dets); axs[0].invert_yaxis()
h1 = plt.Line2D([], [], marker="o", color=MODE["A"], ls="", ms=4.5, label="online (ao vivo)")
h2 = plt.Line2D([], [], marker="s", color=INK2, mfc="white", ls="", ms=4.5, label="offline")
fig.legend(handles=[h1, h2], loc="upper center", ncol=2, bbox_to_anchor=(0.55, 1.03))
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(os.path.join(a.saida, "fase1_f1.pdf")); plt.close(fig)

# Réplicas e latência por modo, 3 cenários
fig, axs = plt.subplots(2, 3, figsize=(6.4, 3.4), sharex="col")
for j, sc in enumerate(SC):
    for m in "ABC":
        rs = [pd.read_csv(f).set_index("offset_seconds").desired
              for f in glob.glob(os.path.join(a.fase3, "results/hpa/series", f"{m}_{sc}_*.csv"))]
        ls = [pd.read_csv(f).set_index("offset_seconds").latency_p95 * 1000
              for f in glob.glob(os.path.join(a.fase3, "datasets_hpa", f"{m}_{sc}_*.csv"))]
        r = pd.concat(rs, axis=1).mean(axis=1); r = r[r.index <= FIM[sc]]
        l = pd.concat(ls, axis=1).mean(axis=1); l = l[l.index <= FIM[sc]]
        axs[0, j].step(r.index, r.values, where="post", color=MODE[m], lw=1.3, label=f"modo {m}")
        axs[1, j].plot(l.index, l.values, color=MODE[m], lw=1.1)
    for ax in axs[:, j]:
        for ini, fim in GAB[sc]:
            ax.axvspan(ini, fim, color="#e34948", alpha=0.10, lw=0)
    axs[0, j].axhline(8, color=INK2, lw=0.7, ls="--"); axs[0, j].set_ylim(1.5, 8.7)
    axs[0, j].set_title(sc); axs[1, j].set_xlabel("tempo (s)")
axs[0, 0].set_ylabel("réplicas pedidas"); axs[1, 0].set_ylabel("latência p95 (ms)")
axs[0, 0].legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.12), fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(a.saida, "fase3_replicas.pdf")); plt.close(fig)
print("figuras em", a.saida)
