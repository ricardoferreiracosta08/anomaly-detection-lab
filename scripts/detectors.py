"""
detectors.py — Implementação dos 5 detectores + avaliação fatorial
PPGCC/UFMA — Ricardo F. Costa — 2026

Detectores (todos não supervisionados; o label só é usado para avaliar):
  1. EWMA   (α=0.3, k=3)            — controle estatístico, UNIVARIADO (latência p95)
  2. IF     (contamination=0.1)     — isolamento, multivariado (4 features)
  3. LOF    (n_neighbors=20)        — densidade local, multivariado
  4. DBSCAN (min_samples=2·dim, eps=P90 da k-distância) — densidade global, multivariado
  5. AE     (MLP 4-3-2-3-4, limiar μ+2σ do erro)        — reconstrução, multivariado

Avaliação online (opcional): se o CSV tiver colunas online_<DET> (alertas
exportados do online_detector via Prometheus), elas são avaliadas como <DET>_online.

Uso:
  python scripts/detectors.py --input datasets/burst_run1.csv --output results/
  python scripts/detectors.py --input datasets/ --output results/  # processa todos CSVs

Métricas de saída:
  - Precision, Recall, F1-score
  - MTTD (Mean Time To Detect)
  - Confusion matrix
"""

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

# ── Tentar importar sklearn; informar se ausente ────────────────────────────
try:
    from sklearn.cluster import DBSCAN
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
except ImportError:
    print("ERRO: scikit-learn não instalado. Execute:")
    print("  pip install scikit-learn numpy")
    sys.exit(1)


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class DetectionResult:
    detector: str
    scenario: str
    run: str
    precision: float
    recall: float
    f1: float
    mttd_seconds: float
    tp: int
    fp: int
    fn: int
    tn: int
    total_points: int
    anomaly_ratio: float


# =============================================================================
# Detector 1: EWMA
# =============================================================================

def detect_ewma(
    values: np.ndarray,
    alpha: float = 0.3,
    k: float = 3.0,
    warmup: int = 30,
) -> np.ndarray:
    """
    EWMA (Exponentially Weighted Moving Average) detector.

    Args:
        values: série temporal univariada (latência p95)
        alpha: fator de suavização
        k: fator de sensibilidade (limites k-sigma)
        warmup: pontos iniciais para estimar μ e σ (30 = 150s @ 5s interval)

    Returns:
        array binário (0=normal, 1=anomalia)
    """
    n = len(values)
    predictions = np.zeros(n, dtype=int)

    # Limpar NaN/inf
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)

    if n < warmup:
        return predictions

    # Filtrar zeros do warmup (sem requisições = sem latência)
    warmup_vals = values[:warmup]
    warmup_nonzero = warmup_vals[warmup_vals > 0]

    if len(warmup_nonzero) < 5:
        # Poucos dados no warmup, usar todos os dados não-zero como referência
        all_nonzero = values[values > 0]
        if len(all_nonzero) < 5:
            return predictions
        mu = np.median(all_nonzero)
        sigma = np.std(all_nonzero)
    else:
        mu = np.mean(warmup_nonzero)
        sigma = np.std(warmup_nonzero)

    if sigma < 1e-9:
        sigma = mu * 0.1 if mu > 0 else 1e-6

    ucl = mu + k * sigma
    lcl = mu - k * sigma

    # EWMA
    z = mu
    for t in range(n):
        if values[t] > 0:  # Ignorar pontos sem dados
            z = alpha * values[t] + (1 - alpha) * z
        if z > ucl or (z < lcl and z > 0):
            predictions[t] = 1

    return predictions


# =============================================================================
# Detector 2: Isolation Forest
# =============================================================================

def detect_isolation_forest(
    features: np.ndarray,
    contamination: float = 0.1,
    n_estimators: int = 100,
    random_state: int = 42,
) -> np.ndarray:
    """
    Isolation Forest detector.

    Constrói floresta de árvores de isolamento; anomalias = caminhos curtos.

    Args:
        features: matrix (n_samples, n_features) — CPU, latência, memória, etc.
        contamination: proporção esperada de anomalias
        n_estimators: número de árvores
        random_state: semente para reprodutibilidade

    Returns:
        array binário (0=normal, 1=anomalia)
    """
    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    model = IsolationForest(
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=random_state,
        n_jobs=-1,
    )
    raw_pred = model.fit_predict(X)  # -1 = anomaly, 1 = normal

    # Converter: -1 → 1 (anomalia), 1 → 0 (normal)
    return (raw_pred == -1).astype(int)


# =============================================================================
# Detector 3: Local Outlier Factor
# =============================================================================

