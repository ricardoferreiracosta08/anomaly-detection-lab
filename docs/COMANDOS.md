# Comandos `make`, um a um

Todos rodam da pasta do projeto e leem o `.env`. Qualquer comando pode ser rodado em qualquer ordem: se faltar algo (cluster, imagem, dados), ele resolve sozinho ou diz o que fazer.

Valores entre `<>` são exemplos. Qualquer variável do `.env` pode ser trocada só para aquele comando, por exemplo `make experiment REPS=3`.

---

## Primeiros passos

### `make help`
Mostra a lista resumida dos comandos e as configurações atuais: ROLE, CLUSTER_HOST, REPS e modo do HPA.

### `make setup`
Confere Docker, k3d e kubectl, e instala o que faltar. Também gera o `k3d-config.yaml` a partir do `.env`. Raramente é preciso chamar direto, porque o `make up` já chama.

### `make selftest`
Autoteste do código de análise, **sem cluster**, em cerca de 30 s. Confere:
- os 6 detectores (o LSTM inclusive: pico injetado, razão finita no online, determinismo);
- o detector online;
- o cálculo do IC (reproduz o slide 55);
- as métricas do HPA;
- a leitura dos resumos do k6.

Rode depois de qualquer mudança nos scripts.

---

## Cluster

### `make up`
Sobe **tudo** e deixa pronto para usar:
- o cluster k3d (só se ainda não existir);
- as duas imagens (app e análise);
- a aplicação FastAPI;
- Prometheus e Grafana;
- o kube-state-metrics;
- o detector online;
- o Prometheus Adapter;
- o HPA no modo do `.env` (`HPA_MODE`, padrão A).

Com `ROLE=client` ele não cria nada: só roda o `vpn-check`.

### `make server-up`
Igual ao `make up`. É o nome usado na VPS.

### `make deploy`
Reaplica só os manifests (app, monitoramento, detector, adapter, HPA), sem recriar o cluster. Use depois de editar algo em `k8s/`.

### `make status`
Mostra os pods, o HPA (com a coluna do modo) e o consumo de CPU e memória. É o primeiro comando a rodar quando algo parece errado.

### `make logs`
Logs da aplicação FastAPI em tempo real. `Ctrl+C` sai.

### `make down` / `make server-down`
Destrói o cluster. Os dados em `datasets/` e `results/` continuam. Não roda com `ROLE=client`.

---

## Imagens

### `make build`
Reconstrói a imagem da aplicação FastAPI e a coloca no cluster.

### `make build-analysis`
Reconstrói a imagem de análise, que contém os detectores, a estatística e o detector online, e a coloca no cluster. Com o cluster de pé, também **reinicia o pod do detector online**, porque ele só passa a usar a imagem nova num pod novo. Se a importação no cluster falhar, o comando para com erro (antes falhava em silêncio). Não rode durante um experimento.

### `make rebuild`
As duas anteriores, mais o reinício dos pods para usarem as imagens novas. Use depois de mudar código em `app/` ou `scripts/`.

---

## Testes de carga avulsos (sem análise)

### `make test-burst` / `make test-ramp` / `make test-shift`
Roda **uma** execução do cenário contra o cluster e salva o resumo do k6 em `results/k6/`. Serve para ver o sistema reagir, por exemplo com o Grafana aberto. Não gera CSV nem estatística.

---

## Fase 1: comparar os 6 detectores

### `make experiment`
O experimento completo:
1. Roda cada carga `REPS` vezes (padrão 10, ou seja, 30 execuções e cerca de 11 h, contando o aquecimento de `WARMUP_SECONDS` antes de cada uma). A ordem é sorteada a cada repetição e cada execução começa com a **app reiniciada** (estado limpo, 100 itens por pod) e o HPA de volta a 2 réplicas, depois do cooldown e de um **aquecimento** (`WARMUP_SECONDS`, padrão 330 s: carga normal constante do cenário, que não gera CSV), para a referência do detector online não ser feita de silêncio. O roteiro começa 30 s antes do fim do aquecimento, que desce enquanto ele sobe (carga constante na troca). Se o HPA escalar no aquecimento, o log avisa e fica registrado em `results/warmup_log.csv`.
2. Salva 1 CSV por execução em `datasets/`.
3. Roda os 6 detectores em todos os CSVs.
4. Calcula a estatística.

Se for interrompido, rode de novo: as execuções já feitas são puladas.

