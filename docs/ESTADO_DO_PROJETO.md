# Estado do projeto (18/out/2026)

> **Resumo.** Em caso de divergência, valem [DECISOES_METODO.md](DECISOES_METODO.md) (decisões) e [PILOTOS.md](PILOTOS.md) (pilotos).

Resumo completo do que está feito, decidido e pendente, para quem chega agora. Os detalhes ficam nos documentos citados; este arquivo é o mapa.

Dissertação de mestrado PPGCC/UFMA, Ricardo F. Costa, orientador Prof. Dr. Mário A. M. Teixeira: **"Detecção de Anomalias em Kubernetes Baseada em Observabilidade Contínua"**.

---

## 1. O projeto em 3 fases

| Fase | O que faz | Tamanho |
|---|---|---|
| **1. Comparar detectores** | 6 detectores não supervisionados × 3 cargas k6 (burst, rampup, shift) × 10 repetições, **offline e online**; HPA fixo no modo A. Métrica: F1 (e precisão, recall, MTTD) | 30 execuções, ~11 h |
| **2. Integrar** | detector online no cluster publica `anomaly_level`; o Prometheus Adapter o entrega ao HPA como métrica externa, sem modificar o Kubernetes | — |
| **3. Avaliar o HPA** | modos **A** (CPU 50%), **B** (CPU 50% + anomalia do detector escolhido na Fase 1), **C** (CPU 35%, controle: escalar cedo sem detector), D opcional; × 3 cargas × 10 rep. Métrica principal pré-registrada: **tempo de reação**; também p95 e % acima do SLO (500 ms) nas anomalias, custo (pod·s), scale-ups falsos | 90 execuções, ~35 h |

Comparações da Fase 3: **B × A** (o proativo é melhor?), **B × C** (é a detecção ou só mais pods?), **C × A** (escalar cedo basta?).

## 2. Infraestrutura

- Tudo em container; no host só Docker, k3d e kubectl. Cluster k3d numa VPS (`ROLE=server`); k6 na própria VPS em núcleos separados (`CLUSTER_CPUS` / `LOADGEN_CPUS`); o notebook só acompanha pelo Grafana, via VPN.
- App FastAPI de teste: 1 worker por pod, limite 300m de CPU, request 100m, 2 a 8 réplicas.
- Prometheus, Grafana (dashboards "Anomaly Detection Lab" e "Detector Online & HPA"), kube-state-metrics, Prometheus Adapter. Toda configuração vem do `.env` (`.env.example` versionado).
- Imagem de análise com PyTorch só CPU (1,38 GB). Pod do detector: limite 0,5 núcleo e 768 Mi.

## 3. Os 6 detectores

| Detector | Classe | Offline (Fase 1) | Online |
|---|---|---|---|
| EWMA | estatístico, 1 sinal (latência p95) | fora de μ ± 3σ (base nos primeiros 150 s) | \|média suavizada − μ\| / 3σ |
| IF | isolamento | os 10% mais estranhos (contamination 0,1) | nota > μ + K·σ |
| LOF | densidade local | os 10% mais estranhos | nota > μ + K·σ |
| DBSCAN | densidade global | ruído (min_samples 8, eps P90) | distância / eps |
| AE | reconstrução (MLP 4-3-2-3-4) | erro > μ + 2σ | erro > μ + K·σ |
| LSTM (6º, pedido do orientador) | previsão temporal | erro > μ + 2σ; 12 primeiros pontos = normais | erro > μ + K·σ |

