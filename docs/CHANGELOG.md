# Changelog — versão pós-alinhamento (out/2026)

## Novo

- **DBSCAN e Autoencoder** no `detectors.py` (5 detectores). Rodados sobre os 9 CSVs reais da qualificação; EWMA, IF e LOF reproduzem exatamente os 27 resultados originais.
- **Detector online** (`scripts/online_detector.py`) como pod no cluster:
  - roda os 5 detectores em janela deslizante;
  - usa limiar dinâmico μ + K·σ;
  - publica `anomaly_score`, `anomaly_alert` e `anomaly_level` no Prometheus.

  Tem modo `--replay` para testar sem cluster.
- **Grafana:** dashboard novo "Detector Online & HPA". O painel de réplicas passou a vir do kube-state-metrics.
- **kube-state-metrics** (réplicas do Deployment e do HPA no Prometheus), necessário para medir o HPA.
- **Prometheus Adapter** com manifests explícitos, sem Helm: `anomaly_level` como métrica externa.
- **HPA em modos:** A (CPU 50%), B (CPU + anomalia/IF), C (CPU 35%) e D (CPU + anomalia/EWMA). A troca é feita com `make hpa-mode`.
- **`bin/experiment.sh`** para as Fases 1 e 3:
  - `REPS` configurável;
  - ordem aleatória com semente;
  - espera o HPA voltar ao mínimo antes de cada execução;
  - retomável.
- **Summary do k6 por execução** (avg, med, p90, p95, p99) e `k6_summary.py`.
- **`hpa_metrics.py`:** tempo de reação, tempo até Ready, p95 e violação de SLO nas janelas anômalas, pod·segundos, scale-ups falsos.
- **`stats_tlc.py`:** IC da média pelo TLC, t de Student com p-valor, teste visual, Shapiro-Wilk, replicações necessárias e validação com o slide 55; gera figuras e xlsx.
- **Topologia por papel** (`ROLE=local|server|client`):
  - portas publicadas só em `BIND_ADDR`;
  - API do Kubernetes acessível pela VPN (`make kubeconfig`);
  - `make vpn-check`.
- **`make selftest`:** testes do código de análise sem cluster.
- **Idempotência do detector:** o `make detector-deploy` só recria o pod quando a configuração muda (hash na anotação do pod).
- **Modos B e D configuráveis:** `HPA_B_DETECTOR` e `HPA_D_DETECTOR` aceitam qualquer um dos 5 detectores; o `make hpa-mode` recusa um detector que não esteja em `DETECTOR_ALGOS`.

## Novo (15/out, depois dos primeiros testes na VPS)

- **Topologia "tudo na VPS"** (recomendada com VPN instável): o k6 roda na própria VPS, em núcleos separados do cluster.
  - `CLUSTER_CPUS` e `LOADGEN_CPUS` no `.env` (vazios = sem fixação);
  - `make cpu-pin` fixa os nós do k3d com `docker update --cpuset-cpus`; o `make experiment` e o `make hpa-experiment` já chamam;
  - o k6 e a análise rodam com `--cpuset-cpus LOADGEN_CPUS`.
- **Execução inválida:** se o k6 não termina (sem resumo, por queda de conexão ou falta de memória), a execução não é marcada como concluída e é refeita na próxima chamada. Antes, entrava na estatística sem aviso.
- **`make purge`** remove também os binários `k3d` e `kubectl` de `/usr/local/bin`.
- **Documentação:**
  - `docs/HPA.md` (novo): como o HPA decide, os modos A/B/C/D, por que existe o C, pré-registro do detector do B, métricas e estatística da Fase 3;
  - `bin/experiment.sh`: enquanto espera as réplicas voltarem ao mínimo antes de cada execução, mostra o progresso a cada minuto (antes ficava mudo vários minutos depois de "HPA modo A"); a espera em si não mudou;
  - `docs/PILOTOS.md` no `README.md`, com a regra: cada execução de teste relevante é registrada nele;
  - **Grafana, dashboard "Detector Online & HPA":** painel de score em escala log com linha tracejada do limiar em 1; painel de alertas com 0 = "normal" (cinza) e 1 = "alerta" (vermelho). `docs/GRAFANA.md` descreve os painéis como estão e tira os dois da lista de problemas; README com links para `docs/GRAFANA.md` e `docs/DETECTOR_ONLINE.md` ao lado do `docs/HPA.md`;
  - `docs/RUNBOOK_VPS_VPN.md` e `docs/COMANDOS.md`: `make phase2-check` sempre precedido de `make hpa-mode HPA_MODE=B` (em outro modo a seção do HPA só mostra CPU e a checagem fica pela metade);
  - `README.md`: link para `docs/DETECTOR_ONLINE.md`, ao lado do `docs/HPA.md`;
  - `docs/RUNBOOK_VPS_VPN.md`: degustação do TL;DR virou sequência com "o que conferir" em cada passo, `make online-replay` para separar atraso do cluster de qualidade do detector, e o lembrete de decidir com o orientador, antes da rodada longa, a tolerância de atraso na avaliação do online;
  - `docs/RUNBOOK_VPS_VPN.md`: TL;DR em passos (Docker sem `sudo`, cluster, **degustação** de Fase 1 e Fase 3 em minutos, `make clean` antes da rodada longa);
  - `docs/RUNBOOK_VPS_VPN.md`: `tmux new -A -s exp` (o mesmo comando cria a sessão ou volta a ela depois de uma queda do SSH);
  - `docs/COMANDOS.md`: seção "Administração pela CLI" com os comandos `kubectl`/`k3d` de consulta;
  - `docs/RUNBOOK_VPS_VPN.md` reescrito: TL;DR no topo, topologias A e B, teste da VPN com `curl`, `tmux`/`nohup`, diagnóstico de "connection refused".