### `make experiment-quick`
Uma única execução do burst, cerca de 20 min (aquecimento incluído). Serve para testar se o pipeline inteiro funciona antes de deixar o experimento longo rodando. Inclui os alertas do detector online (avaliados como `EWMA_online`, `IF_online`…), mas o HPA fica no modo A: para ver o HPA escalar pela anomalia, use `make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B`. Rode `make clean` antes do experimento longo, senão este burst conta como repetição 1.

### `make client-experiment`
Mesmo que `make experiment`. É o nome antigo, mantido.

### `make detect`
Só roda os 6 detectores (e pontua os alertas `online_*`) sobre os CSVs que já estão em `datasets/` e gera `results/detection_results.csv`. Não roda carga nenhuma. A pontuação ignora os primeiros `EVAL_SKIP_SECONDS` (60) segundos de cada execução (acomodação; os detectores veem a série inteira); a coluna `eval_skip_s` registra o valor usado. Para a avaliação antiga: `make detect EVAL_SKIP_SECONDS=0`. A avaliação vai só até o **fim do roteiro k6 + `EVAL_END_MARGIN_SECONDS`** (15 s; burst 633, rampup 575, shift 925 s), porque depois disso o CSV não foi medido (decisão 17). A coluna `eval_end_s` registra o corte. `make detect EVAL_END_MARGIN_SECONDS=off` reproduz os números "como rodou" da Fase 1.

### `make k6-summary`
Junta os resumos do k6 de cada execução em `results/k6_summary.csv`: média, mediana, p90, p95, p99, requisições e erros, uma linha por execução.

### `make stats`
Calcula a estatística sobre os resultados que já existem e gera `results/stats/phase1/`:
- `relatorio.md`: resumo legível, com o IC do F1 por detector e cenário, o ranking da **regra do B**, **só as comparações planejadas** com teste pareado (offline × online do mesmo detector; vencedor da regra do B × outros online) e o F1 **com tolerância de atraso** (secundário, offline e online);
- `estatistica.xlsx`: uma aba por análise;
- figuras: IC do F1, box-plot e p95 do k6.

O `detection_results.csv` traz, além das métricas principais, `f1_tol`, `precision_tol` e `recall_tol` (tolerância de `EVAL_TOLERANCE_SECONDS`, 30 s, depois de cada pico; 0 = sem).

### `make analyze`
`detect` + `k6-summary` + `stats` de uma vez. É o que o `make experiment` chama no final.

---

## Fase 2: detector online

### `make online-replay CSV=<arquivo>`
Testa o detector online **sem cluster**, "re-assistindo" um CSV ponto a ponto, como se fosse ao vivo. Mostra precision, recall e F1 de cada detector e salva o detalhe ponto a ponto em `results/replay_<arquivo>.csv`. Exemplo:

```bash
make online-replay CSV=datasets_qualificacao/burst_run1.csv
```

Usa o `DETECTOR_SIGMA_FLOOR` e o `EVAL_SKIP_SECONDS` (acomodação de 60 s na pontuação) do `.env`; para comparar, troque só naquele comando: `make online-replay CSV=… DETECTOR_SIGMA_FLOOR=0` ou `… EVAL_SKIP_SECONDS=0`.

### `make check-inicio DIR=<pasta>`
Conta, em cada CSV da pasta (padrão `datasets`), quantos alertas `online_*` cada detector deu **antes da 1ª janela anômala** do cenário, mostrando "alertas / pontos". O início da 1ª janela vem do gabarito (`ANOMALY_PHASES`), não é fixo. Nesse trecho não há anomalia, então todo alerta é falso alarme. Use depois de um piloto:

```bash
make check-inicio                    # Fase 1 (datasets/)
make check-inicio DIR=datasets_hpa   # Fase 3
```

Cada célula mostra as duas partes do trecho, separadas em `EVAL_SKIP_SECONDS` (60 s): **[0, 60) s**, a acomodação após a troca aquecimento → roteiro, que fica fora da avaliação da Fase 1; e **[60 s, 1ª anomalia)**, ruído real que conta na avaliação. Assim dá para separar a troca do ruído.

Critério ([PILOTOS.md](PILOTOS.md)): perto de 0% (alguns alertas isolados são esperados com K = 2). No piloto 2, antes do aquecimento, era 53–87%. Não roda carga nem mexe no cluster.

