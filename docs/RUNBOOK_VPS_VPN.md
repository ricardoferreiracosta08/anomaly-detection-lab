# Runbook: experimento na VPS (+ notebook pela VPN)

Há duas topologias. A **recomendada** roda tudo na VPS, inclusive o k6. O notebook só acompanha pelo Grafana, pela VPN.

| | A. Tudo na VPS (recomendada) | B. k6 no notebook |
|---|---|---|
| Onde roda o `make experiment` | VPS (`ROLE=server`) | notebook (`ROLE=client`) |
| CPU do k6 × cluster | separadas por núcleos fixos (`CLUSTER_CPUS` / `LOADGEN_CPUS`) | separadas por máquina |
| VPN na medição | não | sim: a latência da VPN entra no p95 do k6 e reduz a carga |
| Queda da VPN | não afeta o experimento | a execução em curso é invalidada e refeita |
| Quando usar | VPN instável (caso atual) | VPN estável, VPS com poucos núcleos |

```
A. Tudo na VPS                                  B. k6 no notebook
VPS (ROLE=server)                               Notebook (ROLE=client)        VPS (ROLE=server)
  núcleos 0-5: cluster k3d                        k6 ───── APP_PORT ────────▶  FastAPI
    (app, Prometheus, Grafana,                    export ─ PROM_PORT ───────▶  Prometheus
     detector online, adapter, HPA)               navegador GRAFANA_PORT ───▶  Grafana
  núcleos 6-7: k6 + análise                       kubectl  KUBE_API_PORT ───▶  API do Kubernetes
Notebook: só o navegador → Grafana pela VPN     todas as portas só no IP da VPN (BIND_ADDR)
```

## 0. VPN

Qualquer VPN que dê um IP fixo à VPS serve (OpenVPN, WireGuard, Tailscale). Nos exemplos abaixo, a VPS é `<IP_DA_VPN>`.

Antes de escolher a topologia, meça a VPN com TCP, que é o que o k6 usa (o `ping` pode enganar, porque muitas VPS limitam ICMP). Rode no notebook, com o cluster já de pé na VPS:

```bash
for i in $(seq 100); do curl -o /dev/null -s -w '%{http_code} %{time_total}\n' --max-time 5 http://<IP_DA_VPN>:5070/health; done | sort | uniq -c | sort -rn | head
```

Muitas falhas (`000`) ou tempos muito variáveis: use a topologia A.

## 1. VPS (as duas topologias)

```bash
git clone https://github.com/ricardoferreiracosta08/anomaly-detection-lab.git && cd anomaly-detection-lab
cp .env.example .env
```

No `.env` da VPS:

```
ROLE=server
CLUSTER_HOST=<IP_DA_VPN>      # IP da VPS na VPN
BIND_ADDR=<IP_DA_VPN>         # publica as portas só na VPN (NUNCA 0.0.0.0)
GRAFANA_ADMIN_PASSWORD=<troque>
# só na topologia A (ajuste ao nproc da VPS; exemplo para 8 núcleos):
CLUSTER_CPUS=0-5
LOADGEN_CPUS=6-7
```

O root no AlmaLinux às vezes não tem `/usr/local/bin` no `PATH`, onde ficam o k3d e o kubectl. Se for o caso, corrija uma vez:

```bash
echo 'export PATH=$PATH:/usr/local/bin' >> ~/.bashrc && source ~/.bashrc
```

```bash
./setup.sh                 # instala k3d/kubectl se faltar; gera k3d-config.yaml
make server-up             # cluster + imagens + todos os manifests
make status                # todos os pods Running; HPA com modo A
ss -ltnp | grep -E ':(5070|5080|5090|6550)\b'    # portas em <IP_DA_VPN>
```

## 2A. Topologia A: experimento na VPS

O experimento precisa sobreviver à queda do SSH: sem isso, o `make experiment` morre junto com a sessão. O cluster continua de pé, porque é do Docker, mas fica sem carga. Use `tmux` ou `nohup`.

**Fase 1** (cerca de 8 h com REPS=10):

```bash
tmux new -s exp            # ou: nohup make experiment > results/experiment.out 2>&1 &
make experiment            # Ctrl+B, depois D: sai sem parar; tmux attach -t exp: volta
```

O `make experiment` chama o `make cpu-pin`, que fixa os nós do k3d nos núcleos `CLUSTER_CPUS`. O k6 e a análise rodam em `LOADGEN_CPUS`. Para conferir:

```bash
docker inspect -f '{{.Name}} {{.HostConfig.CpusetCpus}}' $(docker ps -q --filter label=k3d.cluster=anomaly-lab)
```

Todos devem mostrar `0-5`. O HPA mede a CPU em relação ao `request` de cada pod, não ao total da máquina, então a fixação não muda o significado de "CPU 50%".

**Fase 3** (cerca de 24 h com REPS=10):

```bash
make phase2-check          # anomaly_level precisa aparecer em external.metrics.k8s.io
make hpa-experiment        # também dentro do tmux/nohup
```