## Novo (16/out, depois do piloto 2): falsos alarmes com referência "vazia"

**Por quê.** No piloto 2 ([PILOTOS.md](PILOTOS.md)), os 5 detectores online passaram **53–87%** dos primeiros 150 s do burst em alerta, sem nenhuma anomalia. Causa: entre execuções o cluster fica parado, e a janela de referência do detector (5 min) era feita desse silêncio; o tráfego **normal** do início do roteiro parecia anômalo. No modo B isso virou 2 scale-ups falsos, +48% de custo e tempo de reação indefinido. Com o cluster ocioso, o σ das notas ia a ~0 e a razão chegava a ~10⁵ (AE).

- **Aquecimento antes de cada execução** (`WARMUP_SECONDS`, padrão 330 s = (60 + 6) × 5 s, o tamanho da referência + gap; `0` desliga):
  - `k6-scripts/warmup.js` (novo): carga constante com o **mesmo mix da fase normal** de cada roteiro; VUs = nível no fim da 1ª rampa (burst 10, rampup 10, shift 30, mapa `WARMUP_VUS` no `bin/experiment.sh`). Os roteiros k6 e o ground truth **não** mudaram;
  - roda depois do `wait_baseline` e do cooldown e imediatamente antes do roteiro, nos núcleos `LOADGEN_CPUS`; entre o fim do aquecimento e o roteiro, só a conferência das réplicas, sem espera;
  - se o HPA escalou durante o aquecimento, o log avisa; cada aquecimento é registrado em `results/warmup_log.csv`. Não gera CSV nem entra na avaliação;
  - **Fase 3: aquecimento sempre no modo A.** Espera, cooldown e aquecimento rodam com o HPA no modo A; o modo da execução (B, C ou D) só é aplicado depois da conferência das réplicas, imediatamente antes do roteiro. Antes, o modo era aplicado no início: um alarme na passagem "parado → aquecimento" faria o B escalar antes do roteiro e começar com mais réplicas que A e C. Agora toda execução começa com 2 réplicas, em qualquer modo (mesma condição inicial). O `warmup_log.csv` registra também o `anomaly_level` do detector do B ao fim do aquecimento (`b_detector`, `anomaly_level_b`, lido pelo Adapter como o HPA o veria);
  - custo: +330 s por execução. Com REPS=10: Fase 1 = 30 execuções ≈ **+2,75 h**; Fase 3 (A, B, C) = 90 execuções ≈ **+8,25 h**.
- **Piso relativo do σ** no detector online (`DETECTOR_SIGMA_FLOOR`, padrão 0,05; `0` = comportamento antigo): no `_zratio`, σ_ef = máx(σ, piso·|μ|). Vale para IF, LOF e AE (EWMA e DBSCAN não usam essa razão). Passado ao ConfigMap (`make detector-config`, entra no hash do pod) e ao `make online-replay`.
  - **Validação** (replay dos 9 CSVs da qualificação, [validacao/piso_sigma.csv](validacao/piso_sigma.csv)): com piso 0 o replay reproduz exatamente o `results_qualificacao/online_replay_K2.csv` (45/45); com 0,05 o F1 médio é **idêntico** em 14 de 15 combinações e o LOF varia ±0,005. O piso não custa F1 em regime com carga; o efeito dele só aparece com o cluster ocioso (σ ≈ 0), que esses CSVs não têm. **Decidido: 0,05** (16/out). Motivo: no regime com carga não muda o F1, e com o cluster quase ocioso impede as razões de ~10⁵ do piloto 2; proteção sem custo medido. Registrado no regras do projeto e como padrão no `.env.example`.
- **`make check-inicio DIR=…`** (`scripts/check_inicio.py`, novo): conta, por CSV e por detector, os alertas `online_*` antes da 1ª janela anômala do cenário (lida de `ANOMALY_PHASES`, não fixa em 150 s). Verificação permanente do problema.
- **`make selftest`:** `test_sigma_floor` (referência constante + 2% → alarma sem piso, não alarma com piso; 50% alarma nos dois; o exemplo numérico da documentação) e `test_check_inicio`. Agora 9 testes.
- **Escopo do detector online:** avaliado **em regime** (referência com carga normal); a partida a frio (pod recém-criado ou cluster vindo do zero) fica fora do escopo.

## Novo (16/out): LSTM, o 6º detector

**Por quê.** Pedido do orientador, antes da Fase 1 definitiva. Os outros multivariados (IF, LOF, DBSCAN, AE) olham cada ponto isolado; a LSTM **acrescenta a dimensão temporal (previsão do próximo ponto)**. Referências: Malhotra et al., *Long Short Term Memory Networks for Anomaly Detection in Time Series*, ESANN 2015; Hundman et al., KDD 2018.

