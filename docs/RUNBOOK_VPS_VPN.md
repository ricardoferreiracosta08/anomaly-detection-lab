# Runbook: experimento na VPS (+ notebook pela VPN)

## TL;DR

**Na VPS** (topologia A, recomendada). Faça na ordem; cada passo só depois do anterior dar certo.

**1. Uma vez só: Docker sem `sudo`**

```bash
docker ps                                # funcionou sem sudo? pule para o passo 2
sudo usermod -aG docker $USER            # põe seu usuário no grupo docker
exit                                     # sai do SSH e entra de novo (o grupo só vale num login novo)
docker ps                                # agora tem que funcionar sem sudo
```

Daqui em diante, **nunca** use `sudo` com `./setup.sh` ou `make`: os arquivos ficariam com dono root.

**2. Configurar e subir o cluster**

```bash
cp .env.example .env                     # só na primeira vez
# edite o .env: ROLE=server  CLUSTER_HOST=<IP_DA_VPN>  BIND_ADDR=<IP_DA_VPN>  CLUSTER_CPUS=0-5  LOADGEN_CPUS=6-7
#               GRAFANA_ADMIN_PASSWORD=<troque>   HPA_B_DETECTOR=<fixe depois da Fase 1>
./setup.sh && make server-up && make status
tmux new -A -s exp                       # cria a sessão ou volta a ela (caiu o SSH? rode de novo)
```

**3. Degustação: confere tudo em ≈ 1 h 15, antes das rodadas longas**

Rode na ordem, dentro do tmux. Cada linha diz o que conferir antes de seguir.

```bash
make selftest            # ≈ 40 s, sem cluster.  Confira: "Ran 9 tests ... OK"
make status              # segundos.            Confira: pods Running; HPA com TARGETS preenchido
make experiment-quick    # ≈ 20 min (com o aquecimento de 330 s). Fase 1 com 1 burst.  Confira: termina sem erro e gera results/stats/phase1/relatorio.md
make online-replay CSV=datasets/burst_run1.csv   # poucos min. O mesmo burst no detector online, sem o atraso do cluster
make hpa-mode HPA_MODE=B && make phase2-check   # segundos. Confira: um valor de anomaly_level E, na seção Metrics do HPA, a linha da métrica externa (só aparece no modo B)
make hpa-experiment REPS=1 SCENARIOS=burst HPA_MODES=A,B   # ≈ 40 min. Fase 3: burst no modo A e no B
#                                               Confira: results/hpa/hpa_results.csv com 2 linhas (A e B)
make check-inicio DIR=datasets_hpa   # segundos. Confira: alertas antes da 1ª anomalia perto de 0% (eram 53–87% sem aquecimento)
```

| | Fase 1 (offline) | Detector online detecta | HPA escala pela anomalia |
|---|---|---|---|
| `make experiment-quick` | ✓ | ✓ (`EWMA_online`, `IF_online`…) | ✗ (modo A, só CPU) |
| `make hpa-experiment REPS=1 …` | — | ✓ | ✓ (modo B) |

Como ler a degustação:

- **Só prova que o caminho funciona.** Com N = 1, o relatório mostra a média e "—" em DP, IC e Shapiro, e avisa que não há teste t. É o esperado. Os números **não** valem para a dissertação.
- **Online abaixo do offline é esperado.** O offline vê a execução inteira (limite superior); o online só vê o passado e chega com atraso (consulta ao Prometheus + publicação + novo scrape). O online tende a trocar precisão por recall.
- **O replay separa as causas.** Compare o F1 do `online-replay` com o `<DET>_online` do `experiment-quick`: se o replay ficar bem acima, a perda vem do atraso do cluster, não dos detectores. Referência da qualificação (replay, burst, média de 3): AE 0,61 · DBSCAN 0,60 · IF 0,46 · LOF 0,39 · EWMA 0,34.
- **Decida antes da rodada longa, com o orientador:** se o online será avaliado com tolerância de atraso ou não. Não decida depois de ver os resultados finais, e não reajuste o K (`DETECTOR_K_SIGMA`) olhando a Fase 1 definitiva.

