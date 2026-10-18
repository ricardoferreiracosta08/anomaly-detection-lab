"""
online_detector.py — Detector de anomalias ONLINE (Fase 2)
PPGCC/UFMA — Ricardo F. Costa — 2026

A cada STEP segundos:
  1. consulta no Prometheus as mesmas 4 features do detectors.py (prom_queries.py)
  2. guarda o ponto numa janela deslizante
  3. ajusta cada detector numa JANELA DE REFERÊNCIA (os WINDOW pontos que terminam
     GAP pontos antes do instante atual) e pontua o ponto atual
  4. publica no /metrics (scrapeado pelo próprio Prometheus):

     anomaly_score{detector}  razão score/limiar: 0 = típico, >1 = acima do limiar
     anomaly_alert{detector}  1 se anomaly_score > 1
     anomaly_level{detector}  média dos alertas nos últimos LEVEL_POINTS pontos (0..1)
                              → métrica externa do HPA (via Prometheus Adapter)

Por que janela de referência com GAP: o ponto atual e os imediatamente anteriores
não entram no ajuste, para o detector não "aprender" a anomalia que está começando.
Limitação conhecida: uma anomalia que dura mais que GAP + WINDOW pontos passa a fazer
parte da referência e deixa de ser alarmada (o detector se adapta ao novo regime).

Limiar dinâmico (sem contamination fixo): para IF, LOF e AE o ponto atual é anômalo
se score > média + K·DP dos scores da própria janela de referência.
Piso relativo do DP (DETECTOR_SIGMA_FLOOR): σ_ef = máx(σ, piso·|μ|). Com a referência
quase constante (cluster ocioso, σ ≈ 0), sem piso qualquer variação mínima vira uma
razão enorme (piloto 2: ~10⁵). Piso 0 = desligado.
Piso relativo nas ENTRADAS (DETECTOR_FEATURE_FLOOR): cada feature é padronizada pela
referência com σ_entrada = máx(σ, piso·|μ|). A memória fica quase constante (σ ≈ 0,005 MB);
sem piso, um salto de 0,25 MB (coleta de lixo) virava ~50σ e os multivariados alarmavam
(piloto 3, 140–145 s). Vale para IF, LOF, DBSCAN, AE e LSTM (o EWMA usa a latência bruta).
EWMA: |z − μ| > L·σ (μ, σ da referência). DBSCAN: distância ao núcleo mais próximo > eps.
LSTM (lstm_model.py): treinada na referência para prever o próximo ponto; nota = erro
da previsão do ponto atual a partir dos LSTM_SEQ_LEN pontos anteriores a ele; decisão
pelo mesmo μ + K·σ_ef (com piso) do IF, LOF e AE. Retreina a cada LSTM_RETRAIN passos,
defasada meio período do AE (os dois treinos nunca no mesmo ciclo).

Modos:
  python online_detector.py                          # serviço (Prometheus → /metrics)
  python online_detector.py --replay datasets/x.csv  # reproduz um CSV, sem cluster
"""

import argparse
import collections
import csv
import logging
import math
import os
import sys
import time
import warnings

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
from sklearn.neural_network import MLPRegressor

from prom_queries import FEATURES, queries

log = logging.getLogger("online_detector")


def env(name, default, cast=str):
    v = os.environ.get(name, "")
    return cast(v) if v != "" else default


CFG = dict(
    prom_url=env("PROMETHEUS_URL", "http://prometheus.anomaly-lab.svc:9090"),
    port=env("DETECTOR_PORT", 9105, int),
    step=env("DETECTOR_STEP_SECONDS", 5.0, float),
    window=env("DETECTOR_WINDOW", 60, int),        # 60 × 5 s = 5 min de referência
    gap=env("DETECTOR_GAP", 6, int),               # 6 × 5 s = 30 s fora da referência
    k_sigma=env("DETECTOR_K_SIGMA", 2.0, float),   # limiar dinâmico μ + K·σ (K=2: proposta da reunião)
    sigma_floor=env("DETECTOR_SIGMA_FLOOR", 0.05, float),  # σ_ef = máx(σ, piso·|μ|); 0 = desligado
    feature_floor=env("DETECTOR_FEATURE_FLOOR", 0.01, float),  # σ_entrada = máx(σ, piso·|μ|); 0 = desligado
    level_points=env("DETECTOR_LEVEL_POINTS", 3, int),
    ae_retrain=env("DETECTOR_AE_RETRAIN", 12, int),  # retreina o AE a cada 12 passos (1 min)
    lstm_seq_len=env("LSTM_SEQ_LEN", 12, int),       # pontos anteriores usados na previsão (1 min)
    lstm_retrain=env("LSTM_RETRAIN", 12, int),       # retreina a LSTM a cada 12 passos (1 min)
    eval_skip=env("EVAL_SKIP_SECONDS", 60.0, float),  # replay: s iniciais fora da pontuação (acomodação)
    algos=[a.strip().upper() for a in env("DETECTOR_ALGOS", "EWMA,IF,LOF,DBSCAN,AE,LSTM").split(",") if a.strip()],
    target=env("TARGET_APP", "fastapi"),
)