def detect_lof(
    features: np.ndarray,
    n_neighbors: int = 20,
    contamination: float = 0.1,
) -> np.ndarray:
    """
    Local Outlier Factor detector.

    Compara densidade local de cada ponto com vizinhos; pontos em regiões
    de densidade muito menor que vizinhança são anômalos.

    Args:
        features: matrix (n_samples, n_features)
        n_neighbors: número de vizinhos para calcular densidade local
        contamination: proporção esperada de anomalias

    Returns:
        array binário (0=normal, 1=anomalia)
    """
    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    model = LocalOutlierFactor(
        n_neighbors=min(n_neighbors, len(X) - 1),
        contamination=contamination,
        novelty=False,
        n_jobs=-1,
    )
    raw_pred = model.fit_predict(X)  # -1 = anomaly, 1 = normal

    return (raw_pred == -1).astype(int)


# =============================================================================
# Detector 4: DBSCAN
# =============================================================================

def dbscan_eps(X: np.ndarray, min_samples: int, eps_percentile: float = 90.0) -> float:
    """eps pelo gráfico de k-distância (Schubert et al., 2017): percentil da
    distância de cada ponto ao seu k-ésimo vizinho, com k = min_samples."""
    k = min(min_samples, len(X) - 1)
    dist = NearestNeighbors(n_neighbors=k).fit(X).kneighbors(X)[0][:, -1]
    eps = float(np.percentile(dist, eps_percentile))
    return eps if eps > 0 else 1e-6


def detect_dbscan(
    features: np.ndarray,
    min_samples: Optional[int] = None,
    eps_percentile: float = 90.0,
) -> np.ndarray:
    """
    DBSCAN (Ester et al., 1996) — agrupamento por densidade.

    Pontos que não pertencem a nenhum cluster (rótulo -1, "ruído") = anomalia.
    Não usa contamination: marca quantos pontos isolados existirem.

    Args:
        features: matrix (n_samples, n_features)
        min_samples: vizinhos mínimos para ponto-núcleo (padrão: 2 × nº de features)
        eps_percentile: percentil da k-distância usado como raio eps

    Returns:
        array binário (0=normal, 1=anomalia)
    """
    X = StandardScaler().fit_transform(features)
    ms = min_samples or 2 * X.shape[1]
    eps = dbscan_eps(X, ms, eps_percentile)
    labels = DBSCAN(eps=eps, min_samples=ms).fit_predict(X)
    return (labels == -1).astype(int)


# =============================================================================
# Detector 5: Autoencoder
# =============================================================================

def detect_autoencoder(
    features: np.ndarray,
    hidden: tuple = (3, 2, 3),
    k: float = 2.0,
    random_state: int = 42,
) -> np.ndarray:
    """
    Autoencoder (Sakurada & Yairi, 2014) — reconstrução neural.

    MLP 4-3-2-3-4 (tanh) treinada para reproduzir a própria entrada; o erro de
    reconstrução (MSE por ponto) é o score. Limiar dinâmico: erro > μ + k·σ dos
    erros da série (sem contamination fixo).

    Returns:
        array binário (0=normal, 1=anomalia)
    """
    X = StandardScaler().fit_transform(features)
    ae = MLPRegressor(
        hidden_layer_sizes=hidden, activation="tanh", solver="adam",
        learning_rate_init=0.01, max_iter=3000, random_state=random_state,
    )
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ae.fit(X, X)
    err = ((ae.predict(X) - X) ** 2).mean(axis=1)
    return (err > err.mean() + k * err.std()).astype(int)


# =============================================================================
# Registro dos detectores (ordem fixa = ordem das tabelas/figuras)
# =============================================================================

DETECTORS = {
    "EWMA":   ("EWMA (α=0.3, k=3)",                 lambda d: detect_ewma(d["latency"], alpha=0.3, k=3.0)),
    "IF":     ("Isolation Forest (contam=0.1)",     lambda d: detect_isolation_forest(d["features"], contamination=0.1)),
    "LOF":    ("LOF (n_neighbors=20, contam=0.1)",  lambda d: detect_lof(d["features"], n_neighbors=20, contamination=0.1)),
    "DBSCAN": ("DBSCAN (min_samples=8, eps=P90)",   lambda d: detect_dbscan(d["features"])),
    "AE":     ("Autoencoder (4-3-2-3-4, μ+2σ)",     lambda d: detect_autoencoder(d["features"])),
}


# =============================================================================
# Evaluation metrics
# =============================================================================

