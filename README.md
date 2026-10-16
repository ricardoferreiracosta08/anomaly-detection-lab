# Anomaly Detection Lab — Kubernetes (100% Docker + IaC)

Detecção de anomalias em Kubernetes baseada em observabilidade contínua:
comparação experimental de 5 detectores (Fase 1), detector online no cluster (Fase 2)
e HPA proativo avaliado contra o HPA reativo (Fase 3).

**Dissertação de Mestrado — PPGCC/UFMA — Ricardo F. Costa — 2026**

## Pré-requisitos

Docker 24+. `./setup.sh` instala k3d e kubectl. k6, Python, scikit-learn e o detector online rodam em container.

## Início rápido (tudo local)

```bash
cp .env.example .env        # ROLE=local, CLUSTER_HOST=localhost
make up                     # cluster + app + Prometheus + Grafana + detector online + adapter + HPA (modo A)
make selftest               # autoteste do código de análise (sem cluster, ~30 s)
make experiment-quick       # 1 rodada burst + 5 detectores + estatística (~20 min)
```

Grafana em `http://localhost:5090`, com os dashboards **Anomaly Detection Lab** e **Detector Online & HPA**.

## Experimento definitivo: VPS (+ notebook pela VPN)

Duas topologias; a escolha depende da estabilidade da VPN.

| Topologia | Onde roda o `make experiment` | `.env` da VPS | `.env` do notebook |
|---|---|---|---|
| **A. Tudo na VPS** (recomendada) | VPS, dentro de `tmux`/`nohup` | `ROLE=server`, `CLUSTER_HOST` e `BIND_ADDR` = IP VPN da VPS, `CLUSTER_CPUS=0-5`, `LOADGEN_CPUS=6-7` | nenhum: só o navegador no Grafana |
| B. k6 no notebook | notebook | `ROLE=server`, `CLUSTER_HOST` e `BIND_ADDR` = IP VPN da VPS | `ROLE=client`, `CLUSTER_HOST` = IP VPN da VPS, `KUBECONFIG_FILE=kubeconfig-vpn.yaml` |

Na A, o k6 e o cluster ficam em núcleos de CPU separados (`make cpu-pin`, chamado pelo próprio `make experiment`) e a VPN fica fora da medição. Na B, a separação é por máquina, mas a latência da VPN entra no p95 do k6. Nas duas, uma execução em que o k6 não termina é marcada como inválida e refeita.

O passo a passo completo, com o teste da VPN e a solução de problemas, está em [docs/RUNBOOK_VPS_VPN.md](docs/RUNBOOK_VPS_VPN.md).

## As três fases

| Fase | O que faz | Comando | Saída |
|---|---|---|---|
| 1. Comparar | 3 cenários × `REPS` (10), ordem aleatória, 5 detectores offline | `make experiment` | `results/detection_results.csv`, `results/k6_summary.csv`, `results/stats/phase1/` |
| 2. Detector online | 5 detectores em janela deslizante no cluster, publicando `anomaly_score`, `anomaly_alert` e `anomaly_level` | `make up` (já incluso) | Prometheus/Grafana; colunas `online_<DET>` nos CSVs |
| 3. Avaliar o HPA | modos A, B e C × 3 cenários × `REPS` | `make hpa-experiment` | `results/hpa/hpa_results.csv`, `results/stats/phase3/` |

**Modos do HPA** (`make hpa-mode HPA_MODE=X`). Como o HPA decide, por que existe o modo C, as métricas e a estatística da Fase 3: **[docs/HPA.md](docs/HPA.md)**. Como o detector online funciona (Fase 2): **[docs/DETECTOR_ONLINE.md](docs/DETECTOR_ONLINE.md)**. O que cada painel do Grafana mostra e como ler: **[docs/GRAFANA.md](docs/GRAFANA.md)**.

| Modo | Métricas | Papel |
|---|---|---|
| A | CPU 50% | baseline (estado atual) |
| B | CPU 50% + `anomaly_level` do IF | tratamento (HPA proativo) |
| C | CPU 35% | controle de custo: ganho por detectar ou só por ligar mais pods? |
| D | CPU 50% + `anomaly_level` do EWMA | ablação opcional (univariado × multivariado) |

## Detectores

| Detector | Classe | Métricas | Decisão |
|---|---|---|---|
| EWMA | estatístico | 1 (latência p95) | média suavizada (λ=0,3) fora de μ ± 3σ |
| IF | isolamento | 4 | contamination = 0,1 |
| LOF | densidade local | 4 | n_neighbors = 20, contamination = 0,1 |
| DBSCAN | densidade global | 4 | ruído = anomalia; min_samples = 8, eps = P90 da k-distância |
| AE | reconstrução neural | 4 | MLP 4-3-2-3-4; erro > μ + 2σ |

• EWMA: Ele não sabe o que é uma falha. Ele só decora o ritmo normal da fila. Se o ritmo mudar de repente, ele desconfia.
• Isolation Forest (IF): Ele não sabe quem é o vilão. Ele só repara que algumas pessoas são tão diferentes que são fáceis de isolar com poucas perguntas.
• LOF: Ele só olha quem ficou no "vácuo", longe de qualquer grupinho de 20 pessoas.
• DBSCAN: Ele cria os grupos por proximidade física. Quem sobrou sozinho no escuro, do lado de fora dos círculos, vira anomalia.
• Autoencoder (AE): Você treina ele mostrando a festa rolando normalmente. Ele aprende a desenhar o "normal". Quando aparece algo diferente, ele erra o desenho porque nunca viu aquilo antes.

