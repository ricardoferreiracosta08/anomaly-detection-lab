# Anomaly Detection Lab — Kubernetes

Avaliação experimental comparativa de detectores de anomalias (EWMA, Isolation Forest, LOF) em workloads Kubernetes.

**Dissertação de Mestrado — PPGCC/UFMA — Ricardo F. Costa — 2026**

## Pré-requisitos

- Docker 24+
- k3d e kubectl são instalados automaticamente por `./setup.sh`

## Início rápido

```bash
cp .env.example .env       # ajustar se necessário
./setup.sh                 # instala k3d/kubectl, gera k3d-config.yaml
make up                    # cria cluster, builda imagens, faz deploy
make experiment-quick      # 1 rodada burst + detecção (~14 min)
```

## Experimento completo (9 rodadas, ~2h25)

```bash
make experiment
```

Gera `datasets/*.csv` (9 CSVs anotados) e `results/detection_results.csv` (27 avaliações).

## Topologia distribuída (recomendada)
VPS:      make up              # cluster K3D
Notebook: make experiment CLUSTER_HOST=<IP_VPS_VPN>

## Comandos

| Comando | O que faz |
|---------|-----------|
| `make up` | Cluster + build + deploy |
| `make experiment` | 9 rodadas + detecção |
| `make experiment-quick` | 1 rodada burst + detecção |
| `make detect` | Detectores sobre datasets/ |
| `make status` | Pods e HPA |
| `make down` | Destrói cluster |
| `make clean` | Remove datasets/ e results/ |

## Estrutura
.env.example          # Template de configuração
setup.sh              # Pré-requisitos + gera k3d-config.yaml
Makefile              # Orquestrador idempotente
app/                  # FastAPI (5 endpoints) + Dockerfile
k8s/                  # Manifests K8s (deploy, prometheus, grafana)
k6-scripts/           # 3 cenários de carga (burst, rampup, shift)
scripts/              # export_metrics.py + detectors.py + Dockerfile
datasets/             # GERADO: 9 CSVs anotados
results/              # GERADO: detection_results.csv