def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, timestamps: np.ndarray) -> dict:
    """Calcula Precision, Recall, F1, MTTD e confusion matrix."""
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # MTTD: para cada janela anômala contígua no ground truth,
    # encontrar o primeiro alerta verdadeiro
    mttd = compute_mttd(y_true, y_pred, timestamps)

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mttd_seconds": round(mttd, 2),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def compute_mttd(y_true: np.ndarray, y_pred: np.ndarray, timestamps: np.ndarray) -> float:
    """
    Mean Time To Detect.
    Para cada janela anômala contígua no ground truth:
      1. Marca t_início = primeiro timestamp com label=1
      2. Encontra primeiro alerta verdadeiro (pred=1 AND true=1) após t_início
      3. delay = t_alerta - t_início
    MTTD = média dos delays.
    """
    delays = []
    in_anomaly = False
    anomaly_start = None

    for i in range(len(y_true)):
        if y_true[i] == 1 and not in_anomaly:
            # Início de nova janela anômala
            in_anomaly = True
            anomaly_start = timestamps[i]
        elif y_true[i] == 0 and in_anomaly:
            # Fim da janela anômala
            in_anomaly = False
            anomaly_start = None

        # Primeiro alerta verdadeiro dentro da janela
        if in_anomaly and y_pred[i] == 1 and anomaly_start is not None:
            delay = timestamps[i] - anomaly_start
            delays.append(delay)
            anomaly_start = None  # Já detectou esta janela

    if not delays:
        return float("inf")

    return float(np.mean(delays))


# =============================================================================
# Pipeline principal
# =============================================================================

FEATURE_COLS = ["latency_p95", "cpu_percent", "memory_mb", "request_rate"]


def impute(col: np.ndarray, how: str) -> np.ndarray:
    """Lacunas do Prometheus (NaN): 'ffill' repete o último valor observado
    (padrão em séries de monitoramento); 'zero' reproduz o tratamento antigo."""
    col = col.astype(float)
    if how == "zero":
        return np.nan_to_num(col, nan=0.0, posinf=0.0, neginf=0.0)
    out = col.copy()
    last = np.nan
    for i, v in enumerate(out):
        if np.isfinite(v):
            last = v
        elif np.isfinite(last):
            out[i] = last
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)  # NaN no início → 0


