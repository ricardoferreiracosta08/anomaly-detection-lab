"""
stats_tlc.py — Análise estatística (IC da média pelo TLC + t de Student)
PPGCC/UFMA — Ricardo F. Costa — 2026

Base: material da disciplina (Prof. Mário Teixeira)
  [AR] 05_analise-resultados  slides 49–52 (IC), 58–59 (controle do erro),
       64 (teste visual), 66 (t de Student), 23–24 (box-plot)

Procedimento (por célula = cenário × detector, ou cenário × modo do HPA):
  Yi   = métrica de UMA execução (F1, p95 do k6, tempo de reação...)
  Ȳ    = média dos N valores;  S² = Σ(Yi − Ȳ)²/(N − 1);  S = √S²
  H    = t(1−α/2; N−1) · S/√N     (erro-padrão da média pelo TLC)
  IC   = Ȳ ± H;  precisão relativa = H/Ȳ
  H_tDP = t · S  (forma literal dos slides 52/55, mantida para comparação)

Uso:
  python stats_tlc.py phase1 --detections /results/detection_results.csv \\
         --k6 /results/k6_summary.csv --out /results/stats/phase1
  python stats_tlc.py phase3 --hpa /results/hpa/hpa_results.csv \\
         --k6 /results/hpa/k6_summary.csv --out /results/stats/phase3
"""
import argparse
import itertools
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ALPHA = 0.05
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SCEN_ORDER = ["burst", "rampup", "shift"]
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e6e5e0", "axes.axisbelow": True,
                     "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
                     "figure.dpi": 150, "savefig.bbox": "tight"})


# =============================================================================
# Núcleo estatístico
# =============================================================================

def ic(values, alpha=ALPHA):
    """IC da média pelo TLC + descritivas. Valores infinitos (ex.: MTTD sem detecção)
    não entram na média; são contados em n_inf."""
    y = np.asarray(pd.to_numeric(pd.Series(values), errors="coerce"), dtype=float)
    n_inf = int(np.isinf(y).sum())
    y = y[np.isfinite(y)]
    N = y.size
    row = {"N": N, "n_inf": n_inf}
    if N == 0:
        return row
    row.update(media=y.mean(), mediana=float(np.median(y)), min=y.min(), max=y.max(),
               Q1=float(np.percentile(y, 25)), Q3=float(np.percentile(y, 75)))
    if N < 2:
        return row
    S = y.std(ddof=1)
    t = stats.t.ppf(1 - alpha / 2, N - 1)
    H = t * S / np.sqrt(N)
    row.update(S2=S ** 2, DP=S, EP=S / np.sqrt(N), t=t, H=H, IC_inf=y.mean() - H, IC_sup=y.mean() + H,
               H_sobre_Y=(H / y.mean()) if y.mean() != 0 else np.nan, H_tDP=t * S,
               shapiro_p=(stats.shapiro(y).pvalue if N >= 3 and np.ptp(y) > 0 else np.nan))
    return row