- 4 sinais: latência p95, CPU, memória e taxa de requisições (memória e CPU são a soma dos pods).
- Parâmetros de EWMA, IF e LOF idênticos aos da qualificação. LSTM fixo: sequência de 12 pontos (1 min), 16 unidades, 30 épocas, Adam, semente 42, determinístico, 1 thread; só muda com base no replay da qualificação.
- **Online:** a cada 5 s, janela de referência de 60 pontos (**5 min**, fixa) terminando 30 s antes do ponto (gap); K = 2; piso do σ das notas = 5% da média; piso nas entradas = 1% da média; AE e LSTM retreinam a cada 12 passos, defasados 6 entre si. `anomaly_level` = fração de alertas nos últimos 3 passos; o modo B age a partir de 0,67 (alvo 0,5).
- Os 6 rodam num só pod, em sequência, a cada 5 s ("mesma foto" dos dados). Custo medido no piloto 4: ciclo p95 0,48 s, CPU do pod ~0,03 núcleo, 0 reinícios.
- **Offline × online:** o offline (série inteira na mão) **não é um teto** do online. Ele vê o futuro, mas treina sobre os picos (*masking*), e IF/LOF offline têm cota fixa de 10% (`contamination`), enquanto o online usa a régua μ + K·σ dos últimos 5 min, sem cota. A comparação mede o efeito de operar online e pode favorecer qualquer lado (replay da qualificação: online venceu em 13 de 18 combinações detector × cenário, não em todas). O detector do B sai só do online.
- LSTM no replay dos 9 CSVs da qualificação (configuração final): F1 online burst 0,606, rampup 0,451, shift 0,356, entre os melhores e empatado com AE e DBSCAN. Offline fraco (aprende os picos como normais).

Detalhes: [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md), [README](../README.md).

## 4. Procedimento de cada execução (`bin/experiment.sh`)

1. HPA no modo A;
2. app reiniciada: estado limpo, 100 itens por pod (`RESTART_APP=1`);
3. espera 2 réplicas + cooldown de 120 s;
4. aquecimento de 330 s com a carga normal do cenário (`k6-scripts/warmup.js`; VUs burst 10, rampup 10, shift 30), descendo nos últimos 30 s enquanto o roteiro sobe (`WARMUP_OVERLAP=30`): carga total constante na troca;
5. 15 s antes da troca: confere réplicas, `anomaly_level` do B e itens por pod (`results/warmup_log.csv`);
6. só então aplica o modo da execução (B, C ou D);
7. roteiro k6.

- Ordem sorteada com semente fixa; retomável; execução sem resumo do k6 é inválida e refeita.
- Na Fase 3, o detector roda **igual nos modos A, B e C** (um pod, `DETECTOR_ALGOS` fixo); o modo só muda quem lê o `anomaly_level`.
- Ao fim de cada fase: `results/detector_ciclo_<fase>.txt` (ciclo e CPU do detector).
- Gabarito (`ANOMALY_PHASES`) e roteiros k6 nunca alterados. 1ª anomalia: 150 s (burst, shift), 175 s (rampup).

Detalhes: [HPA.md](HPA.md), seção 4; [RUNBOOK_VPS_VPN.md](RUNBOOK_VPS_VPN.md).

## 5. Avaliação e estatística (`scripts/detectors.py`, `scripts/stats_tlc.py`)

- **Acomodação inicial:** na Fase 1, pontos com offset < 60 s ficam fora de F1, precisão, recall e MTTD, offline e online; os detectores veem a série inteira (`EVAL_SKIP_SECONDS=60`). Não vale para a Fase 3.
- **Tolerância de atraso (secundária):** `f1_tol`, `precision_tol`, `recall_tol` ignoram os pontos normais até 30 s depois do fim de cada pico (`EVAL_TOLERANCE_SECONDS=30`), offline e online. O F1 principal é sempre sem tolerância.
- **MTTD:** janelas não detectadas ficam fora da média; janelas detectadas/total ao lado (`windows_detected`/`windows_total`; na Fase 1, 100 janelas por detector).
- **IC da média:** Ȳ ± t(0,975; N−1)·S/√N (material da disciplina; a coluna `H_tDP` guarda a forma t·S).
- **Fase 1: teste pareado** (mesmas execuções): IC 95% da diferença por execução, d̄ ± t·S_d/√N, gl = N − 1.
- **Fase 3: t de Student não pareado** (gl = nA + nB − 2) + teste visual dos ICs.
- **Só comparações planejadas na Fase 1** (as 66 de todos os pares não são geradas, nem como anexo): por cenário, 6 offline × online do mesmo detector + 5 do vencedor da regra do B × outros online. Duas famílias, ambas pareadas (mesmas execuções): **da escolha** (vencedor × outros online → decide a Fase 3) e **offline × online** (efeito de operar ao vivo → achado da dissertação, não escolhe ninguém); tabela em `DECISOES_METODO.md`, item 2.
- **Regra de escolha do detector do B** (pré-registrada em 16/out, esclarecida em 18/out; o relatório a aplica): maior média das 3 médias do F1 online (cada cenário pesa igual; o mesmo vencedor nos 3 cenários); grupo de empate = o 1º + todos sem diferença significativa (pareado) para ele em nenhum cenário → dentro do grupo vence o menor MTTD online; requisito de ciclo p95 < 2,5 s, verificado pelo pod (0,48 s com os 6).
- Diagnósticos: Shapiro-Wilk; replicações necessárias para H/Ȳ ≤ 10% e 20%; validação com o exemplo do slide 55.
- **Regressão garantida:** com `EVAL_SKIP_SECONDS=0` e `EVAL_TOLERANCE_SECONDS=0`, as métricas reproduzem exatamente a qualificação (45/45).
- `make selftest`: 22 testes.