**Antes da rodada longa, passe pelo [Checklist antes do experimento definitivo](#checklist-antes-do-experimento-definitivo).** Ele inclui apagar a degustação (senão o `make experiment` a conta como repetição 1 e a pula):

```bash
make clean                               # apaga datasets/, datasets_hpa/ e results/; preserva os dados da qualificação
```

**4. Rodadas longas (dentro do tmux), só depois do [checklist](#checklist-antes-do-experimento-definitivo)**

```bash
make experiment                          # Fase 1 (≈ 11 h: 8 h + 2,75 h de aquecimento): 5 detectores × 3 cargas × 10
#   → escolher o detector em results/stats/phase1/relatorio.md e fixar HPA_B_DETECTOR no .env
make hpa-mode HPA_MODE=B && make phase2-check   # o B recebe a anomalia? (o hpa-experiment troca o modo sozinho a cada execução)
make hpa-experiment                      # Fase 3 (≈ 32 h: 24 h + 8,25 h de aquecimento): HPA A × B × C × 3 cargas × 10
```

**No notebook:** Grafana em `http://<IP_DA_VPN>:5090`. No fim: `scp -r <usuario>@<IP_DA_VPN>:~/anomaly-detection-lab/results .`

Caiu algo? Rode o mesmo comando de novo: execuções concluídas são puladas, as interrompidas são refeitas.

Detalhes do HPA (modos, por que existe o C, métricas e estatística): [HPA.md](HPA.md).

---

## Checklist antes do experimento definitivo

Marque cada item **antes** do `make experiment` definitivo. Nenhum dado de piloto pode entrar nos resultados ([PILOTOS.md](PILOTOS.md)).

**Antes da Fase 1:**

- [ ] **Pilotos limpos:** `make clean` (apaga `datasets/`, `datasets_hpa/` e `results/`; preserva `datasets_qualificacao/` e `results_qualificacao/`). Os pilotos ficam registrados em `docs/PILOTOS.md`.
- [ ] **`.env` final:** `WARMUP_SECONDS` > 0 (padrão 330) e `DETECTOR_SIGMA_FLOOR=0.05` (decidido em 16/out; ver `docs/CHANGELOG.md`). Conferir com `grep -E '^(WARMUP_SECONDS|DETECTOR_)' .env`.
- [ ] **Imagem e detector com a configuração final:** `make build-analysis && make detector-deploy`, e `make detector-logs` mostra `piso_σ=<valor decidido>` na linha de partida.
- [ ] **`make selftest` passando** (9 testes, OK).
- [ ] **Último piloto dentro do critério:** `make check-inicio` (ou `DIR=datasets_hpa`) com alertas antes da 1ª anomalia perto de 0% — rodar **antes** do `make clean`, que apaga os CSVs.
- [ ] **VPS sem carga anormal nos outros serviços:** `uptime` (load average baixo para o número de núcleos) e `docker stats --no-stream` sem container fora do lab consumindo CPU nos núcleos do cluster.

**Antes da Fase 3 (além dos itens acima, exceto o `make clean`, que apagaria a Fase 1):**

- [ ] **`HPA_B_DETECTOR` escolhido pela Fase 1 e registrado** (no `.env`, no `docs/CHANGELOG.md` e no regras do projeto, com o motivo). Não trocar depois ([HPA.md](HPA.md), seção 3).
- [ ] **`make hpa-mode HPA_MODE=B && make phase2-check` ok:** `anomaly_level` aparece no Adapter e na seção Metrics do HPA.

---

## Topologias

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
r=$(for i in $(seq 100); do curl -o /dev/null -s -w '%{http_code} %{time_total}\n' --max-time 5 http://<IP_DA_VPN>:5070/health; done)
echo "$r" | cut -d' ' -f1 | sort | uniq -c          # quantas respostas por código HTTP
echo "$r" | awk '$1==200{print $2}' | sort -n | LC_ALL=C awk '{t[NR]=$1} END{if(NR) printf "tempo (s): min %.3f  mediana %.3f  p95 %.3f  max %.3f  (n=%d)\n",t[1],t[int((NR+1)/2)],t[int(NR*0.95)],t[NR],NR}'
```

Como ler: o ideal é `100 200`. Qualquer `000` (timeout) ou outro código é falha. Se o p95 passar de ~3× a mediana, a VPN oscila. Falhas ou oscilação: use a topologia A. Na topologia A a VPN só serve para ver o Grafana, então o resultado não afeta a medição.

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

**Fase 1** (cerca de 11 h com REPS=10: 8 h de execuções + 30 aquecimentos de 330 s ≈ 2,75 h):

```bash
tmux new -A -s exp         # cria ou volta à sessão. Ou: nohup make experiment > results/experiment.out 2>&1 &
make experiment            # Ctrl+B, depois D: sai sem parar. Nunca exit/Ctrl+C aqui (mata o make)
```

O `make experiment` chama o `make cpu-pin`, que fixa os nós do k3d nos núcleos `CLUSTER_CPUS`. O k6 e a análise rodam em `LOADGEN_CPUS`. Para conferir:

```bash
docker inspect -f '{{.Name}} {{.HostConfig.CpusetCpus}}' $(docker ps -q --filter label=k3d.cluster=anomaly-lab)
```

Todos devem mostrar `0-5`. O HPA mede a CPU em relação ao `request` de cada pod, não ao total da máquina, então a fixação não muda o significado de "CPU 50%".

**Entre as fases:** escolha o detector do modo B pelo F1 online em `results/stats/phase1/relatorio.md` e fixe `HPA_B_DETECTOR` no `.env`. Não troque depois (ver [HPA.md](HPA.md), seção 3).

**Fase 3** (cerca de 32 h com REPS=10: 24 h de execuções + 90 aquecimentos de 330 s ≈ 8,25 h): HPA A (CPU 50%), B (CPU + anomalia), C (CPU 35%, controle) × 3 cargas × `REPS`.

```bash
make hpa-mode HPA_MODE=B   # a métrica de anomalia só entra no HPA no modo B
make phase2-check          # anomaly_level precisa aparecer em external.metrics.k8s.io e na seção Metrics do HPA
make hpa-experiment        # também dentro do tmux/nohup
```

Resultado em `results/stats/phase3/relatorio.md`. O que cada modo e cada métrica significam está em [HPA.md](HPA.md).

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
make hpa-mode HPA_MODE=B && make phase2-check && make hpa-experiment     # Fase 3
```

Com `ROLE=client`, `make up` não cria cluster: só roda o `vpn-check`. Desligue a suspensão do notebook durante o experimento.

## 3. Garantias do experimento (as duas topologias)

- **Ordem aleatória:** os cenários (e os modos, na Fase 3) são sorteados em cada repetição, com semente fixa. O plano fica em `results/run_plan_phase{1,3}.csv`.
- **Condição inicial:** antes de cada execução, o script (na Fase 3, sempre com o HPA no modo A) espera o HPA voltar a 2 réplicas, aplica o `COOLDOWN` e roda o **aquecimento** (`WARMUP_SECONDS`, carga normal constante do cenário, sem CSV). Ao fim do aquecimento confere de novo as réplicas; se o HPA escalou, avisa no log e registra em `results/warmup_log.csv` (com o `anomaly_level` do detector do B). Só então aplica o modo da execução e começa o roteiro.
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
