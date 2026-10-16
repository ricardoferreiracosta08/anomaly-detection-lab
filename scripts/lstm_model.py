"""
lstm_model.py — LSTM preditiva para detecção de anomalias (6º detector)
PPGCC/UFMA — Ricardo F. Costa — 2026

Ideia (Malhotra et al., "Long Short Term Memory Networks for Anomaly Detection
in Time Series", ESANN 2015; Hundman et al., "Detecting Spacecraft Anomalies
Using LSTMs and Nonparametric Dynamic Thresholding", KDD 2018):
  a rede aprende a PREVER o próximo ponto a partir dos LSTM_SEQ_LEN anteriores.
  Onde o comportamento é o de sempre, a previsão acerta; numa anomalia, erra.
  Nota de anomalia = erro quadrático médio da previsão (média nas 4 features).

Não supervisionada: treina só com as 4 features (o label nunca é usado).
Acrescenta a dimensão TEMPORAL que os outros multivariados (IF, LOF, DBSCAN, AE)
não têm: eles olham cada ponto isolado; a LSTM olha a sequência.

Arquitetura fixa e pequena: 1 camada LSTM (LSTM_HIDDEN = 16) → linear (4 saídas),
Adam (lr = 0,01), LSTM_EPOCHS = 30 épocas em lote único (full batch), MSE.
Reprodutível: torch.manual_seed(42), algoritmos determinísticos, 1 thread de CPU.

Usado por detectors.py (offline) e online_detector.py (online).
"""
import os

import numpy as np


def env_int(name, default):
    v = os.environ.get(name, "")
    return int(v) if v != "" else default


SEQ_LEN = env_int("LSTM_SEQ_LEN", 12)     # 12 × 5 s = 1 min de histórico por previsão
HIDDEN = env_int("LSTM_HIDDEN", 16)
EPOCHS = env_int("LSTM_EPOCHS", 30)
LR = 0.01
SEED = 42

_torch = None


def _t():
    """Importa o torch só quando o LSTM é usado (os outros detectores não pagam o custo)."""
    global _torch
    if _torch is None:
        import torch
        torch.set_num_threads(1)              # limita a CPU (o pod do detector tem 0,5 núcleo)
        torch.use_deterministic_algorithms(True)
        _torch = torch
    return _torch


def sequences(X, seq_len):
    """X (n, d) → entradas (n−L, L, d) e alvos (n−L, d): os L pontos anteriores → o ponto seguinte."""
    n = len(X)
    if n <= seq_len:
        return np.empty((0, seq_len, X.shape[1])), np.empty((0, X.shape[1]))
    idx = np.arange(seq_len)[None, :] + np.arange(n - seq_len)[:, None]
    return X[idx], X[seq_len:]


class LSTMPredictor:
    """LSTM de 1 camada + linear: prevê o ponto t a partir de t−L … t−1."""

    def __init__(self, n_features, seq_len=SEQ_LEN, hidden=HIDDEN, epochs=EPOCHS, seed=SEED):
        torch = _t()
        self.seq_len, self.epochs = seq_len, epochs
        torch.manual_seed(seed)
        self.lstm = torch.nn.LSTM(n_features, hidden, num_layers=1, batch_first=True)
        self.out = torch.nn.Linear(hidden, n_features)
        self.params = list(self.lstm.parameters()) + list(self.out.parameters())

    def _forward(self, xb):
        h, _ = self.lstm(xb)
        return self.out(h[:, -1, :])

    def fit(self, X):
        """Treina em todas as sequências de X (já padronizado). Devolve self."""
        torch = _t()
        xs, ys = sequences(np.asarray(X, dtype=np.float32), self.seq_len)
        if len(xs) == 0:
            return self
        xb, yb = torch.from_numpy(xs.astype(np.float32)), torch.from_numpy(ys.astype(np.float32))
        opt = torch.optim.Adam(self.params, lr=LR)
        for _ in range(self.epochs):
            opt.zero_grad()
            loss = torch.mean((self._forward(xb) - yb) ** 2)
            loss.backward()
            opt.step()
        return self

    def errors(self, seqs, targets):
        """Erro quadrático médio da previsão, um por sequência."""
        torch = _t()
        if len(seqs) == 0:
            return np.empty(0)
        with torch.no_grad():
            p = self._forward(torch.from_numpy(np.asarray(seqs, dtype=np.float32))).numpy()
        return ((p - np.asarray(targets, dtype=np.float32)) ** 2).mean(axis=1).astype(float)