## 6. Decisões de método

Fonte única: [DECISOES_METODO.md](DECISOES_METODO.md).

**Já em vigor e validadas:** aquecimento no modo A; rampas sobrepostas; app reiniciada antes de cada execução; piso das notas 0,05; piso nas entradas 0,01; modo C como controle; estatística do material.

**Fechadas em 28/out/2026, antes da Fase 1 (alinhadas com o orientador):**

| # | Decisão |
|---|---|
| 1 | teste pareado na Fase 1 (não pareado na Fase 3) |
| 2 | só comparações planejadas (6 + 5 por cenário) |
| 3 | LSTM no rol e candidato ao B |
| 4 | app reiniciada com 100 itens |
| 5 | Fase 1 com os 6 num pod; Fase 3 só o detector do B, **igual em A, B e C**; modo D **não usado** (fechado em 29/out/2026): Fase 3 só com A, B e C |
| 6 | tolerância de atraso de 30 s, secundária, offline e online |
| 7 | regra de escolha do B + métrica principal (tempo de reação) |
| 11 | acomodação de 60 s na avaliação da Fase 1 |
| 12 | janela do detector fixa em 5 min (valor da qualificação); sensibilidade só por replay |
| 8 | SLO 500 ms, com sensibilidade a 300 ms e 1 s (em 30/out/2026, antes da Fase 3: **250 ms** e 1 s, porque o histograma não tem balde em 300 ms; calculada na hora, porque os histogramas somem em 7 dias) |
| 10 | forma do IC: t·S/√N |
| 13 | ANOVA dispensada, porque as comparações são planejadas |
| 9 | ameaças à validade declaradas: cluster de 1 nó, carga sintética, app de teste, VPS compartilhada, partida a frio fora do escopo, detector disputando CPU com a app, ruído de latência por pod; em 29/out: drift ao longo do dia e shift começando escalado; em 01/nov, depois da Fase 3: teto de 8 réplicas atingido (B no burst; B e C no rampup), limites 2/8 herdados da qualificação |

**Fechadas em 29/out/2026, depois da Fase 1 e antes da Fase 3 (Ricardo; só dados de ambiente; falta confirmar com o orientador):**

| # | Decisão |
|---|---|
| 14 | drift ao longo do dia: manter os blocos sorteados; registrar o p95 do aquecimento (`warmup_p95_ms`, sempre no modo A) e mostrar o equilíbrio entre A, B e C antes de olhar o tempo de reação; não excluir nem refazer execuções lentas |
| 15 | shift começando escalado (3–7 réplicas): manter o shift; tempo de reação só nas janelas com reação, com as janelas sem reação e as réplicas iniciais ao lado |
| 17 | avaliação só até o fim do k6 + 15 s (`EVAL_END_MARGIN_SECONDS`): na Fase 1, número principal = corrigido, com o "como rodou" ao lado (LSTM continua escolhido; saída em `fase1_corrigido/`); na Fase 3, scale-ups falsos até o fim do k6 + 60 s e custo até o fim da janela |
| 18 | (30/out/2026, depois do piloto 5) `ready_time_s` nas mesmas janelas do tempo de reação e contado depois do pedido; séries de réplicas de cada execução em `results/hpa/series/`; `make hpa-recalc` |
| 16 | janela exportada além do fim do k6 (pontos-fantasma com o último valor repetido): na Fase 3 o script espera o fim da janela antes de exportar; a Fase 1 fica igual à qualificação (sensibilidade: o LSTM segue escolhido) |