**Offline (Fase 1):** cada detector analisa o CSV inteiro da execução.

**Online (Fase 2):** a cada 5 s, cada detector é ajustado numa janela de referência de 60 pontos (5 min), que termina 30 s antes do ponto atual. O limiar é dinâmico: μ + K·σ dos scores da janela, com K = 2. Para testar sem cluster:

```bash
make online-replay CSV=datasets_qualificacao/burst_run1.csv
```

## Estatística

O pipeline segue o material da disciplina (Análise de Resultados, slides 49–66):

- **IC da média:** cada execução gera um valor Yi (F1, p95 do k6, tempo de reação…). Para cada célula, IC = Ȳ ± t(0,975; N−1)·S/√N. A forma t·S dos slides 52/55 também vai na tabela, na coluna `H_tDP`.
- **Comparação:** t de Student (slide 66), com o p-valor, mais o teste visual de sobreposição dos ICs (slide 64).
- **Diagnósticos:** Shapiro-Wilk por célula, como conferência da normalidade, e replicações necessárias para H/Ȳ ≤ 10% e ≤ 20% (slides 58–59).
- **Validação:** a planilha reproduz o exemplo do slide 55 (aba `0_validacao_slide55`).

## Dados da qualificação

`datasets_qualificacao/` guarda os 9 CSVs reais (3 × 3). `results_qualificacao/` guarda:

- `detection_results_3detectores.csv`: o resultado original da qualificação, com 27 avaliações;
- `detection_results.csv`: os mesmos 9 CSVs com os 5 detectores (45 avaliações). EWMA, IF e LOF são idênticos ao original;
- `online_replay_K2.csv`: os mesmos CSVs passados pelo detector online (replay);
- `stats_phase1/`: IC e testes para offline + online (N = 3; ilustra por que 10 repetições).

## Comandos

Cada `make` está explicado um a um em **[docs/COMANDOS.md](docs/COMANDOS.md)**. Resumo:

| Comando | O que faz |
|---|---|
| `make up` / `make down` | cria e destrói o cluster com tudo |
| `make deploy` | reaplica os manifests |
| `make status` | pods, HPA (com o modo) e consumo |
| `make experiment` / `make experiment-quick` | Fase 1 completa / 1 rodada |
| `make detect` / `make stats` / `make analyze` | detectores / estatística / ambos |
| `make hpa-experiment` / `make hpa-analyze` | Fase 3 |
| `make hpa-mode HPA_MODE=B` / `make phase2-check` | troca o modo / confere a métrica externa |
| `make detector-logs` / `make online-replay` | logs do detector / teste sem cluster |
| `make check-inicio DIR=datasets_hpa` | alertas online antes da 1ª anomalia (falsos alarmes do início) |
| `make vpn-check` / `make kubeconfig` | notebook → VPS / exporta o acesso da VPS (topologia B) |
| `make cpu-pin` | fixa o cluster em `CLUSTER_CPUS` (topologia A; o `make experiment` já chama) |
| `make selftest` | autoteste do código |
| `make clean` | apaga `datasets/`, `datasets_hpa/` e `results/` (preserva a qualificação) |
| `make purge` | zera o lab: cluster, imagens do lab, dados gerados e os binários k3d/kubectl (pede confirmação) |

## Estrutura

```
.env.example            configuração única (portas, papel, REPS, detector, HPA)
setup.sh                pré-requisitos + gera k3d-config.yaml do .env
Makefile                orquestrador idempotente
bin/experiment.sh       rodadas (Fase 1 e 3): ordem aleatória, condição inicial, aquecimento, retomável
bin/render.sh           substitui ${VAR} do .env nos manifests (sem envsubst/helm)
app/                    FastAPI (5 endpoints, 1 worker por pod)
k6-scripts/             burst, rampup, shift (+ summary por execução); warmup (aquecimento, fora da avaliação)
k8s/app/                Deployment + Service da aplicação
k8s/monitoring/         Prometheus, Grafana (2 dashboards), kube-state-metrics
k8s/detector/           detector online (template)
k8s/adapter/            Prometheus Adapter (métrica externa anomaly_level)
k8s/hpa/                hpa-cpu.yaml (modos A/C), hpa-anomaly.yaml (modos B/D)
scripts/                imagem de análise: detectors, online_detector, export_metrics,
                        k6_summary, hpa_metrics, stats_tlc, selftest
datasets_qualificacao/  9 CSVs reais da qualificação
results_qualificacao/   resultados da qualificação (3 e 5 detectores, online, estatística)
docs/                   runbook VPS+VPN, HPA (Fase 3), detector online, Grafana, pilotos, comandos, changelog, Git, READMEs anteriores
```

O que mudou em relação à versão anterior e por quê: [docs/CHANGELOG.md](docs/CHANGELOG.md).
Execuções de teste (pilotos) e as decisões que motivaram: [docs/PILOTOS.md](docs/PILOTOS.md). **Regra:** cada execução de teste relevante é registrada em `docs/PILOTOS.md`; os dados dos pilotos não entram nos resultados da dissertação.
Como enviar para o GitHub: [docs/GIT.md](docs/GIT.md).
