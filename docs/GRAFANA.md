# Grafana: o que cada painel mostra e como ler

## TL;DR

- **Endereço:** `http://<CLUSTER_HOST>:<GRAFANA_PORT>`. Na VPS: `http://<IP_DA_VPN>:5090`; local: `http://localhost:5090`. Leitura sem login; para editar: `admin` / `GRAFANA_ADMIN_PASSWORD` do `.env`.
- **Dois dashboards:**
  - **Detector Online & HPA:** o que olhar durante `make hpa-experiment` e `make experiment`. Mostra o que o detector decide e o que o HPA faz.
  - **Anomaly Detection Lab:** a aplicação (carga, latência, CPU, réplicas). Mostra o efeito da carga.
- **Configuração recomendada:** intervalo *Last 15 minutes*, atualização a cada *5s* (canto superior direito).
- **O painel mais importante:** "anomaly_level × réplicas". No modo B, o nível do detector deve subir **antes** das réplicas.

---

## 1. Dashboard "Detector Online & HPA" (7 painéis)

### Score do detector online (razão score/limiar; >1 = alerta)

- **Consulta:** `max by (detector) (anomaly_score)`
- **O que é:** para cada detector, a nota do ponto atual dividida pelo limiar. **Acima de 1 = alerta.** Abaixo de 0 só significa "mais típico que a média da referência".
- **Num burst:** as linhas cruzam 1 durante as janelas do pico (150–185 s, 305–345 s e 465–500 s após o início da execução).
- **Cuidado (problema conhecido):** com o cluster ocioso, a referência fica quase constante, o σ vai a ~0 e a razão explode (já se viu o AE em ~100.000). A escala vertical fica dominada por esse valor e as outras linhas parecem zero. Para ler, use escala logarítmica ou limite o eixo (por exemplo, de −2 a 5) e trace uma linha em 1. Ver também a seção 4.

### Alertas por detector

- **Consulta:** `max by (detector) (anomaly_alert)`
- **O que é:** uma faixa por detector ao longo do tempo: 0 = normal, 1 = alerta. É exatamente o que vira a coluna `online_<DET>` do CSV e é pontuado no F1.
- **Num burst:** blocos de alerta alinhados com os picos. Alerta fora dos picos = falso alarme; pico sem alerta = anomalia perdida.
- **Cuidado (problema conhecido):** sem mapeamento de valores, cada faixa sai na cor do detector e 0 e 1 ficam parecidos. Corrigir com *Value mappings*: 0 = cinza "normal", 1 = vermelho "alerta".

### anomaly_level (métrica do HPA) × réplicas — o principal

- **Consultas:**
  - `max by (detector) (anomaly_level)`: o nível de cada detector (0; 0,33; 0,67; 1);
  - `kube_horizontalpodautoscaler_status_desired_replicas`: réplicas que o HPA **pediu**;
  - `kube_deployment_status_replicas_available`: réplicas **prontas**.
- **O que é:** liga a detecção à ação. O `anomaly_level` é a fração de alertas nos últimos 3 passos. No modo B, o HPA lê só o do detector `HPA_B_DETECTOR`. Com alvo 0,5, o HPA age a partir de 0,67 (2 de 3 alertas).
- **Como ler:**
  - **Modo A:** os níveis sobem e descem, mas as réplicas só reagem quando a CPU passa de 50%. O nível é ignorado pelo HPA.
  - **Modo B:** o nível do detector escolhido chega a 0,67 ou 1 e, logo depois, as réplicas **desejadas** sobem; as **disponíveis** sobem uns 10–30 s depois (tempo de o pod ficar pronto).
  - A distância entre o início do pico e a subida das réplicas desejadas é o **tempo de reação**, a métrica principal da Fase 3 (`reaction_time_s`).
- **Escala:** nível (0–1) e réplicas (2–8) dividem o mesmo eixo. As réplicas aparecem "em cima" e o nível "embaixo", o que é normal.

### Latência p95 e requisições/s (contexto)

