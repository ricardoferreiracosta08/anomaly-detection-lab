# Runbook: experimento na VPS + notebook via VPN

Topologia: a VPS roda o cluster k3d (app, Prometheus, Grafana, detector online, adapter, HPA). O notebook gera a carga (k6) e faz a análise. Os dois conversam só pela VPN.

```
Notebook (ROLE=client)                       VPS (ROLE=server)
  k6 ─────────── APP_PORT ────────────────▶  FastAPI (NodePort 30080)
  export/hpa ─── PROM_PORT ───────────────▶  Prometheus
  navegador ──── GRAFANA_PORT ────────────▶  Grafana
  kubectl ────── KUBE_API_PORT (TLS) ─────▶  API do Kubernetes (troca de modo do HPA)
           todas as portas publicadas só no IP da VPN (BIND_ADDR)
```

## 0. VPN

Qualquer VPN que dê um IP fixo à VPS serve: WireGuard (ex.: VPS `10.0.0.1`, notebook `10.0.0.2`) ou Tailscale (`100.x.y.z`). Teste com `ping` nos dois sentidos antes de seguir.

## 1. VPS

```bash
git clone <repo> && cd anomaly-detection-lab      # ou descompacte o zip
cp .env.example .env
```

No `.env` da VPS:

```
ROLE=server
CLUSTER_HOST=10.0.0.1      # IP da VPS na VPN
BIND_ADDR=10.0.0.1         # publica as portas só na VPN (nunca 0.0.0.0)
```

```bash
./setup.sh                 # instala k3d/kubectl se faltar; gera k3d-config.yaml
make server-up             # cluster + imagens + todos os manifests
make status                # todos os pods Running; HPA com modo A
make kubeconfig            # gera kubeconfig-vpn.yaml (server https://10.0.0.1:6550)
```

Copie o kubeconfig para o notebook. Ele dá acesso total ao cluster; não versione nem compartilhe:

```bash
scp kubeconfig-vpn.yaml usuario@10.0.0.2:~/anomaly-detection-lab/
```

## 2. Notebook

No `.env` do notebook:

```
ROLE=client
CLUSTER_HOST=10.0.0.1
KUBECONFIG_FILE=kubeconfig-vpn.yaml
```

```bash
./setup.sh                 # ROLE=client: não cria cluster
make build-analysis        # imagem de análise local (k6 vem pronto do Docker Hub)
make vpn-check             # app, Prometheus, Grafana, detector e kubectl pela VPN
make selftest
```

No ROLE=client, `make up` não cria cluster nenhum: ele só roda o `vpn-check`.

## 3. Fase 1: comparação (cerca de 8 h com REPS=10)

```bash
make experiment
```

- **Ordem:** a ordem dos cenários é sorteada em cada repetição, com semente fixa. O plano fica em `results/run_plan_phase1.csv`.
- **Condição inicial:** antes de cada execução, o script espera o HPA voltar a 2 réplicas e depois aplica o `COOLDOWN`.
- **Retomável:** se a VPN cair ou o notebook dormir, rode `make experiment` de novo. As execuções concluídas (marcadas em `results/.done/`) são puladas.
- **Saídas:** `datasets/*.csv`, `results/k6/*.json`, `results/detection_results.csv`, `results/k6_summary.csv` e `results/stats/phase1/`.

## 4. Fase 3: HPA A × B × C (cerca de 24 h com REPS=10)

```bash
make phase2-check          # anomaly_level precisa aparecer em external.metrics.k8s.io
make hpa-experiment
```

Saídas: `results/hpa/hpa_results.csv` (1 linha por execução) e `results/stats/phase3/`.

## Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| `vpn-check`: App ✗ | VPN fora ou `BIND_ADDR` errado na VPS | `ping`; na VPS: `docker port k3d-anomaly-lab-serverlb` |
| `vpn-check`: kubectl ✗ | kubeconfig ausente ou certificado sem o IP | na VPS: `make kubeconfig` (o `--tls-san` usa `CLUSTER_HOST`); se mudou `CLUSTER_HOST`: `make down && make up` |
| `phase2-check` sem dados | adapter iniciando ou detector sem amostras | esperar cerca de 1 min (o detector precisa de 20 pontos); `make detector-logs`; `kubectl -n anomaly-lab logs deploy/prometheus-adapter` |
| HPA B nunca escala pela anomalia | `anomaly_level` baixo | Grafana › Detector Online & HPA; ajustar `DETECTOR_K_SIGMA` ou `ANOMALY_TARGET` e rodar `make detector-deploy` |
| "réplicas não voltaram ao mínimo" | scale-down lento (120 s + 1 pod/min) | normal com 8 réplicas; `BASELINE_TIMEOUT` controla a espera |
| Cluster com portas erradas | `.env` mudou | `make down && make up` |