def load_csv(path: str, how: str = "zero") -> dict:
    """Carrega CSV exportado pelo export_metrics.py."""
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        raise ValueError(f"CSV vazio: {path}")

    timestamps = np.array([float(r["timestamp"]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    raw = np.array([[num(r.get(col)) for col in FEATURE_COLS] for r in rows])
    n_missing = int(np.isnan(raw).sum())
    features = np.column_stack([impute(raw[:, j], how) for j in range(raw.shape[1])])

    # Alertas do detector online, se exportados (colunas online_<DET>)
    online = {}
    for col in rows[0].keys():
        if col.startswith("online_"):
            vals = np.array([num(r.get(col)) for r in rows])
            online[col[len("online_"):] + "_online"] = (np.nan_to_num(vals, nan=0.0) > 0.5).astype(int)

    return {
        "timestamps": timestamps,
        "labels": labels,
        "features": features,
        "latency": features[:, 0],   # métrica univariada do EWMA
        "n_points": len(rows),
        "n_missing": n_missing,
        "online": online,
    }


def run_detectors(csv_path: str, selected: list, how: str = "zero") -> list[DetectionResult]:
    """Executa os detectores selecionados sobre um CSV e retorna resultados."""
    fname = Path(csv_path).stem
    # Inferir cenário e run do nome: burst_run1, rampup_run2, shift_run3
    parts = fname.split("_")
    scenario = parts[0] if parts else "unknown"
    run = parts[1] if len(parts) > 1 else "run1"

    print(f"\n{'='*60}")
    print(f"  Processando: {fname}")
    print(f"  Cenário: {scenario} | Run: {run}")
    print(f"{'='*60}")

    data = load_csv(csv_path, how)
    n = data["n_points"]
    n_anom = int(np.sum(data["labels"]))
    print(f"  Pontos: {n} | Anômalos: {n_anom} ({100*n_anom/n:.1f}%) | "
          f"valores ausentes imputados ({how}): {data['n_missing']}")

    results = []
    jobs = [(name, DETECTORS[name][0], DETECTORS[name][1]) for name in selected]
    jobs += [(name, f"{name} (alertas do detector online)", (lambda d, k=name: d["online"][k]))
             for name in sorted(data["online"])]

    for i, (name, desc, fn) in enumerate(jobs, 1):
        print(f"  [{i}/{len(jobs)}] {desc}...")
        pred = fn(data)
        m = compute_metrics(data["labels"], pred, data["timestamps"])
        print(f"    F1={m['f1']:.3f} | Prec={m['precision']:.3f} | Rec={m['recall']:.3f} | MTTD={m['mttd_seconds']:.1f}s")
        results.append(DetectionResult(
            detector=name, scenario=scenario, run=run,
            total_points=n, anomaly_ratio=round(n_anom / n, 3), **m
        ))

    return results


def compute_factorial_effects(results: list[DetectionResult]) -> dict:
    """
    Calcula efeitos fatoriais para cada métrica.
    Fator A: padrão de carga (3 níveis: burst, rampup, shift)
    Fator B: detector (EWMA, IF, LOF, DBSCAN, AE [+ *_online])

    Retorna médias por fator e diferenças.
    """
    # Agrupar por (scenario, detector)
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in results:
        grouped[(r.scenario, r.detector)].append(r)

    # Médias por cenário
    by_scenario = defaultdict(lambda: {"f1": [], "mttd": [], "precision": [], "recall": []})
    by_detector = defaultdict(lambda: {"f1": [], "mttd": [], "precision": [], "recall": []})

    for r in results:
        for metric in ["f1", "mttd_seconds", "precision", "recall"]:
            key = "mttd" if metric == "mttd_seconds" else metric
            val = getattr(r, metric)
            if val != float("inf"):
                by_scenario[r.scenario][key].append(val)
                by_detector[r.detector][key].append(val)

    effects = {"by_scenario": {}, "by_detector": {}}

    for scenario, metrics in by_scenario.items():
        effects["by_scenario"][scenario] = {
            k: round(float(np.mean(v)), 4) if v else None
            for k, v in metrics.items()
        }

    for detector, metrics in by_detector.items():
        effects["by_detector"][detector] = {
            k: round(float(np.mean(v)), 4) if v else None
            for k, v in metrics.items()
        }

    return effects


def save_results(results: list[DetectionResult], output_dir: str):
    """Salva resultados em CSV e JSON."""
    os.makedirs(output_dir, exist_ok=True)

    # CSV detalhado
    csv_path = os.path.join(output_dir, "detection_results.csv")
    fieldnames = list(asdict(results[0]).keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    print(f"\n✓ Resultados salvos: {csv_path}")

    # Efeitos fatoriais
    effects = compute_factorial_effects(results)
    effects_path = os.path.join(output_dir, "factorial_effects.json")
    with open(effects_path, "w") as f:
        json.dump(effects, f, indent=2, default=str)
    print(f"✓ Efeitos fatoriais: {effects_path}")

    # Tabela resumo no terminal
    print(f"\n{'='*70}")
    print(f"  RESUMO: Média por Detector")
    print(f"{'='*70}")
    print(f"  {'Detector':<10} {'F1':>8} {'Prec':>8} {'Recall':>8} {'MTTD(s)':>8}")
    print(f"  {'-'*42}")
    for det, m in effects["by_detector"].items():
        mttd = m['mttd'] if m['mttd'] is not None else float('inf')
        print(f"  {det:<10} {m['f1']:>8.3f} {m['precision']:>8.3f} {m['recall']:>8.3f} {mttd:>8.1f}")

    print(f"\n  RESUMO: Média por Cenário")
    print(f"  {'-'*42}")
    print(f"  {'Cenário':<10} {'F1':>8} {'Prec':>8} {'Recall':>8} {'MTTD(s)':>8}")
    print(f"  {'-'*42}")
    for sc, m in effects["by_scenario"].items():
        mttd = m['mttd'] if m['mttd'] is not None else float('inf')
        print(f"  {sc:<10} {m['f1']:>8.3f} {m['precision']:>8.3f} {m['recall']:>8.3f} {mttd:>8.1f}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executa os detectores + avaliação fatorial")
    parser.add_argument("--input", required=True, help="CSV ou diretório com CSVs")
    parser.add_argument("--output", default="results/", help="Diretório de saída")
    parser.add_argument("--detectors", default=",".join(DETECTORS),
                        help=f"Lista separada por vírgula (padrão: {','.join(DETECTORS)})")
    parser.add_argument("--impute", choices=["ffill", "zero"], default="zero",
                        help="Lacunas do Prometheus: zero (padrão, igual à qualificação) ou ffill")
    args = parser.parse_args()
    selected = [d.strip().upper() for d in args.detectors.split(",") if d.strip()]
    unknown = [d for d in selected if d not in DETECTORS]
    if unknown:
        print(f"ERRO: detector(es) desconhecido(s): {unknown}. Opções: {list(DETECTORS)}")
        sys.exit(1)

    input_path = Path(args.input)
    all_results = []

    if input_path.is_file():
        all_results.extend(run_detectors(str(input_path), selected, args.impute))
    elif input_path.is_dir():
        csvs = sorted(input_path.glob("*.csv"))
        if not csvs:
            print(f"ERRO: Nenhum CSV encontrado em {input_path}")
            sys.exit(1)
        print(f"Encontrados {len(csvs)} CSVs para processar")
        for csv_file in csvs:
            all_results.extend(run_detectors(str(csv_file), selected, args.impute))
    else:
        print(f"ERRO: {input_path} não existe")
        sys.exit(1)

    save_results(all_results, args.output)
