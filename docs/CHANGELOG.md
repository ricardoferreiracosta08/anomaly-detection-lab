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
