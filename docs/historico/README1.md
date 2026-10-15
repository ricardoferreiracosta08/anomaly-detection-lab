# Anomaly Detection Lab — Kubernetes (100% Docker + IaC)

**Avaliação Experimental Comparativa de Detectores de Anomalias (EWMA, IF, LOF) em Workloads Kubernetes**  
Ricardo Ferreira Costa — PPGCC/UFMA — 2026

---

## Pré-requisitos

Apenas Docker. O `setup.sh` instala o resto.

| Ferramenta | Instalação |
|-----------|------------|
| Docker 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| k3d 5+ | Instalado por `./setup.sh` |
| kubectl 1.28+ | Instalado por `./setup.sh` |

K6, Python, scikit-learn, numpy — tudo roda em container.

---

## Design Experimental

### Fatorial 3×3 — 2 fatores, 3 níveis cada

| | **EWMA** | **Isolation Forest** | **LOF** |
|---|:---:|:---:|:---:|
| **Burst** | Exp 1 | Exp 2 | Exp 3 |
| **Ramp-up** | Exp 4 | Exp 5 | Exp 6 |
| **Shift** | Exp 7 | Exp 8 | Exp 9 |

- **Fator A** — Padrão de carga (3 níveis): burst, ramp-up irregular, load-shifting
- **Fator B** — Detector (3 níveis): EWMA, Isolation Forest, LOF 

#####################################################

FATOR B == >>> (nao sao fatores porque noa impactam no experimento)

comparar com HPA??

--

Opção 1: Mudar a Nomenclatura (A Solução Diplomática)Em computação e ciência de dados, quando comparamos algoritmos, o algoritmo é a variável que queremos avaliar. Se o seu orientador não aceita chamá-lo de "fator", use os termos abaixo para descrever seu experimento sem violar as regras do DoE:Variável de Tratamento (ou apenas "Algoritmo"): Diga que o seu experimento possui 1 Fator principal (o Padrão de Carga, com 3 níveis) e que você avaliará o desempenho de 3 algoritmos diferentes sobre esse fator.Abordagem OFAT Adaptada (One Factor at a Time): Você estará rodando um experimento de um único fator (Carga do K8s) repetido para 3 ferramentas distintas.

--

"O experimento foi conduzido utilizando um delineamento de bloco único, onde o Padrão de Carga atuou como o fator principal operando em 3 níveis distintos. Para cada nível de carga, foram avaliados 3 algoritmos de detecção de anomalias (EWCMA, IF e LOF). Para garantir a estabilidade dos resultados e mitigar interferências estocásticas da orquestração do Kubernetes, foram realizadas 3 replicações independentes para cada combinação, totalizando 27 baterias de testes."

####################


- **Repetições**: 3 rodadas por cenário de carga (reprodutibilidade)
- **Total**: 9 CSVs (3 cenários × 3 rodadas) → 27 avaliações (9 CSVs × 3 detectores)

### Onde está cada fator no código

O Makefile executa apenas o **Fator A** (carga). O **Fator B** (detector) é aplicado
depois, pelo `make detect`, que roda os 3 detectores sobre cada CSV:

```
Makefile (Fator A)              detectors.py (Fator B)
──────────────────              ──────────────────────────
K6 burst  → burst_run1.csv  →  EWMA  → resultado 1
                                IF    → resultado 2
                                LOF   → resultado 3
K6 burst  → burst_run2.csv  →  EWMA  → resultado 4
                                IF    → resultado 5
                                LOF   → resultado 6
K6 burst  → burst_run3.csv  →  (idem — repetição para média)
K6 rampup → rampup_run1.csv →  EWMA  → resultado 7
                                IF    → resultado 8
                                LOF   → resultado 9
...

9 CSVs × 3 detectores = 27 linhas em detection_results.csv
```

A tabela fatorial 3×3 se preenche com as médias das 3 repetições:

```
                EWMA              IF                LOF
              (média r1-r3)     (média r1-r3)     (média r1-r3)
BURST         F1=...            F1=...            F1=...
RAMPUP        F1=...            F1=...            F1=...
SHIFT         F1=...            F1=...            F1=...
```