### `make detector-ciclo MIN=<minutos>`
Mostra o **tempo de ciclo** do detector online no cluster (`detector_step_seconds`) nos últimos `MIN` minutos (padrão 70): média, p50, p95, p99 e a fração de ciclos acima de 1, 2 e 5 s. Mostra também a **CPU do pod** `online-detector` (média, p95 e máximo, em núcleos; limite 0,5), os reinícios do pod e o motivo do último término (por exemplo `OOMKilled`, falta de memória). O `make experiment` e o `make hpa-experiment` rodam este comando sozinhos no fim e salvam em `results/detector_ciclo_<fase>.txt`. O ciclo precisa ficar bem abaixo de `DETECTOR_STEP_SECONDS` (5 s); o comando marca ✓ se o p95 < 2,5 s. Rode logo depois de um piloto, com `MIN` cobrindo a duração dele. Os percentis vêm dos baldes do histograma (interpolados).

### `make detector-deploy`
Reaplica o detector online no cluster com as configurações do `.env` (janela, K, piso do σ, algoritmos). Use depois de mudar `DETECTOR_*`. Se nada mudou, o pod não é reiniciado.

### `make detector-config`
Só atualiza o ConfigMap do detector. O `detector-deploy` já chama este comando.

### `make detector-logs`
Logs do detector online em tempo real. Mostra erros de coleta e se ele está publicando.

### `make adapter-deploy`
Reaplica o Prometheus Adapter, a peça que entrega a métrica `anomaly_level` ao HPA.

### `make ksm-deploy`
Reaplica o kube-state-metrics, que coloca as réplicas do HPA e do Deployment no Prometheus.

---

## HPA

### `make hpa-mode HPA_MODE=<A|B|C|D>`
Troca o modo do HPA na hora, sem reiniciar nada:

| Modo | Decide por | Papel no experimento |
|---|---|---|
| A | CPU > 50% | atual, referência |
| B | CPU > 50% **ou** anomalia (detector `HPA_B_DETECTOR`, padrão IF) | o HPA proativo |
| C | CPU > 35% | controle: só "ligar pods mais cedo" |
| D | CPU > 50% **ou** anomalia do detector `HPA_D_DETECTOR` (padrão EWMA) | opcional: um 2º detector no HPA, para comparar com o B. Só roda se você colocar D em `HPA_MODES` |

### `make hpa-status`
Mostra o HPA atual: modo, métricas, réplicas atuais e desejadas.

### `make phase2-check`
Confere se o HPA está recebendo a métrica de anomalia. Mostra o valor de `anomaly_level` que chega pelo Adapter e a seção de métricas do HPA. Use depois de `make hpa-mode HPA_MODE=B`. Em outro modo, a 1ª parte (o valor pelo Adapter) aparece, mas a seção do HPA só mostra CPU: por isso o comando completo é `make hpa-mode HPA_MODE=B && make phase2-check`. Deixar o HPA no B não atrapalha o `make hpa-experiment`, que aplica o modo certo antes de cada execução.

---

## Fase 3: HPA A × B × C

### `make hpa-experiment`
Para cada repetição, roda as 3 cargas em cada modo de `HPA_MODES` (padrão A, B, C), ou seja, 9 execuções por repetição em ordem sorteada. Com REPS=10 são 90 execuções, cerca de 35 h (24 h de carga + 8,25 h de aquecimento + ~2,7 h esperando o fim da janela medida, decisão 16). Antes de cada execução, a espera pelas 2 réplicas, o cooldown e o aquecimento rodam sempre com o HPA no **modo A**; o modo da execução só é aplicado logo antes do roteiro, para todas começarem com 2 réplicas ([HPA.md](HPA.md), seção 4). Gera:
- `results/hpa/hpa_results.csv`: tempo de reação, p95 nas anomalias, % acima de 500 ms, custo em pod·s, scale-ups falsos;
- a estatística em `results/stats/phase3/`.

É retomável, como a Fase 1.

### `make hpa-analyze`
Só recalcula a estatística da Fase 3 sobre os resultados existentes.

---

## Administração pela CLI (`kubectl` e `k3d`)

Os `make status`, `make logs`, `make detector-logs` e `make hpa-status` já cobrem o dia a dia. Para ir além, use o `kubectl` direto. Tudo do lab fica no namespace `anomaly-lab` (`NAMESPACE` no `.env`).

Rode como o mesmo usuário que fez o `make up`/`make server-up`: o kubeconfig fica no `~/.kube` dele. No notebook, pela VPN, vale o kubeconfig do `make kubeconfig`.