## 7. Pilotos

Detalhes: [PILOTOS.md](PILOTOS.md). Dados de piloto nunca entram na dissertação.

| Piloto | O que mostrou | O que gerou |
|---|---|---|
| 1 (Fase 1, burst, N = 1) | online sem atraso (replay) supera o offline em 4 de 5; ao vivo perde ~0,2 de F1, quase tudo em precisão | investigar alarmes falsos |
| 2 (HPA A × B) | 53–87% de alarmes falsos nos 150 s iniciais (detector aprendia o silêncio entre execuções); B "ganhou" por superprovisionar: +48% de custo, 2 scale-ups falsos, reação indefinida | aquecimento + piso do σ |
| 3 (A × B × C, com aquecimento) | alarmes iniciais 0–26%; B sem scale-up falso, reagiu 10 s antes do A com +1% de custo; mas B e C com latência pior. Vieses: transiente na troca (alertas 15–45 s), estado da app crescendo (~4.000 itens/pod, viés de ordem), salto de 0,25 MB na memória virando ~50σ | rampas sobrepostas, reinício da app, piso nas entradas |
| 5 (configuração da Fase 3: só o LSTM, B = LSTM) | pipeline novo ok: `warmup_p95_ms` 4,8–5,0 ms nos 3 modos, espera do fim da janela, ciclo p95 0,05 s; no B, `ready_time_s` (25 s) < `reaction_time_s` (40 s): janelas diferentes nas duas médias; réplicas não eram salvas. Confirmado com as séries: a cauda de alertas do LSTM depois do 1º pico levou o B de 4 a 6 pods com carga normal; ele entrou no 2º pico escalado e ficou no máximo (8) dos 350 aos 630 s; o 3º pico ficou sem reação por teto (+18% de custo) | decisão 18; recálculo feito (`ready_time_s` do B 47,5 s) |
| 4 (configuração final + LSTM) | condição inicial ok (100 itens, 2 réplicas); ciclo p95 0,48 s; latência de A, B e C comparável de novo (414–539 ms); reação A 48 s, B 42 s, C 38 s; custo B +3%, C +14% (1 scale-up falso, por CPU). Alertas iniciais: A 0 nos 6; B e C 0–30%. Dois tipos de oscilação de latência: logo após a troca (nas 3, sistemático) e num pod só em instantes irregulares (ruído do ambiente) | acomodação de 60 s; tolerância medida: 30 s |

- **Piloto 4, hipóteses:** descartadas — réplicas descendo no aquecimento, pod novo somando memória; **improvável, não descartada** — retreino do LSTM (relógio do pod, não do roteiro).
- **Transbordo de alertas após os picos** (base da tolerância): online ao vivo mediana 10–25 s, p90 ~30 s em EWMA e IF; replay da qualificação p90 25 s; cauda de 72–100 s só nos multivariados (estado do sistema após o escalonamento, não atraso).
- **Efeito registrado:** a base do EWMA offline (primeiros 150 s) inclui a oscilação da troca; possível limiar um pouco mais largo (sem correção: parâmetros da qualificação).
- **Ressalva:** a causa do 2º tipo de oscilação não foi verificada; se for throttling de CPU (limite 300m), pode depender do nº de pods e afetar os modos de forma diferente na Fase 3. Verificar antes da Fase 3.

## 8. Comandos principais