### Efeitos fatoriais calculados

- **Efeito de A (carga)**: burst degrada mais a detecção que shift?
- **Efeito de B (detector)**: IF supera EWMA em todas as cargas?
- **Interação A×B**: o ganho do IF sobre EWMA é maior em cenários complexos?

### Métricas de avaliação

| Métrica | O que mede | Unidade |
|---------|-----------|---------|
| F1-score | Equilíbrio entre precision e recall | 0–1 |
| Precision | Proporção de alertas que são anomalias reais | 0–1 |
| Recall | Proporção de anomalias reais detectadas | 0–1 |
| MTTD | Tempo médio entre início da anomalia e primeiro alerta | segundos |

---

## Ground Truth — como sabemos a "resposta certa"

Como o experimento é controlado, sabemos **exatamente** quando a anomalia ocorre
— porque nós definimos as stages do K6. O ground truth é a anotação binária
(0=normal, 1=anomalia) de cada ponto da série temporal.

### Exemplo com o cenário burst

O `burst-anomaly.js` define stages com VUs ao longo do tempo:

```
Tempo (s)    VUs    O que acontece
─────────    ───    ──────────────
0-30         10     warm-up
30-150       10     baseline normal
150-185      80     BURST 1 ← anomalia
185-305      10     volta ao normal
305-345      120    BURST 2 ← anomalia
345-465      10     volta ao normal
465-500      200    BURST 3 ← anomalia
500-720      0      cool-down
```

O `export_metrics.py` conhece essas fases e anota cada linha do CSV:

```python
ANOMALY_PHASES = {
    "burst": [
        (150, 185),   # burst 1
        (305, 345),   # burst 2
        (465, 500),   # burst 3
    ],
}
```

### CSV resultante

```csv
datetime,               offset_s, latency_p95, cpu,  mem,   req_rate, label
2026-03-10T10:00:00,    0.0,      0.012,       15.2, 128.5, 10.3,     0  ← normal
2026-03-10T10:00:05,    5.0,      0.011,       14.8, 128.3, 10.1,     0  ← normal
...
2026-03-10T10:02:30,    150.0,    0.089,       72.1, 198.2, 85.7,     1  ← ANOMALIA
2026-03-10T10:02:35,    155.0,    0.142,       85.3, 210.1, 83.2,     1  ← ANOMALIA
...
2026-03-10T10:03:05,    185.0,    0.025,       22.1, 135.2, 12.1,     0  ← normal
```

### Como o detector é avaliado

O detector gera sua predição (0 ou 1) para cada ponto, e comparamos com o ground truth:

```
label (verdade):    0 0 0 0 1 1 1 1 1 0 0 0 0 1 1 1 ...
y_pred (EWMA):      0 0 0 0 0 0 1 1 1 0 0 0 0 0 1 1 ...
                                 ↑               ↑
                            atrasou 10s       atrasou 5s
                            (2 pontos)        (1 ponto)
```

- **MTTD** = média dos atrasos = (10 + 5) / 2 = 7.5s
- **TP** = pontos onde ambos são 1 (anomalia detectada corretamente)
- **FP** = detector diz 1, verdade é 0 (alarme falso)
- **FN** = detector diz 0, verdade é 1 (anomalia perdida)
- **F1** = 2 × precision × recall / (precision + recall)

### Por que o cooldown de 2 minutos entre rodadas

Sem cooldown, a rodada 2 começaria com o cluster ainda "quente" (CPU alta,
pods escalados pelo HPA). O detector veria anomalia no início da fase que
deveria ser "normal", contaminando o ground truth.

```
[BURST run1 12min] → [cool 2min] → [BURST run2 12min] → [cool 2min] → ...
```

O cooldown garante que CPU, memória e HPA voltem ao baseline antes de cada rodada.

---

## A Aplicação FastAPI — por que tem 5 endpoints

O app do semestre passado (2025.2) tinha 1 endpoint: `GET /` retornando um JSON estático.
Toda requisição custava o mesmo — impossível simular load-shifting.

