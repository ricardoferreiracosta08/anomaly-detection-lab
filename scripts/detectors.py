"""
detectors.py — Implementação dos 3 detectores + avaliação fatorial
PPGCC/UFMA — Ricardo F. Costa — 2026

Detectores:
  1. EWMA   (α=0.3, k=3) — controle estatístico
  2. IF     (contamination=0.1) — ensemble por isolamento
  3. LOF    (n_neighbors=20) — densidade local

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
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
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

def load_csv(path: str) -> dict:
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

    # Features para IF e LOF (multivariadas)
    feature_cols = ["latency_p95", "cpu_percent", "memory_mb", "request_rate"]
    features = np.array([
        [float(r.get(col, 0) or 0) for col in feature_cols]
        for r in rows
    ])

    # Tratar NaN: substituir por 0 (métricas ausentes = sem atividade)
    features = np.nan_to_num(features, nan=0.0)

    # Métrica univariada para EWMA (latência p95)
    latency = features[:, 0]
    latency = np.nan_to_num(latency, nan=0.0)

    return {
        "timestamps": timestamps,
        "labels": labels,
        "features": features,
        "latency": latency,
        "n_points": len(rows),
    }


def run_detectors(csv_path: str) -> list[DetectionResult]:
    """Executa os 3 detectores sobre um CSV e retorna resultados."""
    fname = Path(csv_path).stem
    # Inferir cenário e run do nome: burst_run1, rampup_run2, shift_run3
    parts = fname.split("_")
    scenario = parts[0] if parts else "unknown"
    run = parts[1] if len(parts) > 1 else "run1"

    print(f"\n{'='*60}")
    print(f"  Processando: {fname}")
    print(f"  Cenário: {scenario} | Run: {run}")
    print(f"{'='*60}")

    data = load_csv(csv_path)
    n = data["n_points"]
    n_anom = int(np.sum(data["labels"]))
    print(f"  Pontos: {n} | Anômalos: {n_anom} ({100*n_anom/n:.1f}%)")

    results = []

    # ── EWMA ──
    print("\n  [1/3] EWMA (α=0.3, k=3)...")
    pred_ewma = detect_ewma(data["latency"], alpha=0.3, k=3.0)
    m = compute_metrics(data["labels"], pred_ewma, data["timestamps"])
    print(f"    F1={m['f1']:.3f} | Prec={m['precision']:.3f} | Rec={m['recall']:.3f} | MTTD={m['mttd_seconds']:.1f}s")
    results.append(DetectionResult(
        detector="EWMA", scenario=scenario, run=run,
        total_points=n, anomaly_ratio=round(n_anom/n, 3), **m
    ))

    # ── Isolation Forest ──
    print("  [2/3] Isolation Forest (contamination=0.1, trees=100)...")
    pred_if = detect_isolation_forest(data["features"], contamination=0.1)
    m = compute_metrics(data["labels"], pred_if, data["timestamps"])
    print(f"    F1={m['f1']:.3f} | Prec={m['precision']:.3f} | Rec={m['recall']:.3f} | MTTD={m['mttd_seconds']:.1f}s")
    results.append(DetectionResult(
        detector="IF", scenario=scenario, run=run,
        total_points=n, anomaly_ratio=round(n_anom/n, 3), **m
    ))

    # ── LOF ──
    print("  [3/3] LOF (n_neighbors=20, contamination=0.1)...")
    pred_lof = detect_lof(data["features"], n_neighbors=20, contamination=0.1)
    m = compute_metrics(data["labels"], pred_lof, data["timestamps"])
    print(f"    F1={m['f1']:.3f} | Prec={m['precision']:.3f} | Rec={m['recall']:.3f} | MTTD={m['mttd_seconds']:.1f}s")
    results.append(DetectionResult(
        detector="LOF", scenario=scenario, run=run,
        total_points=n, anomaly_ratio=round(n_anom/n, 3), **m
    ))

    return results


def compute_factorial_effects(results: list[DetectionResult]) -> dict:
    """
    Calcula efeitos fatoriais para cada métrica.
    Fator A: padrão de carga (3 níveis: burst, rampup, shift)
    Fator B: detector (3 níveis: EWMA, IF, LOF)

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
    parser = argparse.ArgumentParser(description="Executa 3 detectores + avaliação fatorial")
    parser.add_argument("--input", required=True, help="CSV ou diretório com CSVs")
    parser.add_argument("--output", default="results/", help="Diretório de saída")
    args = parser.parse_args()

    input_path = Path(args.input)
    all_results = []

    if input_path.is_file():
        all_results.extend(run_detectors(str(input_path)))
    elif input_path.is_dir():
        csvs = sorted(input_path.glob("*.csv"))
        if not csvs:
            print(f"ERRO: Nenhum CSV encontrado em {input_path}")
            sys.exit(1)
        print(f"Encontrados {len(csvs)} CSVs para processar")
        for csv_file in csvs:
            all_results.extend(run_detectors(str(csv_file)))
    else:
        print(f"ERRO: {input_path} não existe")
        sys.exit(1)

    save_results(all_results, args.output)