**No notebook** (acompanhar): abra `http://<IP_DA_VPN>:5090`, dashboards "Anomaly Detection Lab" e "Detector Online & HPA". No fim, traga os resultados com `scp -r <usuario>@<IP_DA_VPN>:~/anomaly-detection-lab/results .`

Ameaça à validade, para registrar na dissertação: outros serviços da VPS (Traefik etc.) não ficam fixados em núcleos. Rode em horário de pouco uso deles.

## 2B. Topologia B: k6 no notebook

Na VPS, gere o acesso ao cluster:

```bash
make kubeconfig            # kubeconfig-vpn.yaml (server https://<IP_DA_VPN>:6550); falha alto se faltar k3d ou cluster
```

Copie para o notebook. Ele dá acesso total ao cluster: não versione nem compartilhe.

```bash
scp <usuario>@<IP_DA_VPN>:~/anomaly-detection-lab/kubeconfig-vpn.yaml .     # rodar no notebook
```

No `.env` do notebook:

```
ROLE=client
CLUSTER_HOST=<IP_DA_VPN>
KUBECONFIG_FILE=kubeconfig-vpn.yaml
CLUSTER_CPUS=
LOADGEN_CPUS=
```

```bash
./setup.sh                 # ROLE=client: não cria cluster
make build-analysis        # imagem de análise local (k6 vem pronto do Docker Hub)
make vpn-check             # app, Prometheus, Grafana, detector e kubectl pela VPN
make selftest
make experiment            # Fase 1
make phase2-check && make hpa-experiment     # Fase 3
```

Com `ROLE=client`, `make up` não cria cluster: só roda o `vpn-check`. Desligue a suspensão do notebook durante o experimento.

## 3. Garantias do experimento (as duas topologias)

- **Ordem aleatória:** os cenários (e os modos, na Fase 3) são sorteados em cada repetição, com semente fixa. O plano fica em `results/run_plan_phase{1,3}.csv`.
- **Condição inicial:** antes de cada execução, o script espera o HPA voltar a 2 réplicas e depois aplica o `COOLDOWN`.
- **Retomável:** as execuções concluídas ficam marcadas em `results/.done/` e são puladas. Se algo cair, rode o mesmo comando de novo.
- **Execução inválida:** se o k6 não terminar (sem resumo), a execução não é marcada e é refeita na próxima chamada.
- **Saídas:**
  - Fase 1: `datasets/*.csv`, `results/k6/*.json`, `results/detection_results.csv`, `results/k6_summary.csv`, `results/stats/phase1/`;
  - Fase 3: `results/hpa/hpa_results.csv`, `results/stats/phase3/`.

## Solução de problemas

### "Connection refused" no `vpn-check`, mas o `ping` responde

A VPN funciona, mas nada escuta nas portas da VPS. Na VPS:

```bash
command -v k3d docker kubectl
grep -E '^(ROLE|CLUSTER_HOST|BIND_ADDR)=' .env
k3d cluster list
ss -ltnp | grep -E ':(5070|5080|5090|6550)\b'
```

| Sintoma | Causa | Correção |
|---|---|---|
| `k3d: command not found` | `setup.sh` não rodou, ou `/usr/local/bin` fora do `PATH` do root | linha do `PATH` acima e `./setup.sh` |
| `k3d cluster list` vazio | o cluster nunca subiu | `make server-up` |
| portas em `127.0.0.1` | `BIND_ADDR` errado | ajustar o `.env`; `make down && make server-up` |
| portas no IP certo, mas recusadas | firewall | `iptables -L INPUT`; com firewalld: `firewall-cmd --permanent --zone=trusted --add-interface=<tun0> && firewall-cmd --reload` |

### Outros

| Sintoma | Causa provável | Ação |
|---|---|---|
| `vpn-check`: kubectl ✗ | kubeconfig ausente ou certificado sem o IP | na VPS: `make kubeconfig` (o `--tls-san` usa `CLUSTER_HOST`); se mudou `CLUSTER_HOST`: `make down && make server-up` |
| `make kubeconfig`: "✗ k3d não instalado" ou "✗ Cluster não existe" | cluster não está de pé nesta máquina | `make server-up` |
| `cpu-pin`: "✗ Cluster não está rodando" | `CLUSTER_CPUS` definido, cluster parado | `make server-up` |
| log "✗ … inválida (k6 sem resumo)" | k6 interrompido (queda, falta de memória) | nada: rode o mesmo comando de novo |
| `phase2-check` sem dados | adapter iniciando ou detector sem amostras | esperar cerca de 1 min; `make detector-logs`; `kubectl -n anomaly-lab logs deploy/prometheus-adapter` |
| HPA B nunca escala pela anomalia | `anomaly_level` baixo | Grafana › Detector Online & HPA; ajustar `DETECTOR_K_SIGMA` ou `ANOMALY_TARGET` e rodar `make detector-deploy` |
| "réplicas não voltaram ao mínimo" | scale-down lento (120 s + 1 pod/min) | normal com 8 réplicas; `BASELINE_TIMEOUT` controla a espera |
| cluster com portas erradas | `.env` mudou | `make down && make server-up` |
