"""
selftest.py — Autoteste do código de análise (roda sem cluster)
PPGCC/UFMA — Ricardo F. Costa — 2026

  make selftest      (ou: python selftest.py)

Verifica:
  1. os 6 detectores offline sobre uma série sintética com 3 rajadas
  2. o detector online (janela deslizante) alarma dentro da rajada
  3. o IC reproduz o exemplo do slide 55 da disciplina
  4. as métricas do HPA (tempo de reação, pod·s, scale-ups falsos)
  5. o parser dos summaries do k6
  6. o piso relativo do σ do detector online (DETECTOR_SIGMA_FLOOR)
  7. a contagem de alertas antes da 1ª anomalia (check_inicio.py)
  8. a estatística com N = 1 (pairwise sem teste t)
  9. o LSTM (6º detector): offline acha um pico injetado, online devolve razão
     finita, e duas execuções com a mesma semente dão o mesmo resultado
  10. o piso relativo na padronização das entradas (DETECTOR_FEATURE_FLOOR)
  11. a acomodação inicial da avaliação (EVAL_SKIP_SECONDS): fora da pontuação,
      nenhum pico cortado, e 0 s reproduz a avaliação antiga
  12. o teste pareado da Fase 1 (decisão 1): IC da diferença por execução
  13. a tolerância de atraso após cada pico (EVAL_TOLERANCE_SECONDS, decisão 6)
  14. as comparações planejadas da Fase 1 (decisão 2) e a regra de escolha do B,
      com o grupo de empate e as janelas detectadas ao lado do MTTD
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
        det = OnlineDetector(["EWMA", "IF", "LOF", "DBSCAN", "AE", "LSTM"], window=60, gap=6, k_sigma=2.0)
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

    def test_lstm_offline(self):
        # pico injetado numa série sintética suave: a LSTM offline alarma dentro dele
        import detectors as d
        rng = np.random.default_rng(3)
        n = 145
        t = np.arange(n)
        base = np.column_stack([0.02 + 0.002 * np.sin(t / 6), 15 + 1.5 * np.sin(t / 8),
                                210 + np.sin(t / 10), 10 + np.sin(t / 7)]) + rng.normal(0, 0.05, (n, 4)) * [0.001, 0.3, 0.2, 0.2]
        spike = (t >= 90) & (t <= 95)
        X = base.copy()
        X[spike] += [0.6, 70, 40, 70]
        pred = d.detect_lstm(X)
        self.assertEqual(len(pred), n)
        from lstm_model import SEQ_LEN
        self.assertEqual(int(pred[:SEQ_LEN].sum()), 0)   # sem histórico = normal
        self.assertTrue(pred[spike].any())

    def test_lstm_online(self):
        # o ciclo online com LSTM roda e devolve razão finita
        from online_detector import OnlineDetector
        t, lab, X = burst_series()
        det = OnlineDetector(["LSTM"], window=60, gap=6, k_sigma=2.0, sigma_floor=0.05)
        ratios = [det.step(list(x))["LSTM"][0] for x in X]
        self.assertTrue(all(np.isfinite(ratios)))
        self.assertTrue(any(r != 0.0 for r in ratios))   # passou do aquecimento e decidiu

    def test_lstm_determinism(self):
        # duas execuções com a mesma semente → mesmo resultado (offline e online)
        import detectors as d
        from online_detector import OnlineDetector
        t, lab, X = burst_series()
        self.assertTrue(np.array_equal(d.detect_lstm(X), d.detect_lstm(X)))
        runs = []
        for _ in range(2):
            det = OnlineDetector(["LSTM"], window=60, gap=6, k_sigma=2.0)
            runs.append([det.step(list(x))["LSTM"][0] for x in X[:90]])
        self.assertEqual(runs[0], runs[1])

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

    def test_feature_floor(self):
        # memória quase constante (σ ≈ 0,005 MB) e um salto de 0,25 MB (piloto 3, 140–145 s):
        # sem piso nas entradas vira ~50σ; com piso de 1% vira ~0,3σ
        from online_detector import OnlineDetector
        rng = np.random.default_rng(1)
        ref = np.column_stack([0.005 + rng.normal(0, 0.0002, 60), 2 + rng.normal(0, 0.2, 60),
                               82.69 + rng.normal(0, 0.005, 60), 6.6 + rng.normal(0, 0.1, 60)])
        cur = ref.mean(0) + [0, 0, 0.25, 0]
        mu0, sd0 = OnlineDetector([], feature_floor=0.0)._scale(ref)
        mu, sd = OnlineDetector([], feature_floor=0.01)._scale(ref)
        z_sem = abs((cur[2] - mu0[2]) / sd0[2])
        z_com = abs((cur[2] - mu[2]) / sd[2])
        self.assertGreater(z_sem, 20)
        self.assertLess(z_com, 1)
        self.assertAlmostEqual(sd[0], ref[:, 0].std(), places=9)   # latência: σ real > 1% de μ, não muda

    def test_check_inicio(self):
        # alertas online antes da 1ª janela anômala do cenário (lida de ANOMALY_PHASES)
        import pandas as pd
        from check_inicio import count_initial
        from export_metrics import ANOMALY_PHASES
        first = min(a for a, _ in ANOMALY_PHASES["burst"])
        off = np.arange(0, 300, 5.0)
        d = pd.DataFrame({"offset_seconds": off, "online_IF": (off < 60).astype(int), "online_AE": 0})
        r = count_initial(d, "burst", split=60)
        self.assertEqual(r["pontos"], int((off < first).sum()))
        self.assertEqual(r["online_IF"], 12)
        self.assertEqual(r["online_AE"], 0)
        # duas partes: [0, 60) acomodação e [60, 1ª anomalia)
        self.assertEqual((r["pontos_1"], r["pontos_2"]), (12, int(((off >= 60) & (off < first)).sum())))
        self.assertEqual((r["online_IF_1"], r["online_IF_2"]), (12, 0))

    def test_paired_test(self):
        # decisão 1: IC da média das diferenças por execução (mesma fórmula do IC da média)
        from scipy import stats as st
        from stats_tlc import paired_test, t_test
        base = np.array([0.20, 0.55, 0.35, 0.70, 0.45, 0.30, 0.60, 0.25, 0.50, 0.40])   # execuções "difíceis" e "fáceis"
        a = base + np.array([0.04, 0.06, 0.05, 0.03, 0.05, 0.06, 0.04, 0.05, 0.06, 0.04])
        r = paired_test(a, base)
        d = a - base
        H = st.t.ppf(0.975, 9) * d.std(ddof=1) / np.sqrt(10)
        self.assertAlmostEqual(r["dif"], d.mean(), places=12)
        self.assertAlmostEqual(r["IC_dif_inf"], d.mean() - H, places=12)
        self.assertEqual((r["gl"], r["n"], r["metodo"]), (9, 10, "pareado"))
        self.assertEqual(r["conclusao"], "médias diferentes")             # pareado vê a melhora constante
        self.assertEqual(t_test(a, base)["conclusao"], "sem diferença significativa")  # o não pareado não vê
        self.assertEqual(paired_test(a[:1], base[:1]), {})                 # N < 2: sem teste
        # pairwise alinha pela execução, mesmo com as linhas fora de ordem
        import pandas as pd
        from stats_tlc import pairwise
        df = pd.DataFrame({"scenario": "burst", "detector": ["X"] * 10 + ["Y"] * 10,
                           "_rep": list(range(1, 11)) + list(range(10, 0, -1)),
                           "f1": list(a) + list(base[::-1])})
        rp = pairwise(df, "scenario", "detector", "f1", paired_on="_rep").iloc[0]
        self.assertAlmostEqual(rp["dif"], d.mean(), places=12)

    def test_planned_pairs(self):
        # decisão 2: só offline × online (6) e vencedor da regra do B × outros online (5), por cenário;
        # o vencedor é o MESMO nos 3 cenários (maior média das 3 médias do F1 online)
        import pandas as pd
        from stats_tlc import planned_pairs, phase1
        rng = np.random.default_rng(5)
        f1_on = {"EWMA": [.30, .30, .30], "IF": [.60, .60, .40], "LOF": [.50, .50, .55],   # LOF vence o shift sozinho
                 "DBSCAN": [.40, .40, .40], "AE": [.45, .45, .45], "LSTM": [.35, .35, .35]}
        rows = []
        for k, sc in enumerate(["burst", "rampup", "shift"]):
            for det, v in f1_on.items():
                for rep in range(1, 4):
                    for name, f in ((det, v[k] - 0.1), (det + "_online", v[k])):
                        rows.append(dict(detector=name, scenario=sc, run=f"run{rep}", f1=f + rng.normal(0, .01),
                                         precision=.5, recall=.5, mttd_seconds=10.0, f1_tol=f))
        det = pd.DataFrame(rows)
        off_on, vs, winner, rank = planned_pairs(det)
        self.assertEqual(winner, "IF_online")                                   # (.6+.6+.4)/3 > LOF (.5+.5+.55)/3
        self.assertEqual(len(off_on), 6)
        self.assertEqual(len(vs), 5)
        self.assertTrue(all(a == "IF_online" and b.endswith("_online") for a, b in vs))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "det.csv"); det.to_csv(path, index=False)
            phase1(path, None, tmp)
            T = pd.read_csv(os.path.join(tmp, "2_teste_t.csv"))
            rel = open(os.path.join(tmp, "relatorio.md")).read()
        f1 = T[T.metrica == "f1"]
        self.assertEqual(f1.groupby("scenario").size().tolist(), [11, 11, 11])   # nada além das 11 planejadas
        self.assertEqual(set(f1[f1.familia.str.startswith("vencedor")].A), {"IF_online"})   # mesmo vencedor nos 3
        self.assertIn("Escolha pela regra do B: IF_online", rel)

    def test_rule_b_tie_group(self):
        # grupo de empate = o 1º + todos sem diferença significativa para ele em nenhum cenário;
        # dentro do grupo vence o menor MTTD (aqui o 3º do ranking)
        import pandas as pd
        from stats_tlc import rule_b_choice
        rank = pd.DataFrame({"detector": ["A_online", "B_online", "C_online", "D_online"],
                             "mttd_media_das_medias": [20.0, 15.0, 10.0, 5.0]})
        nd, dif = "sem diferença significativa", "médias diferentes"
        vs = pd.DataFrame({"B": ["B_online"] * 3 + ["C_online"] * 3 + ["D_online"] * 3,
                           "conclusao": [nd, nd, nd] + [nd, nd, nd] + [nd, dif, nd]})   # D difere no 2º cenário
        chosen, why = rule_b_choice(rank, vs)
        self.assertEqual(chosen, "C_online")                       # o 3º entra no grupo e tem o menor MTTD
        self.assertIn("A_online, B_online, C_online", why)         # D fora do grupo, apesar do menor MTTD
        chosen2, _ = rule_b_choice(rank, vs.assign(conclusao=dif))
        self.assertEqual(chosen2, "A_online")                      # ninguém empata → o 1º

    def test_count_windows(self):
        # MTTD só nas janelas detectadas; o nº de detectadas vai ao lado
        import detectors as d
        lab = np.array([0, 1, 1, 0, 0, 1, 1, 0, 1, 0])               # 3 janelas
        pred = np.array([0, 0, 1, 0, 0, 0, 0, 0, 1, 0])              # detecta a 1ª e a 3ª
        self.assertEqual(d.count_windows(lab, pred), (2, 3))
        m = d.compute_metrics(lab, pred, np.arange(10) * 5.0)
        self.assertEqual((m["windows_detected"], m["windows_total"]), (2, 3))
        self.assertEqual(m["mttd_seconds"], 2.5)                     # (5 + 0)/2: a janela perdida fica fora

    def test_eval_tolerance(self):
        # decisão 6: pontos normais até EVAL_TOLERANCE_SECONDS após o fim de cada pico não contam (secundária)
        import detectors as d
        off = np.arange(0, 100, 5.0)
        lab = ((off >= 40) & (off <= 55)).astype(int)                    # 1 pico: 40–55 s
        alert = ((off >= 45) & (off <= 65)).astype(int)                  # chega 5 s atrasado e transborda até 65 s
        keep = d.tolerance_mask(lab, off, 15)
        self.assertEqual(list(off[~keep]), [60.0, 65.0, 70.0])           # (55, 70] fora
        m0 = d.compute_metrics(lab, alert, off)
        mt = d.compute_metrics(lab[keep], alert[keep], off[keep])
        self.assertEqual(m0["fp"], 2)                                    # sem tolerância: 60 e 65 s são FP
        self.assertEqual(mt["fp"], 0)                                    # com tolerância: deixam de ser
        self.assertEqual(mt["tp"], m0["tp"])                             # os acertos não mudam
        self.assertTrue(d.tolerance_mask(lab, off, 0).all())             # 0 = sem tolerância

    def test_eval_skip(self):
        # acomodação inicial: pontos com offset < EVAL_SKIP_SECONDS fora da pontuação;
        # o detector vê tudo; com 0, a avaliação é a de sempre (regressão)
        import csv as _csv
        import detectors as d
        t, lab, X = burst_series()
        alert = lab.copy()
        alert[(t >= 15) & (t < 50)] = 1        # alarmes falsos na troca aquecimento → roteiro
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "burst_run1.csv")
            with open(path, "w", newline="") as f:
                w = _csv.writer(f)
                w.writerow(["timestamp", "offset_seconds", "latency_p95", "cpu_percent", "memory_mb",
                            "request_rate", "label", "online_IF"])
                for i in range(len(t)):
                    w.writerow([1000 + t[i], t[i], *X[i], lab[i], alert[i]])
            # sem o corte do fim (decisão 17, testado em test_eval_end): aqui só a acomodação
            r0 = {r.detector: r for r in d.run_detectors(path, ["EWMA"], eval_skip=0, eval_end_margin=None)}
            r60 = {r.detector: r for r in d.run_detectors(path, ["EWMA"], eval_skip=60, eval_end_margin=None)}
        full = d.compute_metrics(lab, alert, 1000 + t)
        self.assertEqual(r0["IF_online"].f1, full["f1"])            # 0 s = avaliação antiga
        self.assertEqual(r0["IF_online"].fp, int(((t >= 15) & (t < 50)).sum()))
        self.assertEqual(r60["IF_online"].fp, 0)                     # os falsos da troca saem
        self.assertEqual(r60["IF_online"].tp, r0["IF_online"].tp)   # nenhum pico do gabarito cortado
        self.assertEqual(r60["IF_online"].total_points, int((t >= 60).sum()))
        self.assertEqual(r60["EWMA"].eval_skip_s, 60)

    def test_eval_end(self):
        # decisão 17: só entram os pontos até o fim do k6 + margem; depois disso o CSV da
        # Fase 1 só tem o último valor repetido (pontos-fantasma). off = avaliação oficial
        import csv as _csv
        import detectors as d
        from export_metrics import ANOMALY_PHASES, K6_END_SECONDS
        for sc, end in K6_END_SECONDS.items():   # nenhum pico do gabarito passa do fim do k6
            self.assertGreater(end, max(b for _, b in ANOMALY_PHASES[sc]))
        t, lab, X = burst_series()                # 0–720 s, como a janela do burst
        cut = K6_END_SECONDS["burst"] + 15        # 633 s
        alert = lab.copy()
        alert[t > cut] = 1                        # alerta "repetido" depois do fim do k6
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "burst_run1.csv")
            with open(path, "w", newline="") as f:
                w = _csv.writer(f)
                w.writerow(["timestamp", "offset_seconds", "latency_p95", "cpu_percent", "memory_mb",
                            "request_rate", "label", "online_IF"])
                for i in range(len(t)):
                    w.writerow([1000 + t[i], t[i], *X[i], lab[i], alert[i]])
            off = {r.detector: r for r in d.run_detectors(path, ["EWMA"], eval_end_margin=None)}
            r15 = {r.detector: r for r in d.run_detectors(path, ["EWMA"], eval_end_margin=15)}
            data = d.load_csv(path, max_offset=cut)
        self.assertEqual(off["IF_online"].fp, int((t > cut).sum()))   # oficial: fantasmas viram FP
        self.assertEqual(r15["IF_online"].fp, 0)                      # corrigido: fora
        self.assertEqual(r15["IF_online"].tp, off["IF_online"].tp)    # nenhum pico cortado
        self.assertEqual(r15["IF_online"].total_points, int(((t >= 60) & (t <= cut)).sum()))
        self.assertEqual(r15["EWMA"].eval_end_s, cut)
        self.assertTrue(np.isnan(off["EWMA"].eval_end_s))
        self.assertEqual(data["n_points"], int((t <= cut).sum()))     # o detector offline nem vê o resto
        self.assertEqual(data["n_cut_anom"], 0)
        self.assertIsNone(d.parse_end_margin("off"))
        self.assertEqual(d.parse_end_margin("15"), 15.0)

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
        # pronto só nas janelas com reação e depois do pedido: pods de um scale-up anterior
        # (pedido aos 130 s, prontos aos 160 s) não contam; janela 2 já escalada, sem reação
        step = lambda o, *cuts: next((v for lim, v in cuts if o < lim), 2.0)
        d4 = [(t, step(t - start, (130, 2.0), (170, 3.0), (330, 4.0))) for t in ts]
        a4 = [(t, step(t - start, (160, 2.0), (195, 3.0), (340, 4.0))) for t in ts]
        r4 = reaction_metrics(d4, a4, start, [(150, 185), (305, 345)], grace=60)
        self.assertEqual(r4["reaction_time_s"], 20.0)      # janela 1: 3 → 4 aos 170 s
        self.assertEqual(r4["windows_no_reaction"], 1)     # janela 2: desejadas já em 4
        self.assertEqual(r4["ready_time_s"], 45.0)         # 195 s (não os 160 s do pedido anterior)
        self.assertEqual(r["scaleups"], 1)
        self.assertEqual(r["false_scaleups"], 0)
        self.assertGreater(pod_seconds(available, start, start + 720), 2 * 700)
        # decisão 17: scale-up falso só conta até o fim do k6 + grace (burst: 618 + 60 = 678 s)
        d2 = [(t, 3.0 if t - start >= 600 else 2.0) for t in ts]    # sobe aos 600 s: conta
        d3 = [(t, 3.0 if t - start >= 700 else 2.0) for t in ts]    # sobe aos 700 s: sem carga, não conta
        lim = start + 618 + 60
        self.assertEqual(reaction_metrics(d2, available, start, [], grace=60, count_until=lim)["false_scaleups"], 1)
        self.assertEqual(reaction_metrics(d3, available, start, [], grace=60, count_until=lim)["false_scaleups"], 0)
        self.assertEqual(reaction_metrics(d3, available, start, [], grace=60)["false_scaleups"], 1)

    def test_slo_sensitivity(self):
        import hpa_metrics as hm
        # 2 janelas, 100 requisições cada; abaixo de 0,25 s: 60 e 80; abaixo de 1 s: 95 e 100
        ok = {("0.25", 1185.0): 60, ("0.25", 1345.0): 80, ("1.0", 1185.0): 95, ("1.0", 1345.0): 100}
        def fake(q, t):
            if "_count" in q:
                return 100.0
            return float(ok.get((q.split('le="')[1].split('"')[0], t), float("nan")))
        orig = hm.prom_instant
        hm.prom_instant = fake
        try:
            r = hm.slo_sensitivity(1000.0, [(150, 185), (305, 345)])
        finally:
            hm.prom_instant = orig
        self.assertEqual(hm.SENS_FIELDS, ["slo_viol_anom_250ms_pct", "slo_viol_anom_1000ms_pct"])
        self.assertEqual(r["slo_viol_anom_250ms_pct"], 30.0)    # (40 + 20) / 200
        self.assertEqual(r["slo_viol_anom_1000ms_pct"], 2.5)    # (5 + 0) / 200
        self.assertLess(hm.FIELDS.index("slo_viol_anom_pct"), hm.FIELDS.index("slo_viol_anom_250ms_pct"))

    def test_hpa_series(self):
        from hpa_metrics import save_series
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "series" / "B_burst_run1.csv"
            save_series(p, [(1000.0, 2.0), (1005.0, 3.0)], [(1000.0, 2.0)], 1000.0)
            self.assertEqual(p.read_text().splitlines(),
                             ["timestamp,offset_seconds,desired,available", "1000,0,2,2", "1005,5,3,"])

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
