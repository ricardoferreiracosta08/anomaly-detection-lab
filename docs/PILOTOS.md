# Pilotos: execuções de teste e o que motivaram

Registro das execuções de **teste** (antes do experimento definitivo), com a configuração da época, os números e as decisões que geraram.

> **Os dados dos pilotos não entram nos resultados da dissertação.** Servem para validar o pipeline e justificar decisões de método. Antes da Fase 1 definitiva, `datasets/`, `datasets_hpa/` e `results/` são limpos (ver o checklist em [RUNBOOK_VPS_VPN.md](RUNBOOK_VPS_VPN.md)).

## TL;DR

| Piloto | O que rodou | Achado principal | Decisão |
|---|---|---|---|
| 1 | `make experiment-quick` (Fase 1, burst, N = 1) | o online ao vivo perde ~0,2 de F1 para o replay, quase tudo em precisão | investigar atraso e falsos alarmes; tolerância de atraso em aberto |
| 2 | `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B` | o B "ganhou" em latência porque escalou **antes** dos picos por alarmes falsos: +48% de custo, tempo de reação indefinido. Confirmado: 53–87% de alertas nos 150 s iniciais, sem anomalia | aquecimento + piso do σ; métrica "réplicas no início do pico" |

---

## Configuração comum aos pilotos

| Parâmetro | Valor |
|---|---|
| Topologia | tudo na VPS (`ROLE=server`) |
| Detector online | `DETECTOR_WINDOW=60` (5 min), `DETECTOR_GAP=6` (30 s), `DETECTOR_K_SIGMA=2`, `DETECTOR_LEVEL_POINTS=3` |
| HPA | `ANOMALY_TARGET=500m`, `HPA_B_DETECTOR=IF` |
| Entre execuções (pilotos 1 e 2) | `COOLDOWN=120`, **sem aquecimento**, **sem piso do σ** |
| Núcleos (piloto 2) | cluster 0–5, k6 e análise 6–7 |

## Piloto 1 — Fase 1 rápida (16/out/2026, ~00:30)

**Comando:** `make experiment-quick` (1 execução do burst, `burst_run1`). A estatística quebrou com N = 1 (bug corrigido depois: `pairwise` com colunas fixas).

**F1 do mesmo CSV, três formas** (offline e ao vivo vêm do `detection_results.csv`; o replay, de `make online-replay`):

| Detector | Offline | Replay (online sem cluster) | Online ao vivo |
|---|---|---|---|
| EWMA | 0,485 | 0,424 | 0,222 |
| IF | 0,500 | 0,625 | 0,448 |
| LOF | 0,300 | 0,519 | 0,312 |
| DBSCAN | 0,438 | 0,667 | 0,342 |
| AE | 0,077 | 0,597 | 0,341 |

Precisão / recall ao vivo: EWMA 0,25/0,20 · IF 0,36/0,60 · LOF 0,23/0,48 · DBSCAN 0,26/0,52 · AE 0,24/0,60.

**Leitura:**
- O procedimento online **sem** atraso (replay) supera o offline em 4 de 5 detectores. A janela deslizante evita o *masking* e o limiar se adapta (ver [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md), seção 4).
- Ao vivo, o online perde ~0,2 de F1 para o replay, **quase tudo em precisão**. Duas causas candidatas:
  - **atraso** do pipeline (alerta transborda para depois do fim da janela anômala);
  - **falsos alarmes no começo da execução** (referência formada pelo cooldown sem carga).
- N = 1: padrão, não conclusão.

**Próximo passo registrado:** medir o atraso com o deslocamento dos alertas (script em [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md), seção 5).

## Piloto 2 — HPA A × B (16/out/2026, 01:34–~02:20)

**Comando:** `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B`.

| Métrica | O que significa | A (só CPU) | B (CPU + IF) |
|---|---|---|---|
| `reaction_time_s` | início do pico → HPA pede mais pods | 43,3 s | **indefinido** (0 de 3 janelas) |
| `ready_time_s` | início do pico → pod novo pronto | 50,0 s | indefinido |
| `p95_anom_ms` | p95 da latência nos picos | 590 ms | 169 ms |
| `slo_viol_anom_pct` | % req. > 500 ms nos picos | 3,26% | 0,15% |
| `slo_viol_all_pct` | % req. > 500 ms na execução | 2,60% | 0,13% |
| `pod_seconds` | custo (pods × s) | 3.615 | **5.350 (+48%)** |
| `scaleups` / `false_scaleups` | pedidos de pods / fora dos picos | 3 / 0 | 3 / **2** |
| `k6_p95_ms` | p95 visto pelo k6 | 520 ms | 184 ms |
| `k6_error_rate` | erros no k6 | 0,5% | 0,1% |

**Leitura:**
1. No B, o IF alarmou **fora dos picos** (2 scale-ups falsos). Os pods subiram antes de qualquer anomalia e, como a descida é lenta (120 s + 1 pod/min), ficaram.
2. Quando os picos chegaram, já havia pods sobrando: latência baixa, mas com **custo 48% maior**.
3. O tempo de reação ficou **indefinido**, não "rápido": a métrica exige que o HPA peça **mais** pods do que tinha no início do pico, e o B já estava acima. As 3 janelas contaram como "sem reação" e saíram da média em silêncio.
4. É o cenário que o **modo C** existe para separar: ganho por detectar × ganho por ter mais pods ([HPA.md](HPA.md), seção 2).

**Evidência no Grafana** (dashboard "Detector Online & HPA", escala log):
- scores do AE chegando a ~10⁵ (01:39, 01:52, 02:10) nas transições de "cluster parado" para "carga";
- depois do fim das execuções (~02:28 em diante), com o cluster ocioso, o AE fica **em alerta contínuo** e os outros detectores ficam perto do limiar. A referência quase constante (σ ≈ 0) torna qualquer variação um alarme.

**Verificação (feita): alertas antes da primeira anomalia.** Os primeiros 150 s do burst não têm anomalia (a primeira janela do gabarito começa aos 150 s), ou seja, 30 pontos de 5 s em que o `label` é sempre 0. Alertas `online_*` nesse trecho:

| Execução | EWMA | IF | LOF | DBSCAN | AE |
|---|---|---|---|---|---|
| A_burst_run1 | 22/30 | 19/30 | 16/30 | 26/30 | 26/30 |
| B_burst_run1 | 22/30 | 23/30 | 23/30 | 23/30 | 26/30 |

**Confirmado:** os detectores passam de 53% a 87% do trecho inicial em alerta, sem nenhuma anomalia. São todos falsos positivos. Isso explica boa parte da baixa precisão ao vivo (piloto 1) e os scale-ups falsos do B: com o IF em alerta em 23 de 30 pontos, o `anomaly_level` chega a 0,67–1 logo no começo e o HPA escala.

## Decisões motivadas pelos pilotos

| Decisão | Motivo (piloto) | Estado |
|---|---|---|
| Aquecimento com a carga base do cenário antes de cada execução (`WARMUP_SECONDS`) | falsos alarmes com referência formada por silêncio (pilotos 1 e 2) | **implementado** (16/out): 330 s, VUs burst 10 / rampup 10 / shift 30 |
| Piso relativo do σ (`DETECTOR_SIGMA_FLOOR`, opcional) | razões ~10⁵ com σ ≈ 0 (piloto 2, Grafana) | **implementado e decidido** (16/out): **0,05**. Replay da qualificação: F1 igual com 0 e 0,05 ([validação](DETECTOR_ONLINE.md#6-validação-do-piso)); proteção sem custo medido |
| Métrica "réplicas no início de cada pico" no `hpa_metrics.py` | tempo de reação indefinido quando o sistema já está escalado (piloto 2) | proposta |
| Calibrar o modo C para custo semelhante ao B | o ganho do B veio com +48% de custo (piloto 2) | proposta ([HPA.md](HPA.md), seção 2) |
| Tolerância de atraso na avaliação do online | perda de precisão ao vivo × replay (piloto 1) | em aberto (orientador) |

## Próximo piloto (piloto 3)

**O que mudou desde o piloto 2:** aquecimento de 330 s antes de cada execução, sempre com o HPA no modo A (o modo da execução só entra logo antes do roteiro), e piso do σ = 0,05. Antes de rodar: `git pull`, `make build-analysis` e `make detector-deploy` na VPS, para o pod usar o código e a configuração novos.

**Comando:** `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B,C` (≈ 1 h: 3 execuções de ~12 min + 3 aquecimentos de 5,5 min + esperas). Depois: `make check-inicio DIR=datasets_hpa`.

**Critério de sucesso (fixado antes de rodar):**
- **alertas iniciais** (`make check-inicio`, antes da 1ª anomalia): caem de **53–87%** para **perto de zero**. Alguns alertas isolados são esperados com K = 2 (≈ 2,3% dos pontos de uma normal ficam acima de μ + 2σ), e o transiente de 30 s na troca aquecimento → roteiro pode gerar algum;
- **`false_scaleups` do modo B perto de 0** (eram 2).

Também observar, sem critério fixo: o tempo de reação do B passa a ser **definido** (era indefinido); o custo (`pod_seconds`) do B fica próximo do A; o `results/warmup_log.csv` mostra `at_min=1` (HPA no mínimo ao fim do aquecimento) em todas as execuções e `anomaly_level_b` abaixo de 0,5 — se ficar ≥ 0,5, o B escalaria assim que aplicado e o falso alarme só mudou de lugar.

Registrar aqui como Piloto 3, com a tabela do `check-inicio` e a do `hpa_results.csv`.

## Piloto 4 (depois do piloto 3): LSTM, o 6º detector

**O que mudou:** o LSTM entrou como 6º detector, offline e online (pedido do orientador). Antes de rodar, na VPS: `git pull`, `DETECTOR_ALGOS=EWMA,IF,LOF,DBSCAN,AE,LSTM` no `.env`, `make build-analysis` e `make detector-deploy` (a linha de partida do `make detector-logs` deve listar os 6).

**Comandos:**
```bash
make clean                 # depois de registrar o piloto 3
make experiment-quick      # Fase 1 com 1 burst, 6 detectores (offline e online)
make check-inicio          # alertas antes da 1ª anomalia, LSTM incluído
```
No Grafana, painel **"Saúde do detector"**: o p95 do tempo de ciclo durante a execução.

**Critério de sucesso (fixado antes de rodar):**
- **p95 do ciclo bem abaixo de 5 s** (`DETECTOR_STEP_SECONDS`) com os 6 detectores. Se não ficar, aumentar `LSTM_RETRAIN` (retreino menos frequente) e registrar aqui;
- **alertas iniciais do LSTM perto de zero** no `make check-inicio`, como os dos outros (alguns isolados com K = 2 são esperados);
- `LSTM` e `LSTM_online` aparecem no `results/detection_results.csv` e no relatório da estatística.

Registrar aqui como Piloto 4, com o p95 do ciclo, a tabela do `check-inicio` e o F1 dos 6 (N = 1, só padrão).