| Comando | Para quê |
|---|---|
| `kubectl get nodes -o wide` | nós do k3d de pé? |
| `kubectl -n anomaly-lab get all` | visão geral do lab |
| `kubectl -n anomaly-lab get pods -w` | pods ao vivo (criação e remoção) |
| `kubectl -n anomaly-lab get hpa fastapi-hpa -w` | decisões do HPA ao vivo (CPU e `anomaly_level`) |
| `kubectl -n anomaly-lab describe hpa fastapi-hpa` | eventos do HPA: por que escalou ou não |
| `kubectl -n anomaly-lab top pods` / `kubectl top nodes` | CPU e memória por pod / por nó |
| `kubectl -n anomaly-lab describe pod <pod>` | pod em `Pending` ou `CrashLoopBackOff`: veja "Events" |
| `kubectl -n anomaly-lab logs <pod> --previous` | log do container que caiu |
| `kubectl -n anomaly-lab get events --sort-by=.lastTimestamp \| tail -20` | últimos eventos do namespace |
| `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/anomaly-lab/anomaly_level"` | o valor de anomalia que o HPA enxerga (via Prometheus Adapter) |
| `k3d cluster list` / `k3d node list` | o cluster e seus containers |

Só leitura. Para mudar o estado (HPA, detector, cluster) use os alvos `make`: eles mantêm tudo idempotente e alinhado ao `.env`. Um `kubectl edit`/`scale` manual durante o experimento invalida a execução.

---

## VPS + notebook

### `make vpn-check` (no notebook)
Testa pela VPN, com ✓ ou ✗ para cada item:
- a aplicação;
- o Prometheus;
- o Grafana;
- se o detector online está publicando;
- se o kubectl alcança o cluster.

### `make cpu-pin` (na VPS, topologia "tudo na VPS")
Fixa os nós do k3d nos núcleos `CLUSTER_CPUS`. O k6 e a análise rodam nos núcleos `LOADGEN_CPUS`, assim a carga não rouba CPU do cluster. Com as variáveis vazias, não faz nada. O `make experiment` e o `make hpa-experiment` já chamam este comando.

### `make kubeconfig` (na VPS)
Gera `kubeconfig-vpn.yaml`, o arquivo que deixa o notebook controlar o cluster da VPS (necessário para trocar o modo do HPA na Fase 3). Copie para o notebook e aponte `KUBECONFIG_FILE` no `.env` de lá.

---

## Limpeza

### `make clean`
Apaga os dados **gerados** (`datasets/`, `datasets_hpa/`, `results/`). Não apaga `datasets_qualificacao/` nem `results_qualificacao/`. Arquivos criados pelos containers (análise e k6) têm outro dono; se o seu usuário não conseguir apagá-los, o comando os apaga pelo container de análise, como root, só nessas três pastas. Sem `sudo`.

### `make purge`
Zera **tudo do lab** nesta máquina e pede confirmação antes. Remove:
- o cluster;
- as imagens Docker do lab (app, análise, k6, k3s, k3d);
- os dados gerados;
- os arquivos gerados (`k3d-config.yaml`, `kubeconfig-vpn.yaml`);
- os binários `k3d` e `kubectl` de `/usr/local/bin` (o `./setup.sh` reinstala).

Mantém o código, o `.env` e os dados da qualificação. **Não** usa `docker system prune`: outros containers e imagens da máquina (por exemplo, os serviços que já rodam na VPS) não são tocados. Para não perguntar: `make purge CONFIRM=yes`. Depois, `./setup.sh && make up` reconstrói tudo do zero.

| Comando | Cluster | Imagens | Dados gerados | Qualificação, .env, código |
|---|---|---|---|---|
| `make down` | apaga | mantém | mantém | mantém |
| `make clean` | mantém | mantém | apaga | mantém |
| `make purge` | apaga | apaga (só as do lab) e os binários k3d/kubectl | apaga | mantém |

---

## Sequências comuns

**Primeira vez, local:**
```bash
cp .env.example .env
make up && make selftest && make experiment-quick
```

**Ver o detector online ao vivo:** abra o Grafana (dashboard "Detector Online & HPA") e rode:
```bash
make test-burst
```

**Ver o HPA proativo agindo:**
```bash
make hpa-mode HPA_MODE=B
make phase2-check
make test-burst            # olhar "anomaly_level × réplicas" no Grafana
make hpa-mode HPA_MODE=A   # volta ao normal
```

**Experimento definitivo (VPS):** veja `docs/RUNBOOK_VPS_VPN.md`. Modos do HPA e Fase 3: `docs/HPA.md`.