O app novo tem **5 endpoints com perfis de carga diferentes**:

| Endpoint | Método | O que faz internamente | Custo |
|----------|--------|----------------------|-------|
| `/health` | GET | Retorna `{"status": "healthy"}` | ~0ms |
| `/api/v1/items` | GET | Lista items da memória | ~1ms |
| `/api/v1/items` | POST | Cria item + 1 hash SHA-256 | ~5ms |
| `/api/v1/items/search?q=...` | GET | Filtra + ordena + sleep(5-10ms) | ~10ms |
| `/api/v1/items/report` | GET | Loop de 5000 SHA-256 + agregação | ~50-200ms |

O `/api/v1/items/report` é propositalmente pesado — faz 5000 iterações de hash
SHA-256 em sequência. Consome CPU de verdade, não é um `sleep()`.

### Como o K6 usa os endpoints em cada fase

**Burst — fase normal (10 VUs):**
```
100% GET /api/v1/items (leve)     → CPU ~15%, latência ~10ms
sleep(1s) entre requisições       → ~10 req/s total
```

**Burst — fase de rajada (80-200 VUs):**
```
60% GET /api/v1/items/report (pesado)  → CPU sobe para 80%+
30% GET /api/v1/items/search           → latência p95 sobe para 150ms+
10% POST /api/v1/items                 
sleep(0.25s) entre requisições         → 4x mais pressão
```

A diferença entre normal e burst não é só "mais VUs" — é "mais VUs fazendo
coisas mais pesadas, mais rápido".

**Load-shifting — por que os endpoints são essenciais:**
```
Fase NORMAL:      50 VUs × GET /items (leve)       → CPU ~15%, latência ~10ms
Fase SHIFT→CPU:   50 VUs × GET /items/report       → CPU ~80%, latência ~150ms
Fase SHIFT→WRITE: 50 VUs × POST /items             → CPU ~40%, latência ~30ms
```

Mesma quantidade de VUs e mesma taxa de requisições. Mas o endpoint mudou.
Um detector que só olha request rate não vê nada. Um detector que olha
CPU + latência juntos (IF, LOF) vê a mudança imediatamente.

### Métricas Prometheus exportadas pelo app

Cada requisição é instrumentada automaticamente via middleware:

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `http_request_duration_seconds` | Histogram | Latência por endpoint (buckets p50-p99) |
| `http_requests_total` | Counter | Total de requisições por método/endpoint/status |
| `http_requests_in_progress` | Gauge | Requisições simultâneas em andamento |
| `app_items_total` | Gauge | Total de items no store |

Expostas em `/metrics` no formato Prometheus. O scrape interval de 5s
(configurado no `prometheus.yaml`) coleta essas métricas automaticamente
via annotation `prometheus.io/scrape: "true"` nos pods.

---

## Os 3 Detectores

### EWMA (Exponentially Weighted Moving Average)

**Classe:** Estatístico univariado (controle de processo).

**Como funciona:** Mantém uma média móvel da latência p95, dando peso maior
às amostras recentes. Quando a média suavizada ultrapassa os limites de
controle (μ ± 3σ), marca anomalia.

```
z_t = α × x_t + (1 - α) × z_{t-1}    onde α = 0.3
Anomalia se: z_t > μ + 3σ  OU  z_t < μ - 3σ
```

**Entrada:** 1 métrica (latência p95) — univariado.

**Parâmetros:** α=0.3 (suavização), k=3 (fator sigma), warmup=20 pontos.

**Força:** Simples, rápido, sem treinamento.

**Fraqueza:** Univariado — não vê correlações entre CPU e latência.
Não detecta load-shifting onde a latência muda pouco mas CPU dispara.

### Isolation Forest (IF)

**Classe:** Ensemble por isolamento, multivariado.

**Como funciona:** Constrói 100 árvores de decisão com splits aleatórios.
Anomalias são "fáceis de isolar" — precisam de poucos cortes para ficarem
sozinhas numa folha.

