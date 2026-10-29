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

Comparações:
  Fase 1 — PAREADO (decisão 1, docs/DECISOES_METODO.md): detectores e formas (offline,
           online) saem das MESMAS execuções. Para cada execução, d = Y_A − Y_B; com
           as N diferenças, IC da média de d pela mesma fórmula (d̄ ± t·S_d/√N, gl = N−1).
           Se o IC não contém o 0, as médias são diferentes. t = d̄/(S_d/√N), p bilateral.
  Fase 3 — NÃO PAREADO [AR 66]: A, B e C são execuções independentes;
           t = (X̄A − X̄B)/√(varA/nA + varB/nB), gl = nA + nB − 2; + teste visual [AR 64].

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
                visual=vis, conclusao="médias diferentes" if abs(t) > ttab else "sem diferença significativa",
                metodo="não pareado", n=min(a.size, b.size), IC_dif_inf=np.nan, IC_dif_sup=np.nan)


def paired_test(a, b, alpha=ALPHA):
    """Teste pareado (decisão 1, Fase 1): a e b alinhados pela mesma execução.
    IC da média das diferenças d = a − b: d̄ ± t(1−α/2; N−1)·S_d/√N (mesma fórmula do IC da média)."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    N = a.size
    if N < 2:
        return {}
    d = a - b
    Sd = d.std(ddof=1)
    ttab = stats.t.ppf(1 - alpha / 2, N - 1)
    H = ttab * Sd / np.sqrt(N)
    t = d.mean() / (Sd / np.sqrt(N)) if Sd > 0 else (0.0 if d.mean() == 0 else np.inf * np.sign(d.mean()))
    p = 2 * stats.t.sf(abs(t), N - 1) if np.isfinite(t) else 0.0
    lo, hi = d.mean() - H, d.mean() + H
    differ = (lo > 0 or hi < 0) if Sd > 0 else d.mean() != 0
    return dict(media_A=a.mean(), media_B=b.mean(), dif=d.mean(), t=t, gl=N - 1, t_tab=ttab, p=p,
                visual=f"IC da diferença [{lo:.3f}; {hi:.3f}]", conclusao="médias diferentes" if differ else "sem diferença significativa",
                metodo="pareado", n=N, IC_dif_inf=lo, IC_dif_sup=hi)


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


def pairwise(df, scen_col, group_col, metric, pairs=None, paired_on=None):
    """Pares de grupos por cenário. paired_on=<coluna da execução> → teste pareado (Fase 1),
    alinhando A e B pela mesma execução; None → t não pareado (Fase 3)."""
    rows = []
    for s, g in df.groupby(scen_col, sort=False):
        levels = list(dict.fromkeys(g[group_col]))
        for a, b in (pairs or itertools.combinations(levels, 2)):
            if a in levels and b in levels:
                ga, gb = g[g[group_col] == a], g[g[group_col] == b]
                if paired_on:
                    m = ga[[paired_on, metric]].merge(gb[[paired_on, metric]], on=paired_on, suffixes=("_A", "_B"))
                    r = paired_test(m[metric + "_A"], m[metric + "_B"])
                else:
                    r = t_test(ga[metric], gb[metric])
                if r:
                    rows.append({scen_col: s, "metrica": metric, "A": a, "B": b, **r})
    # com N < 2 por grupo não há teste t: tabela vazia, mas com as colunas (o relatório filtra por elas)
    return pd.DataFrame(rows, columns=[scen_col, "metrica", "A", "B", "media_A", "media_B", "dif", "t", "gl",
                                       "t_tab", "p", "visual", "conclusao", "metodo", "n", "IC_dif_inf", "IC_dif_sup"])


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

DET_ORDER = ["EWMA", "IF", "LOF", "DBSCAN", "AE", "LSTM"]


def rule_b_ranking(det):
    """Regra de escolha do detector do B (pré-registro, docs/HPA.md seção 3): para cada
    detector ONLINE, média do F1 em cada cenário e depois a média das médias (cada cenário
    pesa igual). Também a média das médias do MTTD online (desempate): janelas não
    detectadas ficam fora da média; o nº de janelas detectadas vai ao lado. Ordem decrescente de F1."""
    on = det[det.detector.astype(str).str.endswith("_online")]
    if on.empty:
        return pd.DataFrame(columns=["detector", "f1_media_das_medias", "mttd_media_das_medias", "n_cenarios"])
    f1 = on.groupby(["detector", "scenario"])["f1"].mean().unstack("scenario")
    mt = on.assign(m=on["mttd_seconds"].where(np.isfinite(on["mttd_seconds"]))).groupby(
        ["detector", "scenario"])["m"].mean().unstack("scenario")
    r = pd.DataFrame({"f1_media_das_medias": f1.mean(axis=1), "mttd_media_das_medias": mt.mean(axis=1),
                      "n_cenarios": f1.notna().sum(axis=1)})
    if {"windows_detected", "windows_total"} <= set(on.columns):   # MTTD só existe nas janelas detectadas
        w = on.groupby("detector")[["windows_detected", "windows_total"]].sum()
        r["janelas_detectadas"], r["janelas_total"] = w["windows_detected"], w["windows_total"]
    for sc in f1.columns:
        r[f"f1_{sc}"] = f1[sc]
    return r.sort_values("f1_media_das_medias", ascending=False).reset_index()


def planned_pairs(det):
    """Comparações planejadas da Fase 1 (decisão 2), as MESMAS em todos os cenários:
    (1) offline × online do mesmo detector; (2) o vencedor da regra do B (1º do ranking,
    um só para os 3 cenários) × cada um dos outros online. Nada além disso."""
    present = set(det.detector.astype(str))
    off_on = [(b, f"{b}_online") for b in DET_ORDER if b in present and f"{b}_online" in present]
    rank = rule_b_ranking(det)
    winner = rank["detector"].iloc[0] if len(rank) else None
    vs = [(winner, o) for o in rank["detector"].iloc[1:]] if winner else []
    return off_on, vs, winner, rank


def rule_b_choice(rank, vs_f1):
    """Aplica a regra do B. Grupo de empate = o 1º + todos os online cuja diferença para o 1º
    NÃO é significativa em nenhum cenário (teste pareado, decisão 1). Grupo de 1 → o 1º.
    Grupo maior → vence o menor MTTD online (média das 3 médias; janelas não detectadas fora)."""
    first = rank["detector"].iloc[0]
    tied = [first]
    for o in rank["detector"].iloc[1:]:
        d = vs_f1[vs_f1.B == o]
        if len(d) and (d.conclusao != "médias diferentes").all():
            tied.append(o)
    if len(tied) == 1:
        return first, "nenhum outro online empata com o 1º: diferença significativa em pelo menos um cenário para cada um"
    m = rank.set_index("detector")["mttd_media_das_medias"].reindex(tied)
    chosen = m[np.isfinite(m)].idxmin() if np.isfinite(m).any() else first
    return chosen, (f"grupo de empate com o 1º (sem diferença significativa em nenhum cenário): {', '.join(tied)} "
                    f"→ menor MTTD online: {chosen} ({fmt(m[chosen], 1)} s)")


def phase1(det_path, k6_path, out):
    det = pd.read_csv(det_path)
    det["mttd_seconds"] = pd.to_numeric(det["mttd_seconds"].replace({"inf": np.inf}), errors="coerce")
    det["_rep"] = det["run"].str.extract(r"(\d+)")[0].astype(int)
    order = DET_ORDER
    present = set(det.detector)
    dets = [d for b in order for d in (b, f"{b}_online") if d in present]
    dets += sorted(present - set(dets))
    det["detector"] = pd.Categorical(det["detector"], dets, ordered=True)
    det["scenario"] = pd.Categorical(det["scenario"], [s for s in SCEN_ORDER if s in set(det.scenario)], ordered=True)
    det = det.sort_values(["scenario", "detector", "_rep"])
    det["detector"] = det["detector"].astype(str); det["scenario"] = det["scenario"].astype(str)

    os.makedirs(out, exist_ok=True)
    metrics = ["f1", "precision", "recall", "mttd_seconds"] + [m for m in ("f1_tol",) if m in det]
    T_det = table(det, ["scenario", "detector"], metrics)
    # só as comparações planejadas (decisão 2), com o teste pareado (decisão 1)
    off_on, vs, winner, rank = planned_pairs(det)
    fams = [("offline × online", off_on), (f"vencedor da regra do B × outros online", vs)]
    T_t = pd.concat([pairwise(det, "scenario", "detector", m, pairs=pp, paired_on="_rep").assign(familia=fam)
                     for fam, pp in fams if pp for m in ["f1", "precision", "recall"]] or
                    [pairwise(det.iloc[:0], "scenario", "detector", "f1").assign(familia=[])], ignore_index=True)
    sheets = {"0_validacao_slide55": slide55(), "1_IC_detectores": T_det, "2_teste_t": T_t,
              "5_regra_B_ranking": rank}

    nmax = int(det.groupby(["scenario", "detector"]).size().min())
    if nmax > 3:   # [AR 57]: mesma análise só com as 3 primeiras repetições
        T3 = table(det[det._rep <= 3], ["scenario", "detector"], ["f1"])
        sheets["3_IC_F1_N3"] = T3
    fig_ic(T_det, "detector", "f1", dets, os.path.join(out, "fig_ic_f1.png"), "F1 (média ± H, IC95%)")
    fig_box(det, "detector", "f1", dets, os.path.join(out, "fig_box_f1.png"), "F1 por execução")
    fig_ic(T_det, "detector", "mttd_seconds", dets, os.path.join(out, "fig_ic_mttd.png"), "MTTD (s, média ± H)")

    md = ["# Fase 1 — IC da média (TLC) e t de Student", "",
          f"Entrada: `{det_path}` · {len(det)} avaliações · N por célula: {nmax} · α = {ALPHA}", "",
          ("Avaliação até o fim do k6 + margem (decisão 17): último offset avaliado "
           + ", ".join(f"{sc} {fmt(v, 0)} s" for sc, v in det.groupby("scenario")["eval_end_s"].max().items())
           + ". Pontos depois disso não foram medidos e ficam fora." if "eval_end_s" in det and det["eval_end_s"].notna().any()
           else "Avaliação da série inteira, sem corte no fim do k6 (números \"como rodou\"; decisão 17)."), "",
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
    if "f1_tol" in det:   # decisão 6: secundária, offline e online
        tol = det["eval_tol_s"].iloc[0] if "eval_tol_s" in det else float("nan")
        md += ["", f"## F1 com tolerância de atraso de {fmt(tol, 0)} s (secundário; decisão 6)", "",
               "Pontos normais até a tolerância depois do fim de cada pico não contam: o alerta que ainda carrega o "
               "pico (sinais com janela de 30 s + pipeline online) não vira falso positivo. Offline e online, para a "
               "comparação ser justa. **O F1 principal é o da seção acima, sem tolerância.**", ""]
        md += md_ic_table(T_det, "detector", "f1_tol")

    def pair_table(fam):
        sub = T_t[(T_t.metrica == "f1") & (T_t.familia == fam)]
        lines = ["| cenário | par | N | dif (A − B) | IC95% da diferença | t | gl | p | conclusão |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for r in sub.itertuples():
            lines.append(f"| {r.scenario} | {r.A} × {r.B} | {r.n} | {fmt(r.dif)} | {fmt(r.IC_dif_inf)} – {fmt(r.IC_dif_sup)} | "
                         f"{fmt(r.t,2)} | {r.gl} | {fmt(r.p,4)} | {r.conclusao} |")
        return lines, sub

    md += ["", "## Comparações planejadas (F1; decisões 1 e 2)", "",
           "Só estas comparações, definidas antes dos dados e iguais em todos os cenários. Teste **pareado**: "
           "d = F1(A) − F1(B) em cada execução, IC 95% de d̄ = d̄ ± t·S_d/√N (gl = N − 1); diferença significativa "
           "se o IC não contém o 0. Precisão e recall dos mesmos pares: aba `2_teste_t` do `estatistica.xlsx`.", "",
           "### Offline × online do mesmo detector", ""]
    lines, sub = pair_table("offline × online"); md += lines
    if winner:
        md += ["", "### Regra de escolha do detector do B", "",
               "Maior **média das 3 médias** do F1 online (cada cenário pesa igual); o 1º é o MESMO nos 3 cenários.", "",
               "| posição | detector | " + " | ".join(f"F1 {c[3:]}" for c in rank.columns if c.startswith("f1_") and c != "f1_media_das_medias")
               + " | média das médias (F1) | média das médias (MTTD, s) | janelas detectadas |",
               "|---" * (5 + sum(1 for c in rank.columns if c.startswith("f1_") and c != "f1_media_das_medias")) + "|"]
        for k, r in enumerate(rank.itertuples(), 1):
            cells = " | ".join(fmt(getattr(r, c)) for c in rank.columns if c.startswith("f1_") and c != "f1_media_das_medias")
            jan = (f"{int(r.janelas_detectadas)}/{int(r.janelas_total)}" if hasattr(r, "janelas_total") else "—")
            md.append(f"| {k} | {r.detector} | {cells} | {fmt(r.f1_media_das_medias)} | {fmt(r.mttd_media_das_medias, 1)} | {jan} |")
    if winner:
        lines, sub = pair_table(f"vencedor da regra do B × outros online")
        md += ["", f"### {winner} (1º pela regra do B) × outros online", ""] + lines
        chosen, why = rule_b_choice(rank, sub)
        md += ["", f"**Escolha pela regra do B: {chosen}** ({why}). Requisito do ciclo (p95 < 2,5 s): verificado pelo "
                   "ciclo do pod com os 6 detectores juntos (`make detector-ciclo`; piloto 4: 0,48 s). "
                   "Fixar em `HPA_B_DETECTOR` antes da Fase 3."]
    else:
        md += ["", "Sem alertas online nos dados (colunas `online_*`): sem regra do B nem comparações entre online."]
    if T_t.empty:
        md += ["", "Sem teste t: é preciso N ≥ 2 execuções por detector e cenário."]
    md += ["", "Não há outras comparações (decisão 2). ANOVA antes dos pares (slide 65): pendente de decisão com o orientador."]
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