# =============================================================================
# Núcleo (puro, sem I/O): testável com --replay
# =============================================================================

class OnlineDetector:
    """Mantém a janela e calcula, por detector, (score_ratio, alert)."""

    def __init__(self, algos, window=60, gap=6, k_sigma=2.0, level_points=3, ae_retrain=12, sigma_floor=0.0,
                 lstm_seq_len=12, lstm_retrain=12, feature_floor=0.0):
        self.algos = list(algos)
        self.window, self.gap, self.k = window, gap, k_sigma
        self.sigma_floor = sigma_floor
        self.feature_floor = feature_floor
        self.lstm_seq_len, self.lstm_retrain = lstm_seq_len, lstm_retrain
        self.lstm_model, self.lstm_age = None, 0
        self.min_ref = max(20, window // 3)
        self.hist = collections.deque(maxlen=window + gap + 1)
        self.last_alerts = {a: collections.deque(maxlen=level_points) for a in self.algos}
        self.ewma_z = None
        self.ae_model, self.ae_age = None, 0
        self.ae_retrain = ae_retrain
        self._last_valid = [0.0] * len(FEATURES)

    # ── utilidades ────────────────────────────────────────────────────────
    def _clean(self, x):
        """Lacuna (NaN) → último valor válido daquela feature."""
        out = []
        for j, v in enumerate(x):
            if v is None or not math.isfinite(v):
                v = self._last_valid[j]
            self._last_valid[j] = v
            out.append(float(v))
        return out

    def _scale(self, ref):
        """μ e σ de cada feature na referência, com σ_entrada = máx(σ, piso·|μ|) (e 1 se ainda ~0)."""
        mu, sd = ref.mean(0), ref.std(0)
        sd = np.maximum(sd, self.feature_floor * np.abs(mu))
        sd[sd < 1e-9] = 1.0
        return mu, sd

    def _zratio(self, ref_scores, cur):
        """(nota − μ) / (K·σ_ef), σ_ef = máx(σ, piso·|μ|). Usado por IF, LOF e AE."""
        mu, sd = float(np.mean(ref_scores)), float(np.std(ref_scores))
        sd = max(sd, self.sigma_floor * abs(mu))
        return (cur - mu) / max(self.k * sd, 1e-9)

    # ── detectores ────────────────────────────────────────────────────────
    def _ewma(self, ref, cur, lam=0.3, L=3.0):
        lat_ref = ref[:, 0][ref[:, 0] > 0]
        if lat_ref.size < 5:
            return 0.0
        mu, sd = float(lat_ref.mean()), max(float(lat_ref.std()), 1e-6)
        if self.ewma_z is None:
            self.ewma_z = mu
        if cur[0] > 0:
            self.ewma_z = lam * cur[0] + (1 - lam) * self.ewma_z
        return abs(self.ewma_z - mu) / (L * sd)

    def _if(self, Xr, xc):
        m = IsolationForest(n_estimators=100, random_state=42).fit(Xr)
        return self._zratio(-m.score_samples(Xr), float(-m.score_samples(xc)[0]))

    def _lof(self, Xr, xc):
        m = LocalOutlierFactor(n_neighbors=min(20, len(Xr) - 1), novelty=True).fit(Xr)
        return self._zratio(-m.negative_outlier_factor_, float(-m.score_samples(xc)[0]))

    def _dbscan(self, Xr, xc):
        ms = 2 * Xr.shape[1]
        kd = NearestNeighbors(n_neighbors=min(ms, len(Xr) - 1)).fit(Xr).kneighbors(Xr)[0][:, -1]
        eps = max(float(np.percentile(kd, 90)), 1e-6)
        core = DBSCAN(eps=eps, min_samples=ms).fit(Xr).core_sample_indices_
        if core.size == 0:
            return 0.0
        d = float(np.min(np.linalg.norm(Xr[core] - xc, axis=1)))
        return d / eps

    def _ae(self, Xr, xc):
        if self.ae_model is None or self.ae_age >= self.ae_retrain:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.ae_model = MLPRegressor(hidden_layer_sizes=(3, 2, 3), activation="tanh",
                                             learning_rate_init=0.01, max_iter=1500,
                                             random_state=42).fit(Xr, Xr)
            self.ae_age = 0
        self.ae_age += 1
        err_r = ((self.ae_model.predict(Xr) - Xr) ** 2).mean(1)
        err_c = float(((self.ae_model.predict(xc) - xc) ** 2).mean())
        return self._zratio(err_r, err_c)

    def _lstm(self, H, mu, sd, n_ref):
        """Prevê o ponto atual a partir dos L anteriores (gap incluído); treino só na referência."""
        from lstm_model import LSTMPredictor, sequences
        L = self.lstm_seq_len
        Z = (H - mu) / sd                       # mesma padronização dos outros (μ, σ da referência)
        ref_z = Z[len(H) - 1 - self.gap - n_ref: len(H) - 1 - self.gap]
        if len(ref_z) < L + 2 or len(Z) < L + 1:
            return 0.0
        if self.lstm_model is None or self.lstm_age >= self.lstm_retrain:
            first = self.lstm_model is None
            self.lstm_model = LSTMPredictor(Z.shape[1], seq_len=L).fit(ref_z)
            # defasado meio período do AE: os dois retreinos nunca caem no mesmo ciclo de 5 s
            self.lstm_age = self.lstm_retrain // 2 if first else 0
        self.lstm_age += 1
        xs, ys = sequences(ref_z, L)
        err_r = self.lstm_model.errors(xs, ys)
        err_c = float(self.lstm_model.errors(Z[-1 - L:-1][None, :, :], Z[-1:])[0])
        return self._zratio(err_r, err_c)

    # ── passo ─────────────────────────────────────────────────────────────
    def step(self, x):
        """Recebe um ponto [lat_p95, cpu, mem, req_rate]; devolve {algo: (ratio, alert, level)}."""
        self.hist.append(self._clean(x))
        H = np.asarray(self.hist, dtype=float)
        ref = H[: max(0, len(H) - 1 - self.gap)][-self.window:]
        cur = H[-1]
        out = {}
        if len(ref) < self.min_ref:
            for a in self.algos:
                self.last_alerts[a].append(0)
                out[a] = (0.0, 0, 0.0)
            return out
        mu, sd = self._scale(ref)
        Xr, xc = (ref - mu) / sd, ((cur - mu) / sd).reshape(1, -1)
        fns = {"EWMA": lambda: self._ewma(ref, cur), "IF": lambda: self._if(Xr, xc),
               "LOF": lambda: self._lof(Xr, xc), "DBSCAN": lambda: self._dbscan(Xr, xc),
               "AE": lambda: self._ae(Xr, xc), "LSTM": lambda: self._lstm(H, mu, sd, len(ref))}
        for a in self.algos:
            try:
                ratio = float(fns[a]())
            except Exception as e:  # um detector falhar não derruba os outros
                log.warning("detector %s falhou: %s", a, e)
                ratio = 0.0
            if not math.isfinite(ratio):
                ratio = 0.0
            alert = int(ratio > 1.0)
            self.last_alerts[a].append(alert)
            out[a] = (ratio, alert, float(np.mean(self.last_alerts[a])))
        return out


# =============================================================================
# Serviço: Prometheus → OnlineDetector → /metrics
# =============================================================================

def serve(cfg):
    import requests
    from prometheus_client import Gauge, Histogram, start_http_server

    labels = ["detector", "target"]
    g_score = Gauge("anomaly_score", "Score/limiar do ponto atual (>1 = acima do limiar)", labels)
    g_alert = Gauge("anomaly_alert", "1 se anomaly_score > 1", labels)
    g_level = Gauge("anomaly_level", "Fração de alertas nos últimos pontos (métrica do HPA)", labels)
    g_feat = Gauge("detector_input", "Feature recebida pelo detector", ["feature"])
    g_ok = Gauge("detector_last_success_timestamp", "Unix time da última coleta com sucesso")
    h_step = Histogram("detector_step_seconds", "Tempo de processamento de um passo",
                       buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5])

    q = queries()
    if "LSTM" in cfg["algos"]:   # carrega o PyTorch já na partida, não no 1º ciclo
        import lstm_model
        lstm_model._t()
    det = OnlineDetector(cfg["algos"], cfg["window"], cfg["gap"], cfg["k_sigma"],
                         cfg["level_points"], cfg["ae_retrain"], cfg["sigma_floor"],
                         cfg["lstm_seq_len"], cfg["lstm_retrain"], cfg["feature_floor"])
    start_http_server(cfg["port"])
    log.info("online_detector em :%s | algos=%s | janela=%s gap=%s K=%s piso_σ=%s piso_entrada=%s | Prometheus=%s",
             cfg["port"], cfg["algos"], cfg["window"], cfg["gap"], cfg["k_sigma"], cfg["sigma_floor"],
             cfg["feature_floor"], cfg["prom_url"])
    sess = requests.Session()

    while True:
        t0 = time.time()
        try:
            x = []
            for f in FEATURES:
                r = sess.get(f"{cfg['prom_url']}/api/v1/query", params={"query": q[f]}, timeout=3)
                r.raise_for_status()
                res = r.json().get("data", {}).get("result", [])
                v = float(res[0]["value"][1]) if res else float("nan")
                x.append(v)
                if math.isfinite(v):
                    g_feat.labels(f).set(v)
            with h_step.time():
                out = det.step(x)
            for a, (ratio, alert, level) in out.items():
                g_score.labels(a, cfg["target"]).set(round(ratio, 4))
                g_alert.labels(a, cfg["target"]).set(alert)
                g_level.labels(a, cfg["target"]).set(level)
            g_ok.set(time.time())
        except Exception as e:  # Prometheus fora: mantém último valor e tenta de novo
            log.warning("passo falhou: %s", e)
        time.sleep(max(0.0, cfg["step"] - (time.time() - t0)))