- **Modelo** (`scripts/lstm_model.py`, novo): LSTM preditiva não supervisionada. As 4 features padronizadas; os `LSTM_SEQ_LEN` = 12 pontos anteriores (1 min) preveem o seguinte; nota = erro quadrático médio da previsão. Arquitetura fixa: 1 camada LSTM (`LSTM_HIDDEN` = 16) → linear, Adam (lr 0,01), `LSTM_EPOCHS` = 30, lote único. Reprodutível: `torch.manual_seed(42)`, algoritmos determinísticos, 1 thread de CPU.
- **Offline** (`detect_lstm` em `detectors.py`, entrada `"LSTM"` em `DETECTORS`): treina na execução inteira; alerta se erro > μ + 2σ dos erros de treino (critério do AE offline). Os primeiros 12 pontos, sem histórico, contam como normais (a 1ª janela anômala começa no ponto 30 ou depois).
- **Online** (`_lstm` em `online_detector.py`): treina na janela de referência (com o gap); a sequência do ponto atual são os 12 pontos anteriores a ele; decisão pelo `_zratio` (mesmo K e mesmo piso do σ de IF, LOF e AE). Retreina a cada `LSTM_RETRAIN` = 12 passos, **defasado 6 passos do AE**: na 1ª versão os dois retreinavam no mesmo ciclo e o máximo chegava a 4,8 s. O PyTorch é carregado na partida do serviço. O `--replay` passou a mostrar o tempo por ciclo (média, p95, máximo).
- **Imagem de análise:** PyTorch 2.5.1 **só CPU** (`--index-url https://download.pytorch.org/whl/cpu`, no `scripts/Dockerfile`). Tamanho: **579 MB → 1,38 GB**.
- **Pod do detector:** memória `requests` 192 Mi → 384 Mi e `limits` 384 Mi → 768 Mi (pico de ~410 MiB medido no replay com os 6 detectores).
- **Integração:** `DETECTOR_ALGOS=EWMA,IF,LOF,DBSCAN,AE,LSTM` (padrão no `.env.example`, no `experiment.sh`, no `export_metrics.py` e no `online_detector.py`); `LSTM_SEQ_LEN`, `LSTM_HIDDEN`, `LSTM_EPOCHS`, `LSTM_RETRAIN` no `.env.example`, no ConfigMap (e no hash do pod), no `make online-replay` e no `make detect` (via `ANALYSIS_RUN`); a validação do `DETECTOR_ALGOS` aceita `LSTM`, então `HPA_B_DETECTOR`/`HPA_D_DETECTOR` podem ser `LSTM`. `stats_tlc.py`: LSTM na ordem dos detectores; a paleta já tinha a 6ª cor (verde `#008300`) e `LSTM_online` a herda. Grafana e Prometheus Adapter agrupam por `detector` e pegam o LSTM sem mudança; o `export_metrics.py` exporta `online_LSTM` sozinho.
- **`make selftest`:** `test_lstm_offline` (pico injetado detectado), `test_lstm_online` (razão finita), `test_lstm_determinism` (mesma semente → mesmo resultado, offline e online). Agora 12 testes.
- **Validação** (9 CSVs da qualificação, sem cluster; [validacao/lstm_qualificacao.csv](validacao/lstm_qualificacao.csv), [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md#7-validação-do-lstm)): F1 do replay online do LSTM = 0,605 (burst), 0,453 (rampup), **0,379 (shift, o melhor dos 6)**; offline fraco (0,04–0,34, *masking*). Ciclo com 6 detectores e 0,5 núcleo: média 0,47 s, **p95 1,13 s**, máximo 3,92 s (limite 5 s). Os 5 detectores antigos ficaram idênticos (offline 45/45 com a qualificação, replay 45/45 com a validação do piso). Nenhum parâmetro do LSTM foi mudado por causa da validação.

## Novo (16/out, depois do piloto 3): condição inicial e piso nas entradas

**Por quê.** O piloto 3 ([PILOTOS.md](PILOTOS.md)) confirmou três problemas, todos verificados nos dados:
1. **estado da app crescendo:** os 2 pods mínimos estavam de pé havia 9 h com **4.055 e 3.850 itens** (a semente é 100); a memória no início das execuções subiu A 82,7 → C 85,7 → B 89,1 MB, na ordem em que rodaram. A app guarda os itens em memória por pod e `/report`, `/search` e o GET leve percorrem todos: cada execução herdava uma app mais lenta. **Viés de ordem**, nas Fases 1 e 3;
2. **transiente da troca aquecimento → roteiro:** AE, DBSCAN e LOF alarmavam de 15 a 45 s em todas as execuções (o roteiro recomeça do zero com rampa de 30 s);
3. **salto da memória virando outlier:** alertas dos 4 multivariados em 140–145 s no A, com taxa e latência normais. A memória é quase constante (σ ≈ 0,005 MB) e um salto de 0,25 MB aos 135 s virava ~50σ na padronização das entradas.

- **App reiniciada antes de cada execução** (`restart_app` no `bin/experiment.sh`, Fases 1 e 3): `rollout restart deploy/fastapi-app`, espera o rollout e depois as réplicas no mínimo. Toda execução começa com 2 pods novos e 100 itens por pod. O aquecimento vem depois e também aquece os pods novos ("pod frio"). `results/warmup_log.csv` ganhou `items_per_pod` (itens de cada pod no início do roteiro, via Prometheus); um arquivo no formato antigo é guardado à parte.
- **Rampas sobrepostas na troca:** o `warmup.js` termina com uma descida (VUs → 0 em 30 s, `RAMP_DOWN`) e o roteiro começa 30 s antes do fim do aquecimento, enquanto sobe de 0 → VUs (a 1ª rampa dele): carga total constante. As conferências (réplicas, `anomaly_level`, itens) e o `apply_mode` acontecem 15 s antes da descida. O `start` da execução continua sendo o início do roteiro; roteiros e gabarito inalterados. Custo por execução: ≈ +30 s do reinício, −30 s da sobreposição.
- **Interruptores no `.env`:** `RESTART_APP` (1; 0 = não reinicia a app) e `WARMUP_OVERLAP` (30 s; 0 = sem sobreposição), para desligar uma correção sem mexer no código se um piloto mostrar problema. Com `DETECTOR_FEATURE_FLOOR=0` e `DETECTOR_ALGOS` sem `LSTM`, as 4 mudanças do piloto 3 e do LSTM podem ser desligadas uma a uma.
- **`make detector-ciclo MIN=70`** (`scripts/detector_ciclo.py`, novo): tempo de ciclo do detector no cluster (`detector_step_seconds`: média, p50, p95, p99, fração acima de 1/2/5 s), **CPU do pod `online-detector`** (média, p95, máximo) e reinícios do pod (`OOMKilled`). Para o 1º teste do LSTM no cluster (piloto 4); critério p95 < 2,5 s. O `experiment.sh` o roda no fim de cada fase e salva em `results/detector_ciclo_<fase>.txt` (Fase 1 inclusive).
- **Custo da observação** (`docs/DETECTOR_ONLINE.md`, seção 5): os 6 detectores rodam num só pod, em sequência, nos núcleos da app; disputam CPU com ela (igual nos 3 modos) e um detector pesado atrasa todos os alertas, inclusive o do HPA. O laboratório é o pior caso (em produção rodaria só o escolhido). A tabela "A decisão de cada algoritmo" ganhou a regra offline de cada detector.
- **`make hpa-mode`:** só exige em `DETECTOR_ALGOS` o detector do modo aplicado (antes exigia o do B e o do D sempre). Permite, se decidido, rodar na Fase 3 só o detector do B.
- **Piso relativo nas entradas do detector online** (`DETECTOR_FEATURE_FLOOR`, padrão 0,01; 0 = desligado): σ de cada feature = máx(σ, piso·|μ|) na padronização pela referência (`_scale` em `online_detector.py`). Mesma lógica do piso das notas. Vale para IF, LOF, DBSCAN, AE e LSTM (o EWMA usa a latência bruta). No ConfigMap (e no hash do pod) e no `make online-replay`. `make selftest`: `test_feature_floor` (13 testes).
  - **Validação** (replay dos 9 CSVs da qualificação, 6 detectores, piso das notas 0,05; [validacao/piso_entrada.csv](validacao/piso_entrada.csv), [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md#8-validação-do-piso-nas-entradas)): com 0 o replay é idêntico ao anterior (54/54); com 0,01 o F1 fica igual em 10 de 18 combinações e varia de −0,023 a +0,028 nas outras (média −0,002), sem perda sistemática.

## Novo (30/out): sensibilidade do SLO calculada na hora (decisão 8)

- `scripts/hpa_metrics.py`: colunas `slo_viol_anom_250ms_pct` e `slo_viol_anom_1000ms_pct` (% de requisições acima de 250 ms e de 1 s nas janelas anômalas), ao lado do `slo_viol_anom_pct` (500 ms). Os histogramas somem do Prometheus em 7 dias, então a conta é feita em cada execução. Nenhuma outra métrica muda.
- 250 ms em vez dos 300 ms da decisão 8: o histograma da app não tem balde em 300 ms; 250 ms é contagem exata (registrado no item 8 de `DECISOES_METODO.md`).
- `SLO_SENSITIVITY_SECONDS=0.25,1` no `.env.example`, no `Makefile` (também passado ao `ANALYSIS_RUN`, com o `SLO_SECONDS`) e no `bin/experiment.sh`.
- `scripts/stats_tlc.py`: o relatório da Fase 3 traz as colunas de sensibilidade logo depois do SLO principal.
- `make selftest`: `test_slo_sensitivity`. Agora são 22 testes.
- Atualizados `HPA.md`, `COMANDOS.md`, `RUNBOOK_VPS_VPN.md`, `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md`, `FASE1_EXPLICADA.md` e regras do projeto.

## Novo (30/out, depois do piloto 5): tempo até pronto e séries de réplicas (decisão 18)

- `scripts/hpa_metrics.py`:
  - `ready_time_s` usa só as janelas com reação, contando a partir do pedido (antes, qualquer janela em que as disponíveis subiram: no piloto 5, o B teve o "pronto" em 25 s e o "pedido" em 40 s);
  - `--series`: grava as réplicas desejadas e disponíveis da execução;
  - `--recalc`: refaz as métricas de cada linha de um `hpa_results.csv` pelo Prometheus.
- `bin/experiment.sh`: cada execução da Fase 3 grava `results/hpa/series/<modo>_<cen>_runN.csv`.
- `Makefile`: `make hpa-recalc DIR=<pasta>` (não sobrescreve; grava `hpa_results_recalc.csv` e `series/`). `ANALYSIS_RUN` aceita volumes extras (`ANALYSIS_VOLS`).
- `make selftest`: caso novo em `test_hpa_metrics` (pod pedido antes da janela não conta) e `test_hpa_series`. Agora são 21 testes.
- `.gitignore`: `pilotos/` (dados de piloto guardados fora de `results/`).
- `docs/PILOTOS.md`: piloto 5. `DECISOES_METODO.md`: item 18. Atualizados `HPA.md`, `COMANDOS.md`, `RUNBOOK_VPS_VPN.md`, `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md` e regras do projeto.

## Novo (29/out): avaliação só até o fim do k6 (decisão 17)

- `docs/DECISOES_METODO.md`, item 17, registrado **antes** de gerar os números:
  - na Fase 1, o número principal é o corrigido, avaliado só até o fim do roteiro k6 + 15 s (burst 633, rampup 575, shift 925 s), com o "como rodou" ao lado;
  - na Fase 3, os scale-ups falsos só contam até o fim do k6 + 60 s, e o custo vai até o fim da janela.
- `scripts/export_metrics.py`: `K6_END_SECONDS` (fim de cada roteiro), separado do gabarito, que não muda.
- `scripts/detectors.py`: `EVAL_END_MARGIN_SECONDS` (padrão 15; `off` = série inteira). As linhas depois do corte saem **antes** da imputação, então nem os detectores offline as veem. Nova coluna `eval_end_s`; opção `--eval-end-margin`.
- `scripts/hpa_metrics.py`: `reaction_metrics(..., count_until=)`. Os scale-ups falsos contam só até o fim do k6 + `REACTION_GRACE_SECONDS`.
- `scripts/stats_tlc.py`: o relatório da Fase 1 diz qual corte foi usado.
- `make selftest`: `test_eval_end` e o caso novo em `test_hpa_metrics`. `test_eval_skip` passa a isolar a acomodação. Agora são 20 testes.
- `Makefile` e `.env.example`: `EVAL_END_MARGIN_SECONDS=15`.
- **Fase 1 corrigida**, gerada no notebook a partir do backup da VPS, em `fase1_corrigido/`. Antes, o "como rodou" foi reproduzido célula por célula: 360 linhas, ICs, testes t e o ranking. Resultado: LSTM 0,485 e IF 0,482; a regra do B continua dando LSTM; offline × online continua 14/2/2.
- Atualizados `FASE1_EXPLICADA.md`, `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md`, `COMANDOS.md`, `RUNBOOK_VPS_VPN.md` e regras do projeto.

## Novo (29/out): pontos-fantasma no fim do CSV (decisão 16)

- **Causa:** a janela exportada (`DURATION`: 720/780/960 s, a da qualificação) passa do fim dos roteiros k6 (618/560/910 s). A exportação rodava ~15 s depois do fim do k6 e pedia pontos do futuro. O Prometheus os preenche repetindo o último valor dos gauges (memória, alertas online, réplicas) por até 5 min. No rampup são ~36 pontos por execução (23% do CSV). A qualificação tem o mesmo rabo.
- **Fase 1:** fica como foi, e nenhum número oficial muda. A sensibilidade (conta que reproduz exatamente os F1 oficiais, sem os pontos-fantasma) dá LSTM 0,481 e IF 0,476: a escolha do B não muda. Registrado no item 9 e no item 16 de `DECISOES_METODO.md`, e em `FASE1_EXPLICADA.md`.
- **Fase 3:** o `bin/experiment.sh` espera até início + `DURATION` + 15 s antes de exportar e de rodar o `hpa_metrics.py`, para o `pod_seconds` e o CSV só terem dado medido. A Fase 3 passa de ~32 h para ~35 h. Atualizados `COMANDOS.md`, `RUNBOOK_VPS_VPN.md`, `HPA.md`, `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md` e regras do projeto.

## Novo (29/out): drift e shift decididos antes da Fase 3

- `docs/DECISOES_METODO.md`, itens 14 e 15, e item 9 (ameaças), decididos depois da Fase 1, só com dados de ambiente:
  - **14, drift:** na Fase 1 a latência da fase normal subiu de 2 a 5 vezes da madrugada ao meio-dia. Fica mantido o desenho em blocos sorteados; o p95 do aquecimento é registrado e o equilíbrio entre A, B e C é mostrado antes do tempo de reação.
  - **15, shift:** o shift começou com 3–7 réplicas. Ele é mantido, e o tempo de reação conta só as janelas com reação, com as janelas sem reação e as réplicas iniciais ao lado. É o que o `hpa_metrics.py` já calcula.
- `bin/experiment.sh`: nova coluna `warmup_p95_ms` no `results/warmup_log.csv`. É o p95 da latência nos últimos 4 min do aquecimento, lido antes do modo, e aparece também no log do fim do aquecimento. Os itens por pod e o p95 saem numa só chamada ao Prometheus, para caber na margem antes da troca. O `warmup_log.csv` no formato anterior (o da Fase 1) é guardado à parte como `warmup_log.antigo.<data>.csv` na 1ª execução seguinte.
- Atualizados `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md`, `HPA.md`, `DETECTOR_ONLINE.md` e regras do projeto.
- **Novo `docs/FASE1_EXPLICADA.md`:** a Fase 1 definitiva explicada de forma didática (receita, placar, regra do B, offline × online, achados de ambiente, estatística passo a passo com o exemplo real LSTM × IF no burst, o que falta). As figuras ficam em `docs/figs/fase1/`, geradas dos CSVs reais.
- Item 9 (ameaças): novo achado. No rampup e no shift, o roteiro sobe a carga antes da 1ª anomalia do gabarito, e os detectores online alarmam em 57–99% desses pontos (5–19% no burst). Os pilotos que validaram "alertas iniciais perto de 0%" eram só de burst.

## Novo (29/out): modo D não usado

- `docs/DECISOES_METODO.md`, item 5: modo D fechado em 29/out/2026 (Ricardo), **não usado**. A Fase 3 roda A, B e C (`HPA_MODES=A,B,C`, o padrão; nada muda no código). Atualizados `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md`, `HPA.md`, regras do projeto.
- `RUNBOOK_VPS_VPN.md`: checklist da Fase 3 com cópia dos resultados da Fase 1, `DETECTOR_ALGOS` só com o detector do B, `HPA_MODES=A,B,C` e verificação do throttling.

## Novo (28/out): decisões de método fechadas antes da Fase 1

- `docs/DECISOES_METODO.md`: todas as decisões 1–13 **fechadas em 28/out/2026**, alinhadas com o orientador, antes da Fase 1 (inclusive 8: SLO 500 ms; 9: ameaças à validade; 10: IC t·S/√N; 13: ANOVA dispensada). Em aberto só o modo D, a decidir antes da Fase 3. Nenhuma mudança de método: o que estava adotado e implementado fica como está.
- Atualizados para o mesmo estado: `ESTADO_DO_PROJETO.md`, `EXPLICACAO.md`, `PILOTOS.md`, `DETECTOR_ONLINE.md`, regras do projeto.
- `RUNBOOK_VPS_VPN.md`: checklist com 19 testes no `selftest` e o `grep` do `.env` cobrindo `REPS`, `WARMUP_*`, `RESTART_APP` e `EVAL_*`.

## Novo (19/out): as duas famílias de comparação, lado a lado

- `DECISOES_METODO.md` (itens 1 e 2), `EXPLICACAO.md` (seção 9) e `ESTADO_DO_PROJETO.md`: tabela das duas famílias da Fase 1 — **da escolha** (vencedor online × outros online: "quem detecta melhor ao vivo?" → decide a Fase 3) e **offline × online** ("o desempenho muda ao vivo?" → achado da dissertação, não escolhe ninguém); por que as duas são pareadas (mesmas execuções; mesmo CSV) e a Fase 3 não; hipótese a confirmar ("escolher pelo offline pode levar à escolha errada"). Nomes que evitam confusão com os modos A/B.
- **Correção de atribuição:** "o online venceu em 4 de 5" e "AE 0,08 → 0,60" são do **piloto 1** (N = 1; 0,60 é o replay, 0,34 ao vivo), não do replay da qualificação, onde o online venceu em **13 de 18** combinações detector × cenário (não em todas). Corrigido em `DETECTOR_ONLINE.md`, `DECISOES_METODO.md`, `ESTADO_DO_PROJETO.md` e `EXPLICACAO.md`.

## Novo (18/out): explicação didática e offline × online sem "teto"

- **`docs/EXPLICACAO.md`** (novo): o projeto explicado para reunião e banca (lanchonete, fases, detectores, pilotos como investigação, regras de avaliação, estatística, regra do campeão, limitações, 6 frases-chave). Resumo: em divergência valem `DECISOES_METODO.md` e `PILOTOS.md`; o regras do projeto exige atualizá-lo junto com o `ESTADO_DO_PROJETO.md`.
- **Offline não é um limite superior do online:** `DETECTOR_ONLINE.md` (seção 4) ganhou a tabela "A régua de cada forma" (IF/LOF offline com cota fixa de 10% via `contamination`; AE/LSTM offline com régua contaminada pelos picos; online com μ + K·σ dos últimos 5 min, sem cota) e o texto "O offline não é um teto". A família offline × online mede o efeito de operar online e pode favorecer qualquer lado (registrado no item 2 de `DECISOES_METODO.md` e no `ESTADO_DO_PROJETO.md`); o runbook deixou de chamar o offline de "limite superior".

## Novo (18/out): estado do projeto e fechamento das decisões antes da Fase 1

- **`docs/ESTADO_DO_PROJETO.md`** (novo): resumo completo do que está feito, decidido e pendente (fases, infraestrutura, detectores, procedimento, estatística, decisões, pilotos, comandos, próximos passos). Link no README e no mapa do regras do projeto. É um resumo: em divergência valem `DECISOES_METODO.md` e `PILOTOS.md`; o regras do projeto passa a exigir que toda mudança de decisão ou piloto o atualize também.
- **DECISOES_METODO:** item 5 esclarece que na Fase 3 o detector roda **igual em A, B e C** e que o modo D precisa ser decidido antes (proposta: sai); novo item **12** (janela do detector fixa em 5 min, sensibilidade só por replay: parâmetro do detector ao vivo, não pode mudar depois da Fase 1); novo item **13** (proposta: ANOVA dispensada, porque as comparações são planejadas); item 11 registra que a base do EWMA offline inclui a oscilação da troca.
- **Correções de texto:** retreino do LSTM como hipótese **improvável, não descartada**; alertas iniciais do piloto 4 em B e C = 0–30% (o EWMA do B teve 0).

## Novo (18/out): comparações planejadas e tolerância de 30 s (decisões 2 e 6)

- **Só as comparações planejadas** (decisão 2; `planned_pairs` e `rule_b_ranking` em `stats_tlc.py`): por cenário, 6 offline × online do mesmo detector e 5 do **vencedor da regra do B** × outros online; o vencedor é o 1º pela média das 3 médias do F1 online, **o mesmo nos 3 cenários**. As 66 comparações de todos os pares não são mais geradas (nem como anexo). O relatório mostra o ranking da regra do B e aplica o desempate (menor MTTD online); nova aba `5_regra_B_ranking`; coluna `familia` nos testes.
- **Tolerância de 30 s** (antes 15 s), **offline e online** no relatório (antes só online). Medição em dados de piloto e da qualificação (nunca da Fase 1): transbordo no replay da qualificação p90 25 s (só sinais); ao vivo no piloto 4, mediana 10–25 s e p90 ~30 s em EWMA/IF; cauda de 72–100 s só nos multivariados (estado do sistema após o escalonamento, não atraso). 30 s = janela dos sinais (`rate[30s]`). Ver `DECISOES_METODO.md`, item 6.
- **Regra do B esclarecida e aplicada pelo relatório** (`rule_b_choice`): **grupo de empate** = o 1º + todos sem diferença significativa para ele em nenhum cenário; dentro do grupo vence o menor MTTD online. **MTTD:** janelas não detectadas ficam fora da média (já era assim); novas colunas `windows_detected`/`windows_total` em `detection_results.csv` e "janelas detectadas" ao lado do MTTD no ranking. Requisito do ciclo verificado pelo pod (0,48 s com os 6).
- **`make selftest`:** `test_planned_pairs`, `test_rule_b_tie_group` e `test_count_windows`. Agora 19 testes.

## Novo (18/out): teste pareado na Fase 1 e tolerância de atraso (decisões 1 e 6)

**Por quê.** As decisões 1 e 6 de [DECISOES_METODO.md](DECISOES_METODO.md) foram adotadas em 16/out (aguardando o orientador) e precisavam estar implementadas antes da Fase 1.

- **Teste pareado na Fase 1** (`paired_test` em `stats_tlc.py`): detectores e formas (offline, online) saem das mesmas execuções; cada par é comparado execução a execução, d = Y_A − Y_B, IC 95% de d̄ = d̄ ± t(0,975; N−1)·S_d/√N, t = d̄/(S_d/√N), gl = N − 1, p bilateral. O `pairwise` alinha A e B pela execução (`_rep`). O relatório mostra N, a diferença, o IC da diferença, t, gl, p. A **Fase 3 continua com o t não pareado** [AR 66] e o teste visual [AR 64]. Novas colunas nas tabelas de testes: `metodo`, `n`, `IC_dif_inf`, `IC_dif_sup`.
- **Tolerância de atraso, métrica secundária** (`tolerance_mask` em `detectors.py`, `EVAL_TOLERANCE_SECONDS`, padrão 15 s; 0 = sem): `f1_tol`, `precision_tol` e `recall_tol` ignoram os pontos normais até 15 s depois do fim de cada janela anômala (alerta online que transborda pelo atraso do pipeline). O F1 principal continua sem tolerância. O relatório da Fase 1 mostra o F1 online com tolerância numa seção própria. Valor a confirmar com o orientador.
- **`make selftest`:** `test_paired_test` e `test_eval_tolerance`. Agora 16 testes.
- **Regressão:** com `EVAL_SKIP_SECONDS=0` e `EVAL_TOLERANCE_SECONDS=0`, as métricas principais nos 9 CSVs da qualificação são idênticas ao `results_qualificacao/detection_results.csv` (45/45) e `f1_tol` = `f1` (54/54); com 15 s, `f1_tol` ≥ `f1` em todas (54/54), como esperado.

## Novo (16/out, depois do piloto 4): acomodação inicial da avaliação

**Por quê.** No piloto 4 ([PILOTOS.md](PILOTOS.md)), a latência oscilou logo após a troca aquecimento → roteiro nas **3 execuções**, no mesmo trecho (A 20–35 s, B 30–50 s, C 15–35 s), com a taxa de requisições subindo 8–14% entre 10 e 35 s: um efeito **sistemático do procedimento**, que fazia os multivariados alarmarem. Um 2º tipo de oscilação, num pod só e em instantes irregulares (até 240 ms), é ruído do ambiente, igual para todos os detectores, e não é tratado. Decisão do Ricardo em 16/out/2026, antes da Fase 1 (pré-registro; [DECISOES_METODO.md](DECISOES_METODO.md), item 11).

- **`EVAL_SKIP_SECONDS`** (padrão 60; 0 = avaliação antiga): na avaliação da Fase 1, offline **e** online, os pontos com `offset_seconds` < 60 s não entram em F1, precisão, recall e MTTD. Os detectores continuam rodando sobre a série inteira; só a pontuação ignora o trecho (`eval_mask` em `detectors.py`; a coluna `eval_skip_s` registra o valor em `detection_results.csv`). Vale também no `make online-replay`.
- **Nenhum pico é cortado:** a 1ª anomalia de `ANOMALY_PHASES` começa aos 150 s (burst, shift) e 175 s (rampup); o `detectors.py` avisa se algum ponto do gabarito cair antes do corte. Gabarito, roteiros k6, parâmetros dos detectores, `datasets_qualificacao/` e `results_qualificacao/` inalterados.
- **Fase 3 sem mudança:** `hpa_metrics.py` olha os picos e os scale-ups; nenhuma métrica do HPA pontua alertas no trecho inicial.
- **`make check-inicio`:** cada célula mostra as duas partes do trecho, [0, 60) s (acomodação) e [60 s, 1ª anomalia) (conta na avaliação), para separar a troca do ruído.
- **`make selftest`:** `test_eval_skip` (fora da pontuação, nenhum pico cortado, 0 s = avaliação antiga) e `test_check_inicio` com as duas partes. Agora 14 testes.
- **Regressão:** com `EVAL_SKIP_SECONDS=0`, o offline nos 9 CSVs da qualificação é idêntico ao `results_qualificacao/detection_results.csv` (45/45) e o LSTM offline idêntico à validação dele (9/9); o replay online é idêntico à validação do piso nas entradas (54/54); com 60 s, os pontos anômalos avaliados são os mesmos (54/54).
- **Decisões de método:** `docs/DECISOES_METODO.md` (antes `DECISOES_METODOS_ABERTAS.md`, não versionado) passa a ser a fonte única, com link no README e no regras do projeto; os itens 1, 3, 4, 5 e 6 marcados como adotados em 16/out/2026 (aguardando o orientador; 1 e 6 com implementação pendente).

## Corrigido

| Problema | Efeito | Correção |
|---|---|---|
| `uvicorn --workers 2` com `prometheus_client` sem modo multiprocesso | cada scrape lia um worker diferente: contadores "voltavam", `rate()` via resets falsos | 1 worker por pod (`UVICORN_WORKERS=1`); escala horizontal fica com o HPA |
| `make client-experiment` dependia de `make up` | no notebook, criava um cluster **local** em vez de usar a VPS | `ROLE=client` nunca cria cluster; `ensure-cluster` faz `vpn-check` |
| Usuário fora do grupo `docker` (Docker só com `sudo`) | `setup.sh` e `make` diziam "daemon não está rodando", com o daemon de pé | a checagem distingue *permission denied* e orienta `usermod -aG docker` + novo login (nunca `sudo make`) |
| Teste da VPN no runbook (`sort \| uniq -c \| head`) | agrupava código+tempo: cada linha aparecia 1×, o `head` mostrava só as 10 mais lentas e escondia as falhas `000` | conta os códigos HTTP à parte e imprime min/mediana/p95/max dos tempos |
| `make test-*` seguido de outro `make test-*` | 2º teste falhava com "Operation not permitted": o `chmod -R 777 results` tentava mudar o resumo do k6 anterior, que pertence ao usuário do container (uid 12345); só o `make clean` destravava | `chmod` só nas pastas `results` e `results/k6`, sem `-R` e tolerante a erro (como o `prep_dirs`) |
| Estatística com N=1 (`make experiment-quick`, degustação da Fase 3) | `stats_tlc.py` quebrava com `AttributeError: ... no attribute 'metrica'`: sem teste t possível, a tabela de pares saía sem colunas | a tabela vazia mantém as colunas e o relatório avisa "é preciso N ≥ 2"; IC e figuras seguem saindo; `make selftest` ganhou `test_pairwise_n1` para o caso não voltar |
| `make build-analysis` com o cluster de pé | a importação no k3d falhava em silêncio (`>/dev/null \|\| true`) e o pod do detector seguia com a imagem antiga (sem `piso_σ` no log), enquanto o `selftest`, que usa a imagem do Docker, passava | importa com erro visível (falha → `exit 1`) e reinicia o `online-detector` (`rollout restart`), que só pega a imagem nova num pod novo |
| `make clean` / `make purge` com resultados da análise | "Permission denied": as pastas `results/stats/phase*` são criadas pelo container de análise (uid 10001) e o usuário do host não apaga o que está dentro delas | se o `rm` comum falha, apaga pelo container de análise como root, só em `datasets/`, `datasets_hpa/` e `results/`; recria os `.gitkeep`; o `purge` apaga os dados antes de remover as imagens |
| Portas do k3d em `0.0.0.0` | na VPS, app, Prometheus e Grafana (anônimo) ficavam expostos na internet | `BIND_ADDR` no `.env` (IP da VPN) |
| `handleSummary` gravava em `results/…` relativo, sem volume montado | summary por execução perdido; sem p95 por execução para o IC | `SUMMARY_FILE` por execução em `/results/k6/` |
| 3 repetições fixas no Makefile | não escalava para 10 | `REPS` no `.env` |
| `scripts/run_experiment.sh` exigia k6 e Python no host | violava "tudo em container" | removido; substituído por `bin/experiment.sh` |
| Senha do Grafana fixa no manifest | — | vem do `.env` (`GRAFANA_ADMIN_PASSWORD`) |
| `make kubeconfig` sem k3d ou sem cluster | mostrava "✓" e gerava `kubeconfig-vpn.yaml` **vazio** (o erro do k3d se perdia no pipe) | confere k3d e cluster antes; gera num arquivo temporário e só aceita se o `server:` estiver certo |
| root do AlmaLinux sem `/usr/local/bin` no `PATH` | o instalador do k3d instalava, mas acusava falha; o `make` não achava o k3d | `setup.sh` acrescenta o caminho e avisa como deixar permanente |
| `run_k6 … \|\| true` | execução com k6 interrompido era marcada como concluída | ver "Execução inválida" acima |

## Mantido de propósito

- **Lacunas do Prometheus (NaN) tratadas como 0** (`IMPUTE=zero`), igual à qualificação, para manter a comparabilidade. `IMPUTE=ffill` está disponível. O rampup tem cerca de 36 lacunas por CSV.
- **Ground truth** (`ANOMALY_PHASES` no `export_metrics.py`) e roteiros k6 sem alteração.
- **Parâmetros de EWMA, IF e LOF** idênticos aos da qualificação.

## Não testado aqui

Este ambiente de desenvolvimento não tem acesso a registries de imagens. Por isso:

- **O que foi validado:**
  - manifests: kubeconform strict contra Kubernetes 1.30.4, 34 recursos, 0 erros;
  - scripts: shellcheck;
  - Makefile: dry-run;
  - código Python: `selftest`, replay com os CSVs reais e Prometheus simulado para o `hpa_metrics.py`.
- **O que não foi executado:** o cluster em si (pull das imagens, Adapter registrando a API, HPA lendo a métrica externa) e a fixação de núcleos (`make cpu-pin`) num cluster real. O primeiro `make up` real é o teste disso. Siga `make status`, `make phase2-check` e o `docker inspect` do runbook para conferir os núcleos.