- **Consultas:** p95 da latência (`histogram_quantile(0.95, …)`, em segundos) e `taxa de requisições / 100`.
- **O que é:** o "gabarito visual": onde estão os picos de carga e quanto a aplicação sofreu.
- **Cuidado:** a taxa está **dividida por 100** para caber no mesmo eixo. Uma linha em 0,5 = 50 req/s.

### Entradas do detector (as 4 features)

- **Consulta:** `detector_input`
- **O que é:** os 4 valores que o detector leu do Prometheus no último ciclo: latência p95, CPU, memória e taxa de requisições.
- **Para que serve:** confirmar que os dados chegam. Uma linha zerada ou ausente = consulta sem dados (o detector repete o último valor válido).

### Saúde do detector

- **Consultas:**
  - `time() − detector_last_success_timestamp`: segundos desde o último ciclo bem-sucedido;
  - p95 de `detector_step_seconds`: quanto tempo cada ciclo leva.
- **Valores esperados:** o primeiro oscila entre 0 e ~5 s (o intervalo do ciclo). O segundo deve ficar bem abaixo de 5 s.
- **Sinais de problema:** o primeiro crescendo sem parar = o detector travou ou não alcança o Prometheus (`make detector-logs`). O segundo perto de 5 s = o detector não dá conta do ciclo e começa a atrasar, o que aumenta o atraso dos alertas.

### Modo do HPA (label hpa-mode) e CPU-alvo

- **Consulta:** `kube_horizontalpodautoscaler_spec_target_metric`
- **O que é:** os alvos configurados no HPA agora.
- **Como ler:** CPU 50 = modo A ou B; CPU 35 = modo C. Uma série extra de `anomaly_level` com alvo 0,5 aparece **só** nos modos B e D. É o jeito de confirmar, no meio do experimento, que o script trocou de modo. No terminal: `make hpa-status`.

---

## 2. Dashboard "Anomaly Detection Lab" (8 painéis)

| Painel | Consulta (resumo) | O que mostra | Como ler |
|---|---|---|---|
| **Request Rate (req/s)** | `rate(http_requests_total[30s])` por endpoint | requisições por segundo | a forma da carga do k6: picos no burst, rampa no rampup, degraus no shift |
| **Latência p95 (segundos)** | `histogram_quantile` 0,95 e 0,50 | p95 e mediana da latência | o efeito da carga; o p95 acima de 0,5 s = acima do SLO (`SLO_SECONDS`) |
| **CPU por Pod (%)** | `rate(container_cpu_usage_seconds_total[30s]) × 100` | uso de CPU de cada pod | **atenção:** é % de **um núcleo**, não % do `request` (ver abaixo) |
| **Memória por Pod (MB)** | `container_memory_usage_bytes` | memória de cada pod | deve ficar estável; crescimento contínuo = vazamento |
| **Réplicas (HPA)** | `kube_deployment_status_replicas_available` | pods prontos | de 2 (mínimo) a 8 (máximo) |
| **Error Rate (%)** | 5xx / total | % de erros do servidor | perto de 0; subindo nos picos = aplicação saturada |
| **Requests In Progress** | `http_requests_in_progress` | requisições sendo atendidas agora | a "fila"; sobe quando a aplicação não dá conta |
| **Request Rate por Endpoint** | igual ao primeiro, por endpoint e método | o mesmo, mais detalhado | qual endpoint o roteiro está exercitando |

### CPU por Pod × alvo do HPA

O painel mostra % de **um núcleo**. O HPA mede % do **`request`** do pod, que é 100m (0,1 núcleo). Então:

| No painel | Para o HPA |
|---|---|
| 5% | 50% (alvo dos modos A e B) |
| 3,5% | 35% (alvo do modo C) |
| 10% | 100% |

Um pod mostrando 6% no painel já está acima do alvo do HPA.

---

## 3. O que observar num burst (12 min)

As janelas anômalas do burst começam aos 150 s, 305 s e 465 s após o início da execução. O horário de início aparece no terminal (`══════ X_burst_run1 …`).

