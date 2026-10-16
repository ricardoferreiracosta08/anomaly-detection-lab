# Pilotos: execuções de teste e o que motivaram

Registro das execuções de **teste** (antes do experimento definitivo), com a configuração da época, os números e as decisões que geraram.

> **Os dados dos pilotos não entram nos resultados da dissertação.** Servem para validar o pipeline e justificar decisões de método. Antes da Fase 1 definitiva, `datasets/`, `datasets_hpa/` e `results/` são limpos (ver o checklist em [RUNBOOK_VPS_VPN.md](RUNBOOK_VPS_VPN.md)).

## TL;DR

| Piloto | O que rodou | Achado principal | Decisão |
|---|---|---|---|
| 1 | `make experiment-quick` (Fase 1, burst, N = 1) | o online ao vivo perde ~0,2 de F1 para o replay, quase tudo em precisão | investigar atraso e falsos alarmes; tolerância de atraso em aberto |
| 2 | `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B` | o B "ganhou" em latência porque escalou **antes** dos picos por alarmes falsos: +48% de custo, tempo de reação indefinido. Confirmado: 53–87% de alertas nos 150 s iniciais, sem anomalia | aquecimento + piso do σ; métrica "réplicas no início do pico" |
| 3 | `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B,C`, com aquecimento (modo A) e piso 0,05 | alertas iniciais caíram de 53–87% para 0–30%; B sem scale-up falso, reage 10 s antes do A com +1% de custo. Mas B e C tiveram latência **pior** que A (p95 nos picos 975 e 1.200 ms × 465 ms) | confirmado: transiente da troca (15–45 s), app com 40× mais itens (viés de ordem) e salto da memória virando ~50σ (140–145 s no A). **Decidido:** reiniciar a app, sobrepor as rampas, piso nas entradas |

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
| Reiniciar a app antes de cada execução | estado crescendo: 4.055 e 3.850 itens por pod contra 100 (piloto 3) | **implementado** (16/out) |
| Rampas sobrepostas na troca aquecimento → roteiro | alertas de 15–45 s em AE, DBSCAN e LOF (piloto 3) | **implementado** (16/out) |
| Piso relativo nas entradas (`DETECTOR_FEATURE_FLOOR` = 0,01) | salto de 0,25 MB na memória virava ~50σ (piloto 3) | **implementado** (16/out) |
| Tolerância de atraso na avaliação do online | perda de precisão ao vivo × replay (piloto 1) | em aberto (orientador) |

## Piloto 3: plano e critério (fixados antes de rodar)

**O que mudou desde o piloto 2:** aquecimento de 330 s antes de cada execução, sempre com o HPA no modo A (o modo da execução só entra logo antes do roteiro), e piso do σ = 0,05. Antes de rodar: `git pull`, `make build-analysis` e `make detector-deploy` na VPS, para o pod usar o código e a configuração novos.

**Comando:** `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B,C` (≈ 1 h: 3 execuções de ~12 min + 3 aquecimentos de 5,5 min + esperas). Depois: `make check-inicio DIR=datasets_hpa`.

**Critério de sucesso (fixado antes de rodar):**
- **alertas iniciais** (`make check-inicio`, antes da 1ª anomalia): caem de **53–87%** para **perto de zero**. Alguns alertas isolados são esperados com K = 2 (≈ 2,3% dos pontos de uma normal ficam acima de μ + 2σ), e o transiente de 30 s na troca aquecimento → roteiro pode gerar algum;
- **`false_scaleups` do modo B perto de 0** (eram 2).

Também observar, sem critério fixo: o tempo de reação do B passa a ser **definido** (era indefinido); o custo (`pod_seconds`) do B fica próximo do A; o `results/warmup_log.csv` mostra `at_min=1` (HPA no mínimo ao fim do aquecimento) em todas as execuções e `anomaly_level_b` abaixo de 0,5 — se ficar ≥ 0,5, o B escalaria assim que aplicado e o falso alarme só mudou de lugar.

Registrar aqui como Piloto 3, com a tabela do `check-inicio` e a do `hpa_results.csv`.

## Piloto 3 — HPA A × B × C, com aquecimento e piso (16/out/2026, 03:40–~04:45)

**Comando:** `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B,C`. Configuração: `WARMUP_SECONDS=330` (aquecimento sempre no modo A), `DETECTOR_SIGMA_FLOOR=0.05`, `HPA_B_DETECTOR=IF`, 5 detectores. Ordem sorteada: **A (03:40) → C (04:04) → B (04:27)**.

**Condição inicial (`results/warmup_log.csv`):** as 3 execuções terminaram o aquecimento com 2 réplicas (`at_min=1`) e `anomaly_level` do IF = 0,000. ✓

**Alertas antes da 1ª anomalia (`make check-inicio DIR=datasets_hpa`, 30 pontos):**

| Execução | AE | DBSCAN | EWMA | IF | LOF |
|---|---|---|---|---|---|
| A_burst_run1 | 9/30 | 8/30 | 0/30 | 5/30 | 9/30 |
| B_burst_run1 | 7/30 | 7/30 | 0/30 | 2/30 | 7/30 |
| C_burst_run1 | 7/30 | 7/30 | 0/30 | 2/30 | 7/30 |
| **total** | **26%** | **24%** | **0%** | **10%** | **26%** |
| piloto 2 (sem aquecimento) | 87% | 82% | 73% | 70% | 65% |

**HPA (`results/hpa/hpa_results.csv`, N = 1):**

| Métrica | A (só CPU) | B (CPU + IF) | C (CPU 35%) |
|---|---|---|---|
| `reaction_time_s` | 48,3 s | **38,3 s** | 43,3 s |
| `ready_time_s` | 55,0 s | 45,0 s | 50,0 s |
| `p95_anom_ms` | **465 ms** | 975 ms | 1.200 ms |
| `slo_viol_anom_pct` | **2,2%** | 13,2% | 18,1% |
| `slo_viol_all_pct` | 1,9% | 11,3% | 15,8% |
| `pod_seconds` | 3.590 | 3.625 (+1%) | 3.605 (+0,4%) |
| `scaleups` / `false_scaleups` | 3 / 0 | 5 / **0** | 4 / 0 |
| `k6_p95_ms` | 487 ms | 970 ms | 1.066 ms |

**Contra o critério (fixado antes):**
- `false_scaleups` do B perto de 0: **atingido** (0; eram 2).
- alertas iniciais perto de zero: **parcial**. Caíram muito (de 65–87% para 0–26%), o EWMA zerou e o IF (detector do B) ficou em 7–17%, mas AE, DBSCAN e LOF seguem em ~7 de 30 pontos, bem acima dos ~2% esperados com K = 2.
- também observado: tempo de reação do B **definido** e o menor (38 s × 48 s do A); custo do B ≈ A (+1%).

**Leitura (N = 1, padrão, não conclusão):**
1. **O aquecimento resolveu o problema principal:** sem scale-ups falsos, o B reage antes e com o mesmo custo. O piloto 2 (B "ganhando" por já estar escalado) não se repetiu.
2. **Alertas iniciais restantes: hipótese = transiente aquecimento → roteiro.** O roteiro recomeça do zero com rampa de 30 s (10 VUs → 0 → 10). ~7 de 30 pontos ≈ 35 s, que bate com a rampa + a janela de `rate()` de 30 s. O EWMA (só latência) não alarma; os multivariados, que veem a taxa de requisições cair e voltar, alarmam. **A verificar:** se os alertas se concentram nos primeiros ~40 s.
3. **Latência pior em B e C apesar de reagirem antes.** O C também piorou sem usar detector, então a causa é algo que B e C têm em comum e o A não: **mais scale-ups** (5 e 4 × 3). Três hipóteses, não excludentes:
   - **(a) pod frio:** o pod novo passa na prontidão (`/health`, leve) e recebe tráfego enquanto o Python ainda aquece, com limite de 300m de CPU (`k8s/app/deployment.yaml`). Mais scale-ups = mais pods frios atendendo no pico;
   - **(b) estado da app crescendo:** a app guarda os itens **em memória, por pod** (`items_store` em `app/main.py`); cada POST acrescenta um item e `/report`, `/search` e até o GET leve percorrem todos. Os 2 pods mínimos nunca reiniciam e ficam mais lentos a cada execução. Ordem A → C → B: o A, primeiro, teve a menor latência. Seria um **viés de ordem** (a aleatorização só o transforma em variância);
   - **(c) ruído com N = 1:** o mesmo modo A deu 590 ms no piloto 2 e 465 ms agora.

   **Uma consulta separa (a) de (b):** p95 da latência **por pod** no intervalo do `B_burst_run1`, `histogram_quantile(0.95, sum by (le, pod) (rate(http_request_duration_seconds_bucket{namespace="anomaly-lab"}[30s])))`. Pods **novos** lentos nos primeiros 30–60 s e depois normais → (a). Os 2 pods **antigos** sempre mais lentos que os novos (que nascem com 100 itens) → (b), confirmado por `app_items_total` por pod. Latência alta igual em todos → (c) ou nó sobrecarregado.

   **Alcance:** (a) afeta só a Fase 3 (a Fase 1 roda no modo A, com poucos scale-ups). (b) afetaria **também a Fase 1**: a latência é uma das 4 features, e o crescimento do estado mudaria o "normal" de uma execução para outra (e dentro dela, a cada pico com POSTs). Por isso (b) precisa ser descartada ou corrigida **antes** da Fase 1 definitiva.