```
Para cada ponto x:
  caminho curto nas árvores → anomaly score alto → anomalia
  caminho longo → score baixo → normal
Anomalia se: score > percentil 95
```

**Entrada:** 4 métricas simultâneas (latência, CPU, memória, request rate).

**Parâmetros:** contamination=0.1, n_estimators=100, random_state=42.

**Força:** Multivariado. Não precisa de perfil de normalidade. Rápido.

**Fraqueza:** Não sensível a anomalias de contexto local. Sem dependência temporal.

### LOF (Local Outlier Factor)

**Classe:** Baseado em densidade local, multivariado.

**Como funciona:** Para cada ponto, calcula a densidade da vizinhança
(20 vizinhos) e compara com a densidade dos vizinhos. Ponto em região
menos densa que seus vizinhos é anomalia.

```
LOF(x) = média( densidade(vizinhos) / densidade(x) )
LOF ≈ 1 → normal
LOF >> 1 → anomalia
```

**Entrada:** 4 métricas simultâneas (mesmas do IF).

**Parâmetros:** n_neighbors=20, contamination=0.1.

**Força:** Detecta anomalias contextuais. Complementar ao IF.

**Fraqueza:** Mais lento que IF. Sensível à escolha de k.

### Comparativo

| | EWMA | IF | LOF |
|---|---|---|---|
| **Paradigma** | Controle estatístico | Isolamento | Densidade local |
| **Entrada** | 1 métrica | 4 métricas | 4 métricas |
| **Treinamento** | Nenhum | Não supervisionado | Não supervisionado |
| **Anomalias globais** | ✓ | ✓✓ | ✓ |
| **Anomalias locais** | ✗ | ✗ | ✓✓ |
| **Load-shifting** | Fraco | Forte | Forte |

---

## Os 3 Cenários de Carga K6

### Cenário 1: Burst (`burst-anomaly.js`) — ~12 min (720s)

**Simula:** Rajadas súbitas de tráfego.

```
VUs
200|                                      ████
120|                      ████           █    █
 80|          ████       █    █         █      █
 10|██████████    ███████      █████████        ████
   └────────────────────────────────────────────────→ t
    baseline  burst1  normal  burst2  normal burst3 cool
```

**Endpoints no burst:** 60% heavy, 30% moderate, 10% write.
**O que testa:** Detecção de mudanças abruptas. MTTD do IF/LOF deve ser menor que EWMA.

### Cenário 2: Ramp-up irregular (`rampup-irregular.js`) — ~13 min (780s)

**Simula:** Crescimento em escada com degraus assimétricos e recuos parciais.

```
VUs
200|                                          ████
150|                                    ████ █
100|              ████    ████        █
 55|                    █      █████
 40|    ████
 10|███      ████████████                  ███
   └──────────────────────────────────────────→ t
    base S1  S2   S3  recuo  S4   S5  pico  CD
```

**O que testa:** Anomalias graduais. Recuos parciais geram falsos negativos?

### Cenário 3: Load-shifting (`load-shifting.js`) — ~16 min (960s)

**Simula:** Mudança de perfil SEM mudar volume. VUs constantes (~50).

```
VUs:  ██████████████████████████████████████████████ (~50)

Mix de endpoints:
     NORMAL       SHIFT→CPU     RECOVERY     SHIFT→WRITE    MIXED
     90% light    60% heavy     90% light    70% write      25% cada
     10% moderate 20% write     10% moderate 10% light
```

**O cenário mais difícil.** Request rate constante, mas latência e CPU mudam.
EWMA (univariado) deve falhar. IF e LOF (multivariados) devem detectar.
Valida a hipótese H2 se IF/LOF superarem EWMA aqui.

---

## Tempos de execução

| Comando | O que faz | Duração |
|---------|----------|---------|
| `make up` | Cluster + build + deploy | ~2 min |
| `make experiment-quick` | 1 rodada burst + detect | ~14 min |
| `make experiment` | 9 rodadas + cooldowns + detect | **~2h25** |

**Cálculo do `make experiment`:**

