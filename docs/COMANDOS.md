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
- os 5 detectores;
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
Reconstrói a imagem de análise, que contém os detectores, a estatística e o detector online, e a coloca no cluster.

### `make rebuild`
As duas anteriores, mais o reinício dos pods para usarem as imagens novas. Use depois de mudar código em `app/` ou `scripts/`.

---

## Testes de carga avulsos (sem análise)

### `make test-burst` / `make test-ramp` / `make test-shift`
Roda **uma** execução do cenário contra o cluster e salva o resumo do k6 em `results/k6/`. Serve para ver o sistema reagir, por exemplo com o Grafana aberto. Não gera CSV nem estatística.

---

## Fase 1: comparar os 5 detectores

### `make experiment`
O experimento completo:
1. Roda cada carga `REPS` vezes (padrão 10, ou seja, 30 execuções e cerca de 8 h). A ordem é sorteada a cada repetição e cada execução começa com o HPA de volta a 2 réplicas.
2. Salva 1 CSV por execução em `datasets/`.
3. Roda os 5 detectores em todos os CSVs.
4. Calcula a estatística.

Se for interrompido, rode de novo: as execuções já feitas são puladas.

### `make experiment-quick`
Uma única execução do burst, cerca de 14 min. Serve para testar se o pipeline inteiro funciona antes de deixar o experimento longo rodando.

### `make client-experiment`
Mesmo que `make experiment`. É o nome antigo, mantido.

### `make detect`
Só roda os 5 detectores sobre os CSVs que já estão em `datasets/` e gera `results/detection_results.csv`. Não roda carga nenhuma.

### `make k6-summary`
Junta os resumos do k6 de cada execução em `results/k6_summary.csv`: média, mediana, p90, p95, p99, requisições e erros, uma linha por execução.

### `make stats`
Calcula a estatística sobre os resultados que já existem e gera `results/stats/phase1/`:
- `relatorio.md`: resumo legível;
- `estatistica.xlsx`: uma aba por análise;
- figuras: IC do F1, box-plot e p95 do k6.

### `make analyze`
`detect` + `k6-summary` + `stats` de uma vez. É o que o `make experiment` chama no final.

---

## Fase 2: detector online

### `make online-replay CSV=<arquivo>`
Testa o detector online **sem cluster**, "re-assistindo" um CSV ponto a ponto, como se fosse ao vivo. Mostra precision, recall e F1 de cada detector e salva o detalhe ponto a ponto em `results/replay_<arquivo>.csv`. Exemplo:

```bash
make online-replay CSV=datasets_qualificacao/burst_run1.csv
```

### `make detector-deploy`
Reaplica o detector online no cluster com as configurações do `.env` (janela, K, algoritmos). Use depois de mudar `DETECTOR_*`. Se nada mudou, o pod não é reiniciado.

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
Confere se o HPA está recebendo a métrica de anomalia. Mostra o valor de `anomaly_level` que chega pelo Adapter e a seção de métricas do HPA. Use depois de `make hpa-mode HPA_MODE=B`.

---

## Fase 3: HPA A × B × C

### `make hpa-experiment`
Para cada repetição, roda as 3 cargas em cada modo de `HPA_MODES` (padrão A, B, C), ou seja, 9 execuções por repetição em ordem sorteada. Com REPS=10 são 90 execuções, cerca de 24 h. Gera:
- `results/hpa/hpa_results.csv`: tempo de reação, p95 nas anomalias, % acima de 500 ms, custo em pod·s, scale-ups falsos;
- a estatística em `results/stats/phase3/`.

É retomável, como a Fase 1.

### `make hpa-analyze`
Só recalcula a estatística da Fase 3 sobre os resultados existentes.

---

## VPS + notebook

### `make vpn-check` (no notebook)
Testa pela VPN, com ✓ ou ✗ para cada item:
- a aplicação;
- o Prometheus;
- o Grafana;
- se o detector online está publicando;
- se o kubectl alcança o cluster.

### `make kubeconfig` (na VPS)
Gera `kubeconfig-vpn.yaml`, o arquivo que deixa o notebook controlar o cluster da VPS (necessário para trocar o modo do HPA na Fase 3). Copie para o notebook e aponte `KUBECONFIG_FILE` no `.env` de lá.

---

## Limpeza

### `make clean`
Apaga os dados **gerados** (`datasets/`, `datasets_hpa/`, `results/`). Não apaga `datasets_qualificacao/` nem `results_qualificacao/`.

### `make purge`
Zera **tudo do lab** nesta máquina e pede confirmação antes. Remove:
- o cluster;
- as imagens Docker do lab (app, análise, k6, k3s, k3d);
- os dados gerados;
- os arquivos gerados (`k3d-config.yaml`, `kubeconfig-vpn.yaml`).

Remove também os binários k3d e kubectl de /usr/local/bin. Mantém o código, o .env e os dados da qualificação **Não** usa `docker system prune`: outros containers e imagens da máquina (por exemplo, os serviços que já rodam na VPS) não são tocados. Para não perguntar: `make purge CONFIRM=yes`. Depois, `make up` reconstrói tudo do zero.

| Comando | Cluster | Imagens | Dados gerados | Qualificação, .env, código |
|---|---|---|---|---|
| `make down` | apaga | mantém | mantém | mantém |
| `make clean` | mantém | mantém | apaga | mantém |
| `make purge` | apaga | apaga (só as do lab) | apaga | mantém |

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

**Experimento definitivo (VPS + notebook):** veja `docs/RUNBOOK_VPS_VPN.md`.