# =============================================================================
# Replay: CSV do export_metrics.py → alertas por ponto (sem cluster)
# =============================================================================

def replay(cfg, path, out_path=None):
    rows = list(csv.DictReader(open(path)))
    det = OnlineDetector(cfg["algos"], cfg["window"], cfg["gap"], cfg["k_sigma"],
                         cfg["level_points"], cfg["ae_retrain"], cfg["sigma_floor"],
                         cfg["lstm_seq_len"], cfg["lstm_retrain"], cfg["feature_floor"])

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    records, step_s = [], []
    for r in rows:
        t0 = time.perf_counter()
        out = det.step([num(r.get(f)) for f in FEATURES])
        step_s.append(time.perf_counter() - t0)
        rec = {"offset_seconds": r.get("offset_seconds"), "label": r.get("label")}
        for a, (ratio, alert, level) in out.items():
            rec[f"score_{a}"], rec[f"alert_{a}"], rec[f"level_{a}"] = round(ratio, 4), alert, round(level, 3)
        records.append(rec)
    if out_path:
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            w.writeheader()
            w.writerows(records)
    # pontuação com a mesma acomodação inicial da Fase 1 (detectors.py): o detector viu tudo
    off = np.array([num(r["offset_seconds"]) for r in records])
    keep = np.nan_to_num(off, nan=0.0) >= cfg["eval_skip"]
    y = np.array([int(r["label"]) for r in records])[keep]
    print(f"Replay {os.path.basename(path)}: {int(keep.sum())} de {len(records)} pontos avaliados "
          f"(acomodação {cfg['eval_skip']:.0f} s), {int(y.sum())} anômalos "
          f"(piso_σ={cfg['sigma_floor']}, piso_entrada={cfg['feature_floor']})")
    print(f"  {'detector':<8} {'prec':>6} {'recall':>7} {'F1':>6} {'alarmes':>8}")
    for a in cfg["algos"]:
        p = np.array([r[f"alert_{a}"] for r in records])[keep]
        tp, fp, fn = int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum()), int(((p == 0) & (y == 1)).sum())
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        print(f"  {a:<8} {pr:6.3f} {rc:7.3f} {f1:6.3f} {int(p.sum()):8d}")
    st = np.array(step_s)
    print(f"  tempo por ciclo ({len(cfg['algos'])} detectores): média {st.mean():.3f} s · "
          f"p95 {np.percentile(st, 95):.3f} s · máx {st.max():.3f} s (limite: {cfg['step']:.0f} s)")
    return records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Detector online (Prometheus → /metrics)")
    ap.add_argument("--replay", help="CSV do export_metrics.py para reproduzir sem cluster")
    ap.add_argument("--replay-out", help="CSV de saída com score/alerta por ponto")
    args = ap.parse_args()
    if args.replay:
        replay(CFG, args.replay, args.replay_out)
        sys.exit(0)
    serve(CFG)