**Verificações (feitas, 16/out):**
- **Transiente aquecimento → roteiro: confirmado.** Em B e C, os alertas antes da 1ª anomalia estão **só** em 15–45 s (7 pontos: a rampa de 30 s do roteiro + a janela do `rate()`); EWMA nenhum. No A, além desses, alertas em 140 e 145 s nos 4 multivariados, com taxa e latência normais: só na 1ª execução depois do redeploy do detector; tratado como pontual.
- **Estado da app crescendo: confirmado.** Os 2 pods mínimos estavam de pé havia **9 h** (desde antes do piloto 1) com **4.055 e 3.850 itens** (`app_items_total`; a semente é 100), ~40×. Cada execução encontra uma app mais lenta que a anterior: afeta a Fase 3 (latência) **e a Fase 1** (latência e CPU são features). Corrigir antes da Fase 1 definitiva.
- Pod frio (hipótese a): não verificado à parte; o reinício da app + aquecimento proposto abaixo o cobre para os 2 pods base.

**Decisões tomadas (16/out, implementadas):**
1. **reiniciar a app antes de cada execução** (Fases 1 e 3), antes da espera pelas réplicas: toda execução começa com 2 pods novos e 100 itens. Os itens por pod passam a ser registrados no `warmup_log.csv` (`items_per_pod`);
2. **sobrepor as rampas** na troca: o aquecimento desce (VUs → 0 em 30 s) enquanto o roteiro sobe (0 → VUs), e o roteiro começa 30 s antes do fim do aquecimento;
3. **piso relativo nas entradas** do detector online (`DETECTOR_FEATURE_FLOOR` = 0,01): σ de cada feature = máx(σ, 1% de |μ|). Causa dos alertas de 140–145 s no A: a memória é quase constante (σ ≈ 0,005 MB) e um salto de 0,25 MB aos 135 s (provável coleta de lixo) virava ~50σ. Memória no A: 82,691 MB de 75 a 120 s, 82,941 aos 135 s, 82,664 aos 150 s. Validação: [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md#8-validação-do-piso-nas-entradas).

## Piloto 4: correções do piloto 3 + LSTM (6 detectores)

**O que mudou desde o piloto 3:** app reiniciada antes de cada execução, rampas sobrepostas na troca, piso nas entradas (0,01) e o LSTM como 6º detector (pedido do orientador). Junta num só piloto a validação das correções e a do LSTM: o LSTM não afeta os outros detectores (validado no replay) nem o HPA do B (que usa o IF).

**Antes de rodar, na VPS:** `git pull`; no `.env`, `DETECTOR_ALGOS=EWMA,IF,LOF,DBSCAN,AE,LSTM`, as variáveis `LSTM_*` e `DETECTOR_FEATURE_FLOOR=0.01`; `make build-analysis` e `make detector-deploy` (a linha de partida do `make detector-logs` deve listar os 6, `piso_σ=0.05` e `piso_entrada=0.01`).

**Comandos:**
```bash
make clean                 # o piloto 3 já está registrado aqui
make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B,C   # ≈ 1 h
make check-inicio DIR=datasets_hpa
cat results/warmup_log.csv
cat results/hpa/hpa_results.csv
make detector-ciclo MIN=70       # p95 do ciclo com os 6 detectores + reinícios do pod (1º teste do LSTM no cluster)
```
No Grafana, painel **"Saúde do detector"**: o mesmo tempo de ciclo, ao longo das execuções.

**Critério de sucesso (fixado antes de rodar):**
- **alertas iniciais perto de 0 em todos os detectores**, LSTM incluído (alguns isolados com K = 2 são esperados; o padrão de 15–45 s do piloto 3 não deve aparecer);
- **itens por pod iguais no início de todas as execuções** (`items_per_pod` no `warmup_log.csv`, ~100 por pod no burst) e `at_min=1` em todas;
- **nenhum scale-up falso** (`false_scaleups` = 0 em A, B e C);
- **p95 do ciclo do detector < 2,5 s** (metade de `DETECTOR_STEP_SECONDS`) com os 6 detectores, pelo `make detector-ciclo` (no replay com 0,5 núcleo: 1,13 s), e **nenhum reinício** do pod do detector (sem `OOMKilled`). Se não ficar, aumentar `LSTM_RETRAIN` e registrar aqui.

**Se algo falhar:** cada correção tem um interruptor no `.env` e um commit próprio. Para desligar: `RESTART_APP=0`, `WARMUP_OVERLAP=0`, `DETECTOR_FEATURE_FLOOR=0` (depois `make detector-deploy`) ou tirar `LSTM` de `DETECTOR_ALGOS` (depois `make detector-deploy`).

Também observar, sem critério fixo: a latência de A, B e C fica comparável (no piloto 3, B e C ficaram piores, com a app crescendo); o tempo de reação do B continua o menor.

**Opcional (piloto 4b, ≈ 20 min):** `make experiment-quick` para ver o LSTM **offline** no pipeline da Fase 1 (`LSTM` e `LSTM_online` no `detection_results.csv` e no relatório).

Registrar aqui como Piloto 4.