`make up`/`server-up`, `deploy`, `status`, `logs`, `experiment` (Fase 1), `experiment-quick`, `hpa-experiment` (Fase 3), `hpa-mode HPA_MODE=X`, `phase2-check` (sempre depois de `hpa-mode HPA_MODE=B`), `detect`, `stats`, `analyze`, `hpa-analyze`, `online-replay CSV=…`, `check-inicio DIR=…` (alertas antes da 1ª anomalia, em [0, 60) s e [60 s, 1ª anomalia)), `detector-ciclo MIN=…` (ciclo, CPU do pod, reinícios), `detector-logs`, `build-analysis` (importa no k3d e reinicia o detector), `selftest`, `clean`, `purge`. Todos explicados em [COMANDOS.md](COMANDOS.md).

## 9. Regras de trabalho

- Nunca fabricar ou ajustar resultados; qualificação só leitura; pilotos sempre registrados; decisões fechadas **antes** da fase que afetam e nunca mudadas depois de ver resultados.
- Git: commits por lotes, feitos pelo autor.
- Nunca expor `.env` nem kubeconfig; `BIND_ADDR` nunca `0.0.0.0`; nada de `docker system prune` na VPS.



## 10. Próximos passos

1. **Na VPS:** `git pull`; `EVAL_TOLERANCE_SECONDS=30` no `.env`; `make build-analysis`; `make selftest` (22 testes).
2. **Decisões:** todas as da Fase 1 fechadas em 28/out/2026 (alinhadas com o orientador). Modo D fechado em 29/out/2026: não usado.
3. **Fase 1: concluída** em 29/out/2026 (00h24–13h), com 30 execuções, todas com resumo do k6. A regra escolhe o **LSTM online** (F1 0,485 no corrigido, que é o principal pela decisão 17; 0,476 "como rodou"; MTTD 11,6 s). Explicação completa: [FASE1_EXPLICADA.md](FASE1_EXPLICADA.md). Achados de ambiente: drift ao longo do dia e shift começando escalado; ambos tratados nas decisões 14 e 15.
4. **Piloto 5** (30/out/2026): pipeline ok; gerou a decisão 18 e foi recalculado.
5. **Fase 3: concluída** de 30/out 18h19 a 01/nov/2026 ~08h50, 90 execuções (B = LSTM), backup no notebook (`VPS/FASE 3/backup_fase3_2026-11-01`). Explicação completa: [FASE3_EXPLICADA.md](FASE3_EXPLICADA.md).
   - **Ambiente equilibrado** (decisão 14): p95 do aquecimento com ICs sobrepostos em A, B e C nos 3 cenários; sem o drift da Fase 1.
   - **Métrica principal (tempo de reação): nenhuma diferença significativa** nas 9 comparações (burst A 43,5 / B 38,5 / C 42,5 s).
   - **Burst, secundárias:** B reduz o p95 nas anomalias (422 → 266 ms, p = 0,0005) e as requisições > 250 ms (15,2% → 4,0%) e > 500 ms (2,3% → 0,7%), com +20% de pod·s e 1,5 scale-up falso por execução. Rampup e shift: sem diferença de latência.
   - **Critério pré-registrado não atendido.** Explicação exploratória (séries de réplicas): o B escala **antes** dos picos (cauda de alertas do LSTM) e chega ao teto de 8 pods; o tempo de reação não conta pedidos anteriores ao pico, e os picos no teto saem da média.
   - Uma falha de permissão (`datasets_hpa/` com dono root) na 1ª tentativa do `B_shift_run1`; refeita do zero, sem aproveitar dados.
6. **Agora:**
   - levar ao orientador o resultado e a leitura "antecipa, mas a métrica não capta"; confirmar as decisões 14 a 18 e o SLO a 250 ms;
   - escrever: resultado nulo na principal, ganho de latência no burst com custo, limitações (teto de 8, definição do tempo de reação, poder baixo no rampup e no shift) e trabalhos futuros. **Não refazer** nenhuma fase;
   - opcional, até ~05/nov: a causa do drift da Fase 1 no Grafana (decisão 14, item 5), só observando;
   - melhoria pendente: `bin/experiment.sh` parar no início se `datasets_hpa/` ou `results/` não forem graváveis.
