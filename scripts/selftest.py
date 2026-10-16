"""
selftest.py — Autoteste do código de análise (roda sem cluster)
PPGCC/UFMA — Ricardo F. Costa — 2026

  make selftest      (ou: python selftest.py)

Verifica:
  1. os 5 detectores offline sobre uma série sintética com 3 rajadas
  2. o detector online (janela deslizante) alarma dentro da rajada
  3. o IC reproduz o exemplo do slide 55 da disciplina
  4. as métricas do HPA (tempo de reação, pod·s, scale-ups falsos)
  5. o parser dos summaries do k6
  6. o piso relativo do σ do detector online (DETECTOR_SIGMA_FLOOR)
  7. a contagem de alertas antes da 1ª anomalia (check_inicio.py)
  8. a estatística com N = 1 (pairwise sem teste t)
"""
import json
import logging
import os
import tempfile
import unittest

import numpy as np

logging.disable(logging.WARNING)


def burst_series(n=145, seed=7):
    """Série de 5 s parecida com o cenário burst: 3 rajadas em latência/CPU/req."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 5.0
    lab = np.zeros(n, int)
    for a, b in [(150, 185), (305, 345), (465, 500)]:
        lab[(t >= a) & (t <= b)] = 1
    lat = 0.02 + rng.normal(0, 0.002, n) + lab * 0.6
    cpu = 15 + rng.normal(0, 1.5, n) + lab * 70
    mem = 210 + rng.normal(0, 1, n) + lab * 40
    req = 10 + rng.normal(0, 1, n) + lab * 70
    return t, lab, np.column_stack([lat, cpu, mem, req])


class T(unittest.TestCase):
    def test_offline_detectors(self):
        import detectors as d
        t, lab, X = burst_series()
        data = {"timestamps": t, "labels": lab, "features": X, "latency": X[:, 0]}
        for name, (_, fn) in d.DETECTORS.items():
            pred = fn(data)
            self.assertEqual(pred.shape, lab.shape, name)
            m = d.compute_metrics(lab, pred, t)
            self.assertGreaterEqual(m["f1"], 0.0)
            self.assertLessEqual(m["f1"], 1.0)
        # rajadas evidentes: EWMA pega a maior parte; o AE (limiar μ+2σ ≈ 5% dos
        # pontos) alarma pouco, mas o que alarma deve estar dentro das rajadas
        self.assertGreater(d.compute_metrics(lab, d.DETECTORS["EWMA"][1](data), t)["recall"], 0.5)
        m_ae = d.compute_metrics(lab, d.DETECTORS["AE"][1](data), t)
        self.assertGreater(m_ae["tp"], 0)
        self.assertGreaterEqual(m_ae["precision"], 0.5)

    def test_impute(self):
        import detectors as d
        col = np.array([np.nan, 1.0, np.nan, 3.0])
        self.assertEqual(list(d.impute(col, "ffill")), [0.0, 1.0, 1.0, 3.0])
        self.assertEqual(list(d.impute(col, "zero")), [0.0, 1.0, 0.0, 3.0])

    def test_online_detector(self):
        from online_detector import OnlineDetector
        t, lab, X = burst_series()
        det = OnlineDetector(["EWMA", "IF", "LOF", "DBSCAN", "AE"], window=60, gap=6, k_sigma=2.0)
        alerts = {a: [] for a in det.algos}
        for x in X:
            out = det.step(list(x))
            for a, (ratio, alert, level) in out.items():
                self.assertTrue(np.isfinite(ratio))
                self.assertIn(alert, (0, 1))
                self.assertTrue(0.0 <= level <= 1.0)
                alerts[a].append(alert)
        # 1ª rajada (150–185 s): ao menos um detector deve alarmar dentro dela
        first = (t >= 150) & (t <= 185)
        self.assertTrue(any(np.array(alerts[a])[first].any() for a in det.algos))

    def test_sigma_floor(self):
        # referência constante (cluster ocioso, σ ≈ 0) + ponto 2% acima da média:
        # sem piso a razão explode (alarma); com piso 0,05 fica em 0,2 (não alarma).
        # Uma variação grande (50%) alarma nos dois casos.
        from online_detector import OnlineDetector
        ref = np.full(60, 0.001)
        sem = OnlineDetector(["IF"], k_sigma=2.0, sigma_floor=0.0)
        com = OnlineDetector(["IF"], k_sigma=2.0, sigma_floor=0.05)
        self.assertGreater(sem._zratio(ref, 0.001 * 1.02), 1.0)
        self.assertAlmostEqual(com._zratio(ref, 0.001 * 1.02), 0.2, places=6)
        self.assertGreater(sem._zratio(ref, 0.001 * 1.50), 1.0)
        self.assertGreater(com._zratio(ref, 0.001 * 1.50), 1.0)
        # exemplo da documentação: μ = 0,001, σ = 1e-7, variação de 2% → 100 sem piso, 0,2 com piso
        ref2 = 0.001 + np.tile([-1e-7, 1e-7], 30)
        self.assertAlmostEqual(sem._zratio(ref2, 0.001 * 1.02), 100.0, places=3)
        self.assertAlmostEqual(com._zratio(ref2, 0.001 * 1.02), 0.2, places=6)

    def test_check_inicio(self):
        # alertas online antes da 1ª janela anômala do cenário (lida de ANOMALY_PHASES)
        import pandas as pd
        from check_inicio import count_initial
        from export_metrics import ANOMALY_PHASES
        first = min(a for a, _ in ANOMALY_PHASES["burst"])
        off = np.arange(0, 300, 5.0)
        d = pd.DataFrame({"offset_seconds": off, "online_IF": (off < 60).astype(int), "online_AE": 0})
        r = count_initial(d, "burst")
        self.assertEqual(r["pontos"], int((off < first).sum()))
        self.assertEqual(r["online_IF"], 12)
        self.assertEqual(r["online_AE"], 0)

    def test_ic_slide55(self):
        from stats_tlc import ic
        r = ic([331.993, 447.532, 366.052, 420.858, 403.524, 355.959, 464.856, 492.144, 393.393, 389.200])
        self.assertAlmostEqual(r["media"], 406.551, places=3)
        self.assertAlmostEqual(r["DP"], 50.389, places=3)
        self.assertAlmostEqual(r["t"], 2.262, places=3)
        self.assertAlmostEqual(r["H"], 36.05, places=1)

    def test_pairwise_n1(self):
        # degustação (make experiment-quick): 1 execução por detector → sem teste t,
        # mas a tabela precisa ter a coluna "metrica" (o relatório filtra por ela)
        import pandas as pd
        from stats_tlc import pairwise
        det = pd.DataFrame({"scenario": ["burst"] * 3, "detector": ["EWMA", "IF", "LOF"],
                            "run": ["run1"] * 3, "f1": [0.5, 0.4, 0.3]})
        T = pairwise(det, "scenario", "detector", "f1")
        self.assertTrue(T.empty)
        self.assertIn("metrica", T.columns)
        self.assertTrue(T[T.metrica == "f1"].empty)
        # com N = 2 por detector os pares voltam a aparecer
        det2 = pd.concat([det, det.assign(run="run2", f1=det.f1 + 0.05)], ignore_index=True)
        self.assertEqual(len(pairwise(det2, "scenario", "detector", "f1")), 3)

    def test_hpa_metrics(self):
        from hpa_metrics import reaction_metrics, pod_seconds
        start = 1000.0
        ts = [start + 5 * i for i in range(145)]
        desired = [(t, 4.0 if 170 <= t - start <= 240 else 2.0) for t in ts]
        available = [(t, 4.0 if 185 <= t - start <= 255 else 2.0) for t in ts]
        r = reaction_metrics(desired, available, start, [(150, 185), (305, 345), (465, 500)], grace=60)
        self.assertEqual(r["reaction_time_s"], 20.0)
        self.assertEqual(r["ready_time_s"], 35.0)
        self.assertEqual(r["windows_no_reaction"], 2)
        self.assertEqual(r["scaleups"], 1)
        self.assertEqual(r["false_scaleups"], 0)
        self.assertGreater(pod_seconds(available, start, start + 720), 2 * 700)

    def test_k6_summary(self):
        from k6_summary import parse
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "B_burst_run3.json"
            p.write_text(json.dumps({"metrics": {
                "http_req_duration": {"values": {"avg": 10, "min": 1, "med": 8, "max": 90, "p(90)": 30, "p(95)": 40, "p(99)": 80}},
                "http_reqs": {"values": {"count": 100, "rate": 2.0}},
                "http_req_failed": {"values": {"rate": 0.01}}}}))
            r = parse(p)
            self.assertEqual((r["mode"], r["scenario"], r["run"]), ("B", "burst", "run3"))
            self.assertEqual(r["http_req_duration_p(95)"], 40)


if __name__ == "__main__":
    os.environ.setdefault("MPLBACKEND", "Agg")
    unittest.main(verbosity=2)