def replicas_needed(values, rel=0.10, alpha=ALPHA):
    """[AR 58–59] menor r com t(1−α/2; r−1)·S/√r ≤ rel·Ȳ, usando S do experimento atual."""
    y = np.asarray(pd.to_numeric(pd.Series(values), errors="coerce"), dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 2 or y.mean() == 0:
        return np.nan
    S, beta = y.std(ddof=1), rel * abs(y.mean())
    if S == 0:
        return 2
    for r in range(2, 100000):
        if stats.t.ppf(1 - alpha / 2, r - 1) * S / np.sqrt(r) <= beta:
            return r
    return np.nan


def t_test(a, b, alpha=ALPHA):
    """[AR 66] t = (X̄A − X̄B)/√(varA/nA + varB/nB), gl = nA + nB − 2; + teste visual [AR 64]."""
    a = np.asarray(a, float); a = a[np.isfinite(a)]
    b = np.asarray(b, float); b = b[np.isfinite(b)]
    if a.size < 2 or b.size < 2:
        return {}
    se = np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    t = (a.mean() - b.mean()) / se if se > 0 else 0.0
    gl = a.size + b.size - 2
    ttab = stats.t.ppf(1 - alpha / 2, gl)
    p = 2 * stats.t.sf(abs(t), gl)
    A, B = ic(a), ic(b)
    if A["IC_sup"] < B["IC_inf"] or B["IC_sup"] < A["IC_inf"]:
        vis = "Caso 1: ICs não sobrepostos"
    elif B["IC_inf"] <= A["media"] <= B["IC_sup"] or A["IC_inf"] <= B["media"] <= A["IC_sup"]:
        vis = "Caso 2: média dentro do IC do outro"
    else:
        vis = "Caso 3: sobrepostos, médias fora"
    return dict(media_A=a.mean(), media_B=b.mean(), dif=a.mean() - b.mean(), t=t, gl=gl, t_tab=ttab, p=p,
                visual=vis, conclusao="médias diferentes" if abs(t) > ttab else "sem diferença significativa")


def slide55():
    """Validação: reproduz o exemplo do slide 55 da disciplina."""
    ex = [331.993, 447.532, 366.052, 420.858, 403.524, 355.959, 464.856, 492.144, 393.393, 389.200]
    r = ic(ex)
    r["H_slide55_t226"] = 2.26 * r["DP"]
    return pd.DataFrame([r])


def table(df, groups, metrics):
    rows = []
    for key, g in df.groupby(groups, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        for m in metrics:
            if m in g:
                rows.append({**dict(zip(groups, key)), "metrica": m, **ic(g[m]),
                             "r_para_HY_10pct": replicas_needed(g[m], 0.10),
                             "r_para_HY_20pct": replicas_needed(g[m], 0.20)})
    return pd.DataFrame(rows)


def pairwise(df, scen_col, group_col, metric, pairs=None):
    rows = []
    for s, g in df.groupby(scen_col, sort=False):
        levels = list(dict.fromkeys(g[group_col]))
        for a, b in (pairs or itertools.combinations(levels, 2)):
            if a in levels and b in levels:
                r = t_test(g[g[group_col] == a][metric], g[g[group_col] == b][metric])
                if r:
                    rows.append({scen_col: s, "metrica": metric, "A": a, "B": b, **r})
    # com N < 2 por grupo não há teste t: tabela vazia, mas com as colunas (o relatório filtra por elas)
    return pd.DataFrame(rows, columns=[scen_col, "metrica", "A", "B", "media_A", "media_B", "dif", "t", "gl",
                                       "t_tab", "p", "visual", "conclusao"])


# =============================================================================
# Figuras
# =============================================================================

def colors(levels):
    """Cor fixa por detector/modo; a variante *_online herda a cor do detector base
    (diferenciada por marcador vazado/hachura), sem reciclar a paleta."""
    bases = list(dict.fromkeys(lv.replace("_online", "") for lv in levels))
    base_col = {b: PALETTE[i] if i < len(PALETTE) else "#7a7a7a" for i, b in enumerate(bases)}
    return {lv: base_col[lv.replace("_online", "")] for lv in levels}


def fig_ic(T, group, metric, levels, path, ylabel):
    sub = T[T.metrica == metric]
    if sub.empty:
        return
    scen = [s for s in SCEN_ORDER if s in set(sub.scenario)]
    col, K = colors(levels), len(levels)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, lv in enumerate(levels):
        s = sub[sub[group] == lv].set_index("scenario").reindex(scen)
        online = lv.endswith("_online")
        ax.errorbar(np.arange(len(scen)) + (i - (K - 1) / 2) * 0.8 / K, s["media"], yerr=s.get("H"),
                    fmt="s" if online else "o", ms=7, capsize=4, lw=2, color=col[lv], label=lv,
                    markerfacecolor="white" if online else col[lv])
    ax.set_xticks(range(len(scen))); ax.set_xticklabels(scen)
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, ncol=min(K, 6), loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.savefig(path); plt.close(fig)


def fig_box(df, group, metric, levels, path, ylabel):
    scen = [s for s in SCEN_ORDER if s in set(df.scenario)]
    col, K = colors(levels), len(levels)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    pos, data, cs = [], [], []
    for i, s in enumerate(scen):
        for j, lv in enumerate(levels):
            v = pd.to_numeric(df[(df.scenario == s) & (df[group] == lv)][metric], errors="coerce")
            v = v[np.isfinite(v)]
            if len(v):
                pos.append(i * (K + 1) + j); data.append(v.values); cs.append((col[lv], lv.endswith("_online")))
    if not data:
        plt.close(fig); return
    bp = ax.boxplot(data, positions=pos, widths=0.75, whis=1.5, patch_artist=True)
    for p_, (c_, online) in zip(bp["boxes"], cs):
        p_.set_facecolor(c_); p_.set_alpha(0.35 if online else 0.75)
        if online:
            p_.set_hatch("///")
    for m_ in bp["medians"]:
        m_.set_color("#0b0b0b")
    ax.set_xticks([i * (K + 1) + (K - 1) / 2 for i in range(len(scen))]); ax.set_xticklabels(scen)
    ax.set_ylabel(ylabel)
    ax.legend([plt.Rectangle((0, 0), 1, 1, facecolor=col[lv], alpha=0.35 if lv.endswith("_online") else 0.75,
                             hatch="///" if lv.endswith("_online") else None) for lv in levels], levels,
              frameon=False, ncol=min(K, 6), loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.savefig(path); plt.close(fig)


def fig_dots(k6, metric, path, ylabel, group=None):
    scen = [s for s in SCEN_ORDER if s in set(k6.scenario)]
    fig, axs = plt.subplots(1, len(scen), figsize=(4 * len(scen), 3.4), squeeze=False)
    for ax, s in zip(axs[0], scen):
        g = k6[k6.scenario == s]
        y = pd.to_numeric(g[metric], errors="coerce").values
        x = g["run"].str.extract(r"(\d+)")[0].astype(int).values
        r = ic(y)
        ax.scatter(x, y, s=30, color=PALETTE[0], zorder=3, label="valor de cada execução")
        if "H" in r:
            ax.axhspan(r["IC_inf"], r["IC_sup"], color="#0b0b0b", alpha=0.12, label="IC95% da média")
            ax.axhline(r["media"], color="#0b0b0b", lw=1.2)
        ax.set_title(s, loc="left"); ax.set_xlabel("execução")
    axs[0][0].set_ylabel(ylabel)
    h, l = axs[0][0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 0.0))
    fig.savefig(path); plt.close(fig)


def fig_interaction(T, group, metric, levels, path, ylabel):
    sub = T[T.metrica == metric]
    scen = [s for s in SCEN_ORDER if s in set(sub.scenario)]
    if sub.empty or len(scen) < 2:
        return
    col = colors(levels)
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    for lv in levels:
        s = sub[sub[group] == lv].set_index("scenario").reindex(scen)
        ax.plot(range(len(scen)), s["media"], "-o", color=col[lv], lw=2, ms=7)
        ax.text(len(scen) - 1 + 0.08, s["media"].iloc[-1], lv, va="center")
    ax.set_xticks(range(len(scen))); ax.set_xticklabels(scen); ax.set_xlim(-0.2, len(scen) - 0.4 + 0.7)
    ax.set_ylabel(ylabel)
    fig.savefig(path); plt.close(fig)


# =============================================================================
# Relatório
# =============================================================================

def fmt(v, d=3):
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{d}f}"


def md_ic_table(T, group, metric, d=3):
    sub = T[T.metrica == metric]
    lines = [f"| cenário | {group} | N | média | DP | H | IC95% | H/Ȳ | Shapiro p |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sub.itertuples():
        g = getattr(r, group)
        lines.append(f"| {r.scenario} | {g} | {r.N} | {fmt(getattr(r,'media',np.nan),d)} | {fmt(getattr(r,'DP',np.nan),d)} | "
                     f"{fmt(getattr(r,'H',np.nan),d)} | {fmt(getattr(r,'IC_inf',np.nan),d)} – {fmt(getattr(r,'IC_sup',np.nan),d)} | "
                     f"{fmt(100*getattr(r,'H_sobre_Y',np.nan),1)}% | {fmt(getattr(r,'shapiro_p',np.nan),3)} |")
    return lines


def write_outputs(out, sheets, md):
    os.makedirs(out, exist_ok=True)
    for name, T in sheets.items():
        T.to_csv(os.path.join(out, f"{name}.csv"), index=False)
    try:
        with pd.ExcelWriter(os.path.join(out, "estatistica.xlsx")) as xw:
            for name, T in sheets.items():
                T.to_excel(xw, sheet_name=name[:31], index=False)
    except ImportError:
        pass
    with open(os.path.join(out, "relatorio.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"✓ Estatística → {out}/ (relatorio.md, estatistica.xlsx, *.csv, fig_*.png)")


# =============================================================================
# Fase 1: detectores + k6
# =============================================================================

def phase1(det_path, k6_path, out):
    det = pd.read_csv(det_path)
    det["mttd_seconds"] = pd.to_numeric(det["mttd_seconds"].replace({"inf": np.inf}), errors="coerce")
    det["_rep"] = det["run"].str.extract(r"(\d+)")[0].astype(int)
    order = ["EWMA", "IF", "LOF", "DBSCAN", "AE"]
    present = set(det.detector)
    dets = [d for b in order for d in (b, f"{b}_online") if d in present]
    dets += sorted(present - set(dets))
    det["detector"] = pd.Categorical(det["detector"], dets, ordered=True)
    det["scenario"] = pd.Categorical(det["scenario"], [s for s in SCEN_ORDER if s in set(det.scenario)], ordered=True)
    det = det.sort_values(["scenario", "detector", "_rep"])
    det["detector"] = det["detector"].astype(str); det["scenario"] = det["scenario"].astype(str)

    os.makedirs(out, exist_ok=True)
    metrics = ["f1", "precision", "recall", "mttd_seconds"]
    T_det = table(det, ["scenario", "detector"], metrics)
    T_t = pd.concat([pairwise(det, "scenario", "detector", m) for m in ["f1", "precision", "recall"]], ignore_index=True)
    sheets = {"0_validacao_slide55": slide55(), "1_IC_detectores": T_det, "2_teste_t": T_t}

    nmax = int(det.groupby(["scenario", "detector"]).size().min())
    if nmax > 3:   # [AR 57]: mesma análise só com as 3 primeiras repetições
        T3 = table(det[det._rep <= 3], ["scenario", "detector"], ["f1"])
        sheets["3_IC_F1_N3"] = T3
    fig_ic(T_det, "detector", "f1", dets, os.path.join(out, "fig_ic_f1.png"), "F1 (média ± H, IC95%)")
    fig_box(det, "detector", "f1", dets, os.path.join(out, "fig_box_f1.png"), "F1 por execução")
    fig_ic(T_det, "detector", "mttd_seconds", dets, os.path.join(out, "fig_ic_mttd.png"), "MTTD (s, média ± H)")

    md = ["# Fase 1 — IC da média (TLC) e t de Student", "",
          f"Entrada: `{det_path}` · {len(det)} avaliações · N por célula: {nmax} · α = {ALPHA}", "",
          "## F1", ""] + md_ic_table(T_det, "detector", "f1")
    if k6_path and os.path.exists(k6_path):
        k6 = pd.read_csv(k6_path)
        k6 = k6[k6["mode"].fillna("").astype(str).isin(["", "nan"])] if "mode" in k6 else k6
        km = [c for c in ["http_req_duration_avg", "http_req_duration_med", "http_req_duration_p(95)",
                          "http_req_duration_p(99)", "http_req_failed_rate"] if c in k6]
        T_k6 = table(k6.assign(grupo="k6"), ["scenario", "grupo"], km)
        sheets["4_IC_k6"] = T_k6
        if "http_req_duration_p(95)" in k6:
            fig_dots(k6, "http_req_duration_p(95)", os.path.join(out, "fig_k6_p95.png"), "p(95) do k6 (ms)")
        md += ["", "## k6 (latência por execução, ms)", "",
               "| cenário | métrica | N | média | H | IC95% | H/Ȳ |", "|---|---|---|---|---|---|---|"]
        for r in T_k6.itertuples():
            md.append(f"| {r.scenario} | {r.metrica} | {r.N} | {fmt(getattr(r,'media',np.nan),1)} | {fmt(getattr(r,'H',np.nan),1)} | "
                      f"{fmt(getattr(r,'IC_inf',np.nan),1)} – {fmt(getattr(r,'IC_sup',np.nan),1)} | {fmt(100*getattr(r,'H_sobre_Y',np.nan),1)}% |")
    f1t = T_t[T_t.metrica == "f1"]
    md += ["", "## Teste t (F1, slide 66) e teste visual (slide 64)", "",
           "| cenário | par | t | gl | p | visual | conclusão |", "|---|---|---|---|---|---|---|"]
    for r in f1t.itertuples():
        md.append(f"| {r.scenario} | {r.A} × {r.B} | {fmt(r.t,2)} | {r.gl} | {fmt(r.p,4)} | {r.visual.split(':')[0]} | {r.conclusao} |")
    if f1t.empty:
        md += ["", "Sem teste t: é preciso N ≥ 2 execuções por detector e cenário."]
    md += ["", "Com mais de 2 detectores por cenário, os testes par a par são exploratórios: o slide 65 indica ANOVA antes dos pares."]
    write_outputs(out, sheets, md)


# =============================================================================
# Fase 3: HPA A/B/C(/D)
# =============================================================================

def phase3(hpa_path, k6_path, out):
    h = pd.read_csv(hpa_path)
    h["_rep"] = h["run"].str.extract(r"(\d+)")[0].astype(int)
    modes = sorted(set(h["mode"]))
    h["mode"] = h["mode"].astype(str)
    metrics = ["reaction_time_s", "ready_time_s", "p95_anom_ms", "slo_viol_anom_pct", "slo_viol_all_pct",
               "pod_seconds", "scaleups", "false_scaleups", "k6_p95_ms", "k6_error_rate"]
    metrics = [m for m in metrics if m in h]
    T = table(h, ["scenario", "mode"], metrics)
    pairs = [p for p in [("B", "A"), ("B", "C"), ("C", "A"), ("D", "B")] if p[0] in modes and p[1] in modes]
    T_t = pd.concat([pairwise(h, "scenario", "mode", m, pairs) for m in metrics], ignore_index=True)
    os.makedirs(out, exist_ok=True)
    labels = {"reaction_time_s": "tempo de reação (s)", "p95_anom_ms": "p95 nas janelas anômalas (ms)",
              "slo_viol_anom_pct": "% req. > SLO nas anomalias", "pod_seconds": "custo (pod·s)"}
    for m, lab in labels.items():
        if m in metrics:
            fig_ic(T, "mode", m, modes, os.path.join(out, f"fig_ic_{m}.png"), f"{lab} (média ± H)")
            fig_interaction(T, "mode", m, modes, os.path.join(out, f"fig_interacao_{m}.png"), lab)
    md = ["# Fase 3 — HPA reativo × proativo (IC da média e t de Student)", "",
          f"Entrada: `{hpa_path}` · {len(h)} execuções · modos: {', '.join(modes)}", "",
          "A = CPU 50% (atual) · B = CPU 50% + anomalia (detector da Fase 1) · C = CPU mais sensível (controle de custo) · D = ablação", ""]
    for m in metrics:
        md += [f"## {m}", ""] + md_ic_table(T, "mode", m, 2) + [""]
    md += ["## Comparações (t de Student, slide 66)", "", "| cenário | métrica | par | dif | t | p | conclusão |", "|---|---|---|---|---|---|---|"]
    for r in T_t.itertuples():
        md.append(f"| {r.scenario} | {r.metrica} | {r.A} × {r.B} | {fmt(r.dif,2)} | {fmt(r.t,2)} | {fmt(r.p,4)} | {r.conclusao} |")
    if T_t.empty:
        md += ["", "Sem teste t: é preciso N ≥ 2 execuções por modo e cenário."]
    md += ["", "Critério: B é melhor se reduz tempo de reação e violação de SLO em relação a A, com pod·s semelhante ao de C."]
    write_outputs(out, {"1_IC_hpa": T, "2_teste_t": T_t}, md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="IC da média (TLC) + t de Student")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phase1"); p1.add_argument("--detections", required=True); p1.add_argument("--k6"); p1.add_argument("--out", required=True)
    p3 = sub.add_parser("phase3"); p3.add_argument("--hpa", required=True); p3.add_argument("--k6"); p3.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "phase1":
        if not os.path.exists(a.detections):
            sys.exit(f"ERRO: {a.detections} não existe. Rode: make detect")
        phase1(a.detections, a.k6, a.out)
    else:
        if not os.path.exists(a.hpa):
            sys.exit(f"ERRO: {a.hpa} não existe. Rode: make hpa-experiment")
        phase3(a.hpa, a.k6, a.out)
