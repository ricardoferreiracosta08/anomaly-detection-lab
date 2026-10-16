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
  - `docs/RUNBOOK_VPS_VPN.md`: TL;DR em passos (Docker sem `sudo`, cluster, **degustação** de Fase 1 e Fase 3 em minutos, `make clean` antes da rodada longa);
  - `docs/RUNBOOK_VPS_VPN.md`: `tmux new -A -s exp` (o mesmo comando cria a sessão ou volta a ela depois de uma queda do SSH);
  - `docs/COMANDOS.md`: seção "Administração pela CLI" com os comandos `kubectl`/`k3d` de consulta;
  - `docs/RUNBOOK_VPS_VPN.md` reescrito: TL;DR no topo, topologias A e B, teste da VPN com `curl`, `tmux`/`nohup`, diagnóstico de "connection refused".

## Corrigido

| Problema | Efeito | Correção |
|---|---|---|
| `uvicorn --workers 2` com `prometheus_client` sem modo multiprocesso | cada scrape lia um worker diferente: contadores "voltavam", `rate()` via resets falsos | 1 worker por pod (`UVICORN_WORKERS=1`); escala horizontal fica com o HPA |
| `make client-experiment` dependia de `make up` | no notebook, criava um cluster **local** em vez de usar a VPS | `ROLE=client` nunca cria cluster; `ensure-cluster` faz `vpn-check` |
| Usuário fora do grupo `docker` (Docker só com `sudo`) | `setup.sh` e `make` diziam "daemon não está rodando", com o daemon de pé | a checagem distingue *permission denied* e orienta `usermod -aG docker` + novo login (nunca `sudo make`) |
| Teste da VPN no runbook (`sort \| uniq -c \| head`) | agrupava código+tempo: cada linha aparecia 1×, o `head` mostrava só as 10 mais lentas e escondia as falhas `000` | conta os códigos HTTP à parte e imprime min/mediana/p95/max dos tempos |
| `make test-*` seguido de outro `make test-*` | 2º teste falhava com "Operation not permitted": o `chmod -R 777 results` tentava mudar o resumo do k6 anterior, que pertence ao usuário do container (uid 12345); só o `make clean` destravava | `chmod` só nas pastas `results` e `results/k6`, sem `-R` e tolerante a erro (como o `prep_dirs`) |
| Estatística com N=1 (`make experiment-quick`, degustação da Fase 3) | `stats_tlc.py` quebrava com `AttributeError: ... no attribute 'metrica'`: sem teste t possível, a tabela de pares saía sem colunas | a tabela vazia mantém as colunas e o relatório avisa "é preciso N ≥ 2"; IC e figuras seguem saindo; `make selftest` ganhou `test_pairwise_n1` para o caso não voltar |
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