```
Burst:   12 min × 3 rodadas     =  36 min
Rampup:  13 min × 3 rodadas     =  39 min
Shift:   16 min × 3 rodadas     =  48 min
Cooldown: 2 min × 8 intervalos  =  16 min
Export + Detect                  =   4 min
                           TOTAL ≈ 143 min (~2h25)
```

---

## Pipeline completo

```
make experiment
│
├─ 1. make up (se necessário)
│     └─ setup.sh → k3d cluster → build images → deploy K8s
│
├─ 2. Para cada cenário (burst, rampup, shift) × 3 rodadas:
│     ├─ K6 container gera carga → FastAPI no K3D
│     │   └─ Prometheus coleta métricas a cada 5s
│     ├─ Analysis container exporta Prometheus → CSV
│     │   └─ Anota ground truth (label 0/1) baseado nas fases K6
│     └─ Cooldown 2 min (HPA e CPU voltam ao baseline)
│
├─ 3. make detect
│     └─ Analysis container roda 3 detectores sobre cada CSV
│         ├─ EWMA sobre latência p95 (univariado)
│         ├─ IF sobre 4 features (multivariado)
│         └─ LOF sobre 4 features (multivariado)
│
└─ 4. Saída:
      ├─ datasets/{burst,rampup,shift}_run{1,2,3}.csv  (9 CSVs)
      ├─ results/detection_results.csv                  (27 linhas)
      └─ results/factorial_effects.json                 (médias por fator)
```

---

## Topologia

### Modo local (dev/teste)

```bash
make up                # Tudo na mesma máquina (~2 min)
make experiment-quick  # 1 rodada burst (~14 min)
make down
```

### Modo VPS + Notebook (experimento real)

```bash
# VPS
make server-up

# Notebook
make client-experiment CLUSTER_HOST=10.0.0.2
```

**Por que separar?** K6 na mesma máquina compete por CPU e contamina resultados.

---

## Estrutura

```
.
├── .env                     # Portas, CLUSTER_HOST
├── setup.sh                 # Verifica/instala prereqs + gera k3d-config
├── k3d-config.yaml          # GERADO por setup.sh
├── Makefile                 # Orquestrador idempotente
├── app/
│   ├── Dockerfile
│   └── main.py              # 6 endpoints + Prometheus metrics
├── k8s/
│   ├── namespace.yaml
│   ├── app/deployment.yaml  # Deployment + Service + HPA
│   └── monitoring/
│       ├── prometheus.yaml  # Prometheus + RBAC + auto-discovery
│       └── grafana.yaml     # Grafana + datasource provisionado
├── k6-scripts/
│   ├── config.js
│   ├── burst-anomaly.js     # 720s
│   ├── rampup-irregular.js  # 780s
│   └── load-shifting.js     # 960s
├── scripts/
│   ├── Dockerfile
│   ├── export_metrics.py    # Prometheus → CSV + ground truth
│   └── detectors.py         # EWMA + IF + LOF + avaliação
├── datasets/                # GERADO: 9 CSVs
└── results/                 # GERADO: detection_results.csv
```

---

## Comandos

Qualquer comando resolve dependências automaticamente.

```bash
make up                # setup + cluster + build + deploy
make experiment        # up + 9 rodadas + detect (~2h25)
make experiment-quick  # up + 1 rodada burst + detect (~14 min)
make test-burst        # up + K6 burst (~12 min)
make detect            # 3 detectores sobre datasets/
make status            # Pods e HPA
make rebuild           # Força rebuild das imagens
make down              # Destrói cluster
make clean             # Remove datasets/ e results/
```

---

## Queries Prometheus

```promql
# Latência p95
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{namespace="anomaly-lab"}[30s])) by (le))

# Request rate
sum(rate(http_requests_total{namespace="anomaly-lab"}[30s])) by (endpoint)

# CPU por pod
sum(rate(container_cpu_usage_seconds_total{namespace="anomaly-lab",container="fastapi"}[30s])) by (pod)

# Memória por pod
sum(container_memory_usage_bytes{namespace="anomaly-lab",container="fastapi"}) by (pod)
```