| Momento | Anomaly Detection Lab | Detector Online & HPA |
|---|---|---|
| antes do pico | req/s estável, p95 baixo, 2 réplicas | scores abaixo de 1, sem alertas, níveis em 0 |
| início do pico | req/s e p95 sobem; CPU começa a subir | scores cruzam 1; alertas aparecem; níveis sobem para 0,33 → 0,67 → 1 |
| **modo A** | réplicas sobem só quando a CPU passa do alvo | níveis sobem, mas não mexem nas réplicas |
| **modo B** | réplicas sobem mais cedo | réplicas desejadas sobem logo após o nível do detector chegar a 0,67 |
| fim do pico | req/s e p95 voltam | alertas devem parar; se continuam, é atraso ou falso alarme |
| depois | réplicas descem devagar (120 s de espera, −1 pod/min) | níveis em 0 |

## 4. Problemas conhecidos e como verificar

### Referência "vazia" no início de cada execução (possível causa de falsos alarmes)

Entre execuções, o cluster fica parado (cooldown de `COOLDOWN` s, mais a espera pelas 2 réplicas). A janela de referência do detector (5 min) é feita quase só desse silêncio. Quando o k6 começa o tráfego **normal**, o detector o compara com o silêncio e pode alarmar antes da primeira anomalia (aos 150 s). Cada alarme ali é um falso positivo.

**Analogia: o segurança da loja.** O detector é como um segurança que só conhece a loja pelo que viu nos últimos 5 minutos:

1. Entre uma execução e outra, a loja fica **vazia** (cooldown, sem carga).
2. O segurança passa esses minutos vendo a loja vazia e conclui: "normal = loja vazia".
3. A execução começa e chegam os clientes **normais** (o tráfego base do k6). Para quem só viu a loja vazia, aquilo é estranho, e ele dispara o alarme.
4. Não era assalto: a anomalia de verdade só começa aos 150 s. Cada alarme nesse trecho conta como **falso alarme** e derruba a precisão.

Com a loja vazia, o segurança também fica hipersensível: tudo parado, qualquer movimento mínimo parece enorme. É o σ ≈ 0 que faz o score do AE explodir com o cluster ocioso.

As duas correções, na mesma analogia:
- **aquecimento:** deixar alguns clientes circulando durante o cooldown, para o segurança aprender como é a loja **em funcionamento**;
- **piso para o σ:** ensinar o segurança a não se assustar com movimentos mínimos quando a loja está quase parada.

No Grafana: alertas e scores acima de 1 **nos primeiros 150 s** da execução, quando ainda não há anomalia. Também picos de score com o cluster ocioso (σ ≈ 0).

Nos dados, por exemplo: *"no datasets_hpa/A_burst_run1.csv, conte quantos 1 cada coluna online_* tem com offset_seconds < 150"*. Nesse trecho o `label` é sempre 0.

Correções possíveis (decisão de método, **antes** das 10 repetições, com o orientador):
- **aquecimento:** tráfego normal leve durante o cooldown, para a referência conter "normal com carga" (`bin/experiment.sh`);
- **piso para o σ** no cálculo da razão (`scripts/online_detector.py`).

Detalhes em [DETECTOR_ONLINE.md](DETECTOR_ONLINE.md).

### Painéis de visualização

| Painel | Problema | Correção (`k8s/monitoring/grafana.yaml`, dashboard `online-detector.json`) |
|---|---|---|
| Score do detector online | escala dominada por valores enormes do AE | eixo logarítmico ou limites fixos; linha de limiar em 1 |
| Alertas por detector | 0 e 1 com cores parecidas | *Value mappings*: 0 = cinza "normal", 1 = vermelho "alerta" |

## 5. Painel vazio ("No data")

| Painel | Causa provável | Verificar |
|---|---|---|
| todos do detector | pod do detector parado ou sem aquecer (precisa de ~20 pontos, cerca de 2 min) | `make detector-logs`; painel "Saúde do detector" |
| réplicas e alvos do HPA | kube-state-metrics fora | `make status`; `make ksm-deploy` |
| latência, req/s e CPU | sem carga no momento, ou app fora | `make status`; rodar `make test-burst` |
| `anomaly_level` chega ao Grafana, mas o HPA ignora | Adapter sem a métrica ou HPA no modo A | `make phase2-check`; `make hpa-status` |