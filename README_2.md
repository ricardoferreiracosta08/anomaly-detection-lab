# Anomaly Detection Lab — Kubernetes (100% Docker + IaC)

**Avaliação Experimental Comparativa de Detectores de Anomalias (EWMA, IF, LOF) em Workloads Kubernetes**
Ricardo Ferreira Costa — PPGCC/UFMA — 2026

- Cabe observar que a análise atual está centrada em métricas agregadas
por cenário e por detector. Como evolução futura, pretende-se aprofundar
a investigação com análise temporal dos alertas ao longo das janelas
anômalas, distribuição dos falsos positivos e falsos negativos, e
discussão de aplicabilidade prática em ambientes reais, incluindo
integração com mecanismos de autoescalonamento, observabilidade contínua
e operação em modo online/streaming.

"Análise temporal dos alertas" — Hoje você sabe que o EWMA teve F1=0.431 no burst. Mas não sabe quando ele acertou e quando errou. A análise temporal é um gráfico mostrando, segundo a segundo, o que o ground truth diz e o que o detector diz. Isso revela, por exemplo, que o EWMA acerta no meio do burst mas erra nos primeiros 10 segundos (atraso) e nos últimos 5 segundos (demora para parar de alertar).
"Distribuição dos FP e FN" — Hoje você sabe que o EWMA teve Precision=0.29 (muitos falsos positivos). Mas não sabe onde esses falsos positivos acontecem. Estão concentrados logo após o warmup? Estão espalhados? Os falsos negativos do IF estão nas bordas das janelas anômalas ou no meio? Saber onde os erros acontecem explica por que o detector erra, não só quanto erra.
"Aplicabilidade prática: autoescalonamento, online/streaming" — Seus detectores rodam depois, sobre CSVs já prontos. Em produção real, o detector precisaria rodar em tempo real, analisando cada ponto conforme chega. O orientador quer que a dissertação discuta: como seria isso? O EWMA já funciona em streaming naturalmente (processa ponto a ponto). O IF precisaria ser retreinado periodicamente ou usar uma versão incremental. O LOF teria custo computacional alto em streaming. E como conectar isso ao HPA? Por exemplo: detector percebe anomalia → manda sinal ao HPA antes da CPU subir → escalonamento preditivo em vez de reativo. Ele não quer que você implemente, quer que você discuta.

- Além disso, o número de repetições por cenário ainda é limitado. As três
rodadas permitem observar variação inicial entre execuções, mas não são
suficientes para inferência estatística robusta. Na continuidade deste
trabalho, pretende-se ampliar para 5 a 10 repetições por cenário e
incluir testes de significância estatística, intervalos de confiança e
medidas adicionais de variabilidade.

se 10, serao 10x3 gerando 30 CSV com 90 avalicacos dos 3 dectetores?

2:21 AM

Validou cálculos de repetições e estimou duração total do experimento
Validou cálculos de repetições e estimou duração total do experimento
Sim, exatamente.

3 cenários × 10 repetições = 30 execuções K6 = 30 CSVs
30 CSVs × 3 detectores = 90 avaliações
Tempo estimado com 10 repetições:

Burst:    12 min × 10 =  120 min
Rampup:   13 min × 10 =  130 min
Shift:    16 min × 10 =  160 min
Cooldowns: 2 min × 29 =   58 min
Export + detect:        ~  10 min
                  Total ≈  8 horas
Com 5 repetições: 15 CSVs, 45 avaliações, ~4 horas. Provavelmente o equilíbrio mais prático para a VPS.

---

## O que este projeto faz (em uma frase)

Gera carga controlada sobre uma aplicação web rodando em Kubernetes, coleta métricas de desempenho em tempo real, e compara três algoritmos de detecção de anomalias para saber qual funciona melhor em cada tipo de problema.

---

## Conceitos fundamentais

### O que é Kubernetes

Kubernetes (K8s) é uma plataforma que gerencia aplicações empacotadas em **containers** (Docker). Em vez de rodar sua aplicação diretamente num servidor, você empacota ela numa imagem Docker e diz ao Kubernetes: "rode 2 cópias desta aplicação e mantenha elas saudáveis". O Kubernetes distribui as cópias entre os servidores, reinicia se uma cair, e pode aumentar ou diminuir o número de cópias automaticamente.

Termos essenciais:

- **Pod**: a menor unidade no Kubernetes. Um pod roda um container (sua aplicação). Neste projeto, cada pod roda uma instância da FastAPI.
- **Deployment**: diz ao Kubernetes "quero N pods desta aplicação rodando o tempo todo". Se um pod morre, o Deployment cria outro.
- **Service**: um endereço fixo que distribui requisições entre os pods. Quando o K6 manda uma requisição para `http://fastapi-service:80`, o Service escolhe um dos pods para responder.
- **Namespace**: uma separação lógica dentro do cluster. Tudo deste projeto roda no namespace `anomaly-lab`.
- **HPA (Horizontal Pod Autoscaler)**: mecanismo que monitora a CPU dos pods e cria/remove cópias automaticamente. Neste projeto, quando a CPU média passa de 50%, o HPA cria mais pods (até 8). Quando cai, remove (até mínimo de 2).
- **K3D**: ferramenta que cria um cluster Kubernetes dentro de containers Docker na sua máquina. Simula um cluster real sem precisar de servidores.

### O que é detecção de anomalias

Anomalia é algo fora do normal. Se sua aplicação normalmente responde em 10ms e de repente começa a responder em 2000ms, isso é uma anomalia. Se a CPU normalmente fica em 15% e pula para 90%, é outra anomalia.

Detectar anomalias **automaticamente** significa: dado um fluxo contínuo de números (latência, CPU, memória, etc.), um algoritmo decide para cada momento: "isto é normal" ou "isto é anômalo". Sem um humano olhando gráficos.

### Detecção supervisionada vs. não supervisionada

- **Supervisionada**: você dá ao algoritmo exemplos rotulados: "este dado é normal, este é anomalia". O algoritmo aprende o padrão. Problema: precisa de muitos exemplos rotulados, que raramente existem em ambientes de produção.
- **Não supervisionada**: o algoritmo não recebe exemplos. Ele aprende sozinho o que é "normal" a partir dos dados e marca o que não se encaixa como anomalia. Os três detectores deste projeto (EWMA, IF, LOF) são todos não supervisionados.

### O que é univariado vs. multivariado

**Univariado** = o algoritmo olha **uma métrica por vez**. Se você monitora latência, CPU, memória e request rate, o detector univariado analisa cada uma separadamente. Exemplo: o EWMA olha só a latência p95.

**Multivariado** = o algoritmo olha **várias métricas ao mesmo tempo**. Cada momento no tempo é representado como um ponto num espaço de N dimensões. Exemplo: o IF e LOF olham latência + CPU + memória + request rate simultaneamente.

Por que isso importa? No cenário de **load-shifting**, a taxa de requisições fica constante (50 req/s), mas o tipo muda de leve para pesado. A latência sobe um pouco, a CPU dispara, mas a request rate não muda. Um detector univariado que só olha request rate não vê nada. Um detector multivariado que olha os 4 números juntos percebe que a "forma" do dado mudou.

Exemplo em código:

```python
# EWMA recebe 1 número por ponto:
latency = [0.012, 0.011, 0.089, 0.142, 0.025]
#          um valor por instante

# IF e LOF recebem 4 números por ponto:
features = [
    [0.012, 15.2, 128.5, 10.3],   # latência, CPU, memória, req_rate
    [0.011, 14.8, 128.3, 10.1],
    [0.089, 72.1, 198.2, 85.7],   # ← este ponto está longe dos outros
]                                    #   no espaço 4D = anomalia
```

### O que é F1-score, Precision, Recall e MTTD

Imagine que o detector é um alarme de incêndio:

- **TP (True Positive)**: alarme tocou E tinha fogo. Acerto.
- **FP (False Positive)**: alarme tocou mas NÃO tinha fogo. Alarme falso.
- **FN (False Negative)**: tinha fogo e o alarme NÃO tocou. Perigo!
- **TN (True Negative)**: sem fogo e alarme quieto. Tudo certo.

As métricas:

- **Precision** = TP / (TP + FP) → "de todas as vezes que o alarme tocou, quantas vezes realmente tinha fogo?"
- **Recall** = TP / (TP + FN) → "de todas as vezes que teve fogo, quantas vezes o alarme tocou?"
- **F1-score** = 2 × Precision × Recall / (Precision + Recall) → nota final que equilibra os dois. Vai de 0 (péssimo) a 1 (perfeito).
- **MTTD** = Mean Time To Detect → "quanto tempo entre o fogo começar e o alarme tocar?"

Exemplos do nosso experimento:

```
EWMA no burst:  Precision=0.29 (71% dos alarmes são falsos)
                 Recall=0.87   (pegou 87% das anomalias)
                 F1=0.43       (razoável — muitos alarmes falsos puxam pra baixo)
                 MTTD=5.6s     (rápido)

IF no shift:     Precision=0.68 (68% dos alarmes são reais)
                 Recall=0.15   (só pegou 15% das anomalias)
                 F1=0.24       (fraco — perde muita anomalia)
                 MTTD=23s      (lento)
```

### O que é o parâmetro contamination

Quando você roda IF ou LOF, precisa dizer: "espere que X% dos dados sejam anomalias". O algoritmo então marca exatamente X% dos pontos mais estranhos como anomalia.

Se você diz `contamination=0.1` (10%), o algoritmo marca os 10% mais estranhos. Se na verdade 48% dos dados são anomalias (como no cenário shift), ele pode marcar no máximo 10% — os outros 38% escapam. O Recall máximo teórico fica limitado a ~20%.

É como dar 10 algemas a um policial e pedir pra prender 48 criminosos.

### O que é ground truth

O ground truth é a "resposta certa" — para cada segundo do experimento, sabemos se é normal ou anomalia porque NÓS controlamos o K6. Os scripts K6 definem exatamente quando os bursts acontecem, quando a carga sobe, quando o perfil muda. O script `export_metrics.py` anota cada ponto com label=0 (normal) ou label=1 (anomalia).

Depois, comparamos o que o detector disse (y_pred) com o que realmente aconteceu (label) para calcular F1, Precision, Recall e MTTD.

---

## Pré-requisitos

Apenas Docker. O `setup.sh` verifica e instala o resto:

| Ferramenta | O que é | Instalação |
|-----------|--------|------------|
| Docker 24+ | Roda containers | [docs.docker.com](https://docs.docker.com/get-docker/) |
| k3d 5+ | Cria cluster K8s dentro do Docker | `./setup.sh` instala |
| kubectl 1.28+ | Comando para falar com o K8s | `./setup.sh` instala |

K6, Python, scikit-learn, numpy — tudo roda em container. Nada é instalado no host.

---

## Design Experimental

### 1 fator experimental, 3 algoritmos de análise

O **fator experimental** (o que muda entre as rodadas) é o **padrão de carga**, com 3 níveis:

1. **Burst** — rajadas súbitas (mudanças abruptas)
2. **Ramp-up irregular** — crescimento em escada (mudanças graduais)
3. **Load-shifting** — mudança de perfil sem mudar volume (mudanças sutis)

Os **3 algoritmos** (EWMA, IF, LOF) não são fatores — rodam **depois**, offline, sobre os mesmos dados. Não mudam nada no cluster.

Cada cenário é repetido **3 vezes** para garantir que os resultados não são acaso. Total:

```
3 cenários × 3 repetições = 9 execuções K6 → 9 CSVs
9 CSVs × 3 detectores = 27 avaliações
```

### Tabela de cruzamento cenário × detector

```
                 EWMA            IF              LOF
              ──────────────  ──────────────  ──────────────
BURST          F1=0.43         F1=0.47 ★       F1=0.10
RAMPUP         F1=0.42 ★      F1=0.18         F1=0.03
SHIFT          F1=0.06         F1=0.24         F1=0.25 ★

★ = melhor detector naquele cenário
```

Nenhum detector é o melhor em todos os cenários — essa é a conclusão principal.

---

## A Aplicação FastAPI — por que tem 5 endpoints

O app do semestre passado (2025.2) tinha 1 endpoint: `GET /` retornando um JSON estático. Toda requisição custava o mesmo — impossível simular load-shifting.

O app novo tem 5 endpoints com perfis de carga diferentes:

| Endpoint | Método | O que faz internamente | Custo | Por que existe |
|----------|--------|----------------------|-------|---------------|
| `/health` | GET | Retorna `{"status": "healthy"}` | ~0ms | K8s verifica se o pod está vivo |
| `/api/v1/items` | GET | Lista items da memória | ~1ms | Requisição "leve" (baseline) |
| `/api/v1/items` | POST | Cria item + 1 hash SHA-256 | ~5ms | Requisição de escrita |
| `/api/v1/items/search` | GET | Filtra + ordena + sleep | ~10ms | Requisição "moderada" |
| `/api/v1/items/report` | GET | 5000 iterações de SHA-256 | ~50-200ms | Requisição "pesada" (consome CPU de verdade) |

O `/report` é propositalmente pesado. Faz 5000 cálculos de hash SHA-256 em loop. Isso consome CPU real, não é um `sleep()`. Quando o K6 direciona 60% das requisições para este endpoint durante um burst, a CPU do pod satura e a latência dispara.

### Como o K6 usa os endpoints

**Normal (baseline)**: 100% GET /items (leve) → CPU ~15%, latência ~10ms

**Burst**: 60% GET /report (pesado) + 30% GET /search + 10% POST → CPU ~80%, latência ~1s+

**Load-shifting**: mesma quantidade de requisições, mas muda de 90% /items para 60% /report → CPU dispara sem mudar request rate

### Métricas expostas pelo app

Cada requisição é automaticamente contada pelo middleware Prometheus:

| Métrica | Tipo | O que conta |
|---------|------|-------------|
| `http_request_duration_seconds` | Histogram | Tempo de cada requisição (para calcular p50, p95, p99) |
| `http_requests_total` | Counter | Quantas requisições por endpoint/método/status |
| `http_requests_in_progress` | Gauge | Quantas requisições estão sendo processadas agora |

O Prometheus busca esses números a cada 5 segundos via `GET /metrics` no pod.

---

## Os 3 Detectores — como funcionam

### EWMA (Exponentially Weighted Moving Average)

**Classe**: Estatístico, univariado (olha 1 métrica: latência p95).

**Ideia**: Mantém uma "média suavizada" da latência. Dá mais peso às medições recentes. Se a média suavizada sai dos limites de controle (μ ± 3σ), marca anomalia.

**Fórmula**:
```
z_t = 0.3 × valor_atual + 0.7 × z_anterior

Se z_t > média + 3 × desvio_padrão → ANOMALIA
Se z_t < média - 3 × desvio_padrão → ANOMALIA
```

**Código simplificado**:
```python
def detect_ewma(latency_values):
    # Aprende o "normal" nos primeiros 30 pontos (150 segundos)
    mu = mean(latency_values[:30])     # média do baseline
    sigma = std(latency_values[:30])   # variação do baseline
    
    ucl = mu + 3 * sigma  # limite superior
    lcl = mu - 3 * sigma  # limite inferior
    
    z = mu  # começa na média
    predictions = []
    
    for valor in latency_values:
        z = 0.3 * valor + 0.7 * z   # suaviza
        if z > ucl or z < lcl:
            predictions.append(1)     # ANOMALIA
        else:
            predictions.append(0)     # normal
    
    return predictions
```

**Força**: Simples, rápido, sem treinamento. Bom para detectar picos óbvios na latência.

**Fraqueza**: Só olha latência. Se CPU subir mas latência ficar parecida → não detecta.

### Isolation Forest (IF)

**Classe**: ML não supervisionado, multivariado (olha 4 métricas juntas).

**Ideia**: Constrói 100 "árvores de decisão" com cortes aleatórios. Anomalias são pontos "fáceis de separar" dos demais — precisam de poucos cortes para ficar sozinhos. Pontos normais estão no meio da multidão e precisam de muitos cortes.

**Analogia**: Imagine 100 pessoas numa sala. 95 estão agrupadas no centro. 5 estão isoladas nos cantos. Se você dividir a sala com paredes aleatórias, as pessoas dos cantos ficam sozinhas rapidamente (poucos cortes). As do centro precisam de muitas paredes para serem isoladas.

**Código simplificado**:
```python
def detect_if(features):
    # features = array com 4 colunas: latência, CPU, memória, req_rate
    
    model = IsolationForest(
        contamination=0.1,    # "espere 10% de anomalias"
        n_estimators=100,     # 100 árvores
        random_state=42       # reprodutibilidade
    )
    
    # -1 = anomalia, 1 = normal
    raw_pred = model.fit_predict(features)
    
    # Converter para 0/1
    predictions = [1 if p == -1 else 0 for p in raw_pred]
    return predictions
```

**Força**: Olha 4 métricas ao mesmo tempo. Detecta load-shifting. Rápido.

**Fraqueza**: O `contamination=0.1` limita a detecção quando anomalias são >10% dos dados.

### LOF (Local Outlier Factor)

**Classe**: ML não supervisionado, multivariado (olha as mesmas 4 métricas).

**Ideia**: Para cada ponto, olha os 20 vizinhos mais próximos e compara: "a região onde eu estou é tão densa quanto a região dos meus vizinhos?". Se o ponto está em região pouco densa mas seus vizinhos estão em região densa, ele é anômalo.

**Analogia**: Numa cidade, se você está num bairro vazio mas seus vizinhos mais próximos moram em bairros movimentados, você é o "estranho" — mora longe de todo mundo.

**Código simplificado**:
```python
def detect_lof(features):
    model = LocalOutlierFactor(
        n_neighbors=20,       # olha os 20 vizinhos mais próximos
        contamination=0.1     # "espere 10% de anomalias"
    )
    
    raw_pred = model.fit_predict(features)
    predictions = [1 if p == -1 else 0 for p in raw_pred]
    return predictions
```

**Força**: Detecta anomalias contextuais — pontos que são normais "em geral" mas estranhos "localmente". Complementar ao IF.

**Fraqueza**: Mais lento. Precisa de muitos pontos para calcular densidades bem. Com datasets pequenos (145-193 pontos), a qualidade cai.

### Resumo comparativo

| | EWMA | IF | LOF |
|---|---|---|---|
| **O que olha** | 1 métrica (latência) | 4 métricas juntas | 4 métricas juntas |
| **Como decide** | "Saiu dos limites?" | "Fácil de isolar?" | "Região pouco densa?" |
| **Precisa treinar?** | Não | Não | Não |
| **Detecta burst?** | Sim (forte) | Sim (forte) | Fraco |
| **Detecta load-shifting?** | Não (cego) | Sim | Sim |
| **Velocidade** | Muito rápido | Rápido | Moderado |
| **Limitação** | Univariado | contamination | contamination + n_neighbors |

---

## Os 3 Cenários de Carga K6

### Cenário 1: Burst (`burst-anomaly.js`) — ~12 min (720s)

**O que simula**: Rajadas súbitas de tráfego, como um ataque DDoS leve, uma notícia viral, ou um cron job que dispara milhares de requisições de uma vez.

**O que acontece**: O número de usuários virtuais (VUs) salta de 10 para 80, volta para 10, sobe para 120, volta para 10, sobe para 200. Nos picos, 60% das requisições vão para o endpoint pesado (/report).

```
VUs
200|                                      ████
120|                      ████           █    █
 80|          ████       █    █         █      █
 10|██████████    ███████      █████████        ████
   └────────────────────────────────────────────────→ t
    baseline  burst1  normal  burst2  normal burst3 cool
```

**Proporção de anomalias**: 17.2% (25 de 145 pontos)

**O que testa**: Capacidade de detectar mudanças **abruptas e óbvias**. Todo detector deveria funcionar bem aqui.

### Cenário 2: Ramp-up irregular (`rampup-irregular.js`) — ~13 min (780s)

**O que simula**: Crescimento orgânico imprevisível — como um site que vai ficando popular ao longo do dia, mas com quedas parciais no meio.

**O que acontece**: A carga sobe em degraus desiguais (10→40→60→100), depois recua (100→55), depois sobe mais (55→110→150→200). Não é linear nem previsível.

```
VUs
200|                                          ████
150|                                    ████ █
100|              ████    ████        █
 55|                    █      █████
 40|    ████
 10|███      ████████████                  ███
   └──────────────────────────────────────────→ t
```

**Proporção de anomalias**: 26.8% (42 de 157 pontos)

**O que testa**: Detecção de anomalias **graduais** onde a fronteira entre normal e anômalo é difusa.

### Cenário 3: Load-shifting (`load-shifting.js`) — ~16 min (960s)

**O que simula**: Mudança no TIPO de trabalho sem mudar a QUANTIDADE. Exemplo real: uma API que normalmente recebe consultas leves começa a receber relatórios pesados porque um sistema batch entrou em operação.

**O que acontece**: ~50 VUs o tempo todo (constante!), mas o mix de endpoints muda:
- Fase 1: 90% /items (leve) → CPU ~15%
- Fase 2: 60% /report (pesado) → CPU ~80%
- Fase 3: 90% /items (volta ao normal)
- Fase 4: 70% POST /items (escrita) → CPU ~40%
- Fase 5: 25% de cada

```
VUs:  ██████████████████████████████████████████████ (~50 constante)

Mix:  NORMAL      SHIFT→CPU    RECOVERY    SHIFT→WRITE   MIXED
      90% light   60% heavy    90% light   70% write     25% cada
```

**Proporção de anomalias**: 48.2% (93 de 193 pontos)

**O cenário mais difícil e mais importante.** A request rate não muda. Um detector que só olha volume de requisições não vê nada. Só detectores multivariados (que olham CPU + latência + memória juntos) podem perceber a mudança.

---

## Ground Truth — como sabemos a "resposta certa"

Como NÓS controlamos o K6, sabemos exatamente quando cada anomalia acontece. O script `export_metrics.py` anota cada ponto do CSV:

```python
ANOMALY_PHASES = {
    "burst": [(150, 185), (305, 345), (465, 500)],  # 3 janelas
    "rampup": [(120, 240), (360, 480), (540, 660)],  # 3 janelas
    "shift": [(180, 420), (540, 720), (780, 900)],    # 3 janelas
}
```

Cada ponto recebe label=0 (normal) ou label=1 (anomalia). Depois o detector é avaliado comparando suas predições com esses labels.

---

## Resultados

### Tabela completa (média de 3 repetições)

```
                 EWMA            IF              LOF
              ──────────────  ──────────────  ──────────────
BURST          F1=0.43         F1=0.47 ★       F1=0.10
               Rec=0.87        Rec=0.37        Rec=0.08
               MTTD=5.6s       MTTD=18.6s      MTTD=5.0s

RAMPUP         F1=0.42 ★      F1=0.18         F1=0.03
               Rec=0.53        Rec=0.13        Rec=0.02
               MTTD=7.5s       MTTD=17.8s      MTTD=22.5s

SHIFT          F1=0.06         F1=0.24         F1=0.25 ★
               Rec=0.03        Rec=0.15        Rec=0.15
               MTTD=inf        MTTD=23.1s      MTTD=65.8s

★ = melhor detector no cenário
```

### O que os resultados mostram

1. **Nenhum detector é universalmente melhor** — EWMA ganha no rampup, IF ganha no burst, LOF ganha no shift.
2. **Load-shifting é o cenário mais difícil** — F1 médio cai de 0.33 (burst) para 0.18 (shift).
3. **EWMA é cego ao load-shifting** — F1=0.06, essencialmente não detecta nada. Confirma que análise univariada não basta.
4. **IF e LOF superam EWMA 4× no shift** — confirma a vantagem de detectores multivariados para mudanças de perfil.

---

## Pipeline completo

```
make experiment
│
├─ 1. make up (se necessário)
│     └─ setup.sh → k3d cluster → build images → deploy K8s
│
├─ 2. Para cada cenário × 3 rodadas:
│     ├─ K6 (container) gera carga → FastAPI no K3D
│     │   └─ Prometheus coleta métricas a cada 5s
│     ├─ Python (container) exporta Prometheus → CSV
│     │   └─ Anota ground truth (label 0/1) pelas fases K6
│     └─ Cooldown 2 min (HPA volta ao baseline)
│
├─ 3. make detect
│     └─ Python (container) roda 3 detectores sobre cada CSV
│         ├─ EWMA sobre latência p95 (univariado)
│         ├─ IF sobre 4 features (multivariado)
│         └─ LOF sobre 4 features (multivariado)
│
└─ 4. Saída:
      ├─ datasets/{burst,rampup,shift}_run{1,2,3}.csv  (9 CSVs)
      ├─ results/detection_results.csv                  (27 linhas)
      └─ results/factorial_effects.json
```

---

## Tempos de execução

| Comando | O que faz | Duração |
|---------|----------|---------|
| `make up` | Cluster + build + deploy | ~2 min |
| `make experiment-quick` | 1 rodada burst + detect | ~14 min |
| `make experiment` | 9 rodadas + cooldowns + detect | **~2h25** |

---

## Topologia

### Modo local (dev/teste)

```bash
make up && make experiment-quick && make down
```

### Modo VPS + Notebook (experimento definitivo)

```bash
# VPS (roda o cluster)
make server-up

# Notebook (gera carga e analisa)
make client-experiment CLUSTER_HOST=10.0.0.2
```

**Por que separar?** K6 na mesma máquina compete por CPU e contamina resultados.

---

## Estrutura do Projeto

```
.
├── .env                     # Portas, CLUSTER_HOST
├── setup.sh                 # Verifica/instala prereqs + gera k3d-config
├── k3d-config.yaml          # GERADO por setup.sh — cluster declarativo
├── Makefile                 # Orquestrador 100% idempotente
├── app/
│   ├── Dockerfile           # Imagem da aplicação
│   └── main.py              # 5 endpoints + middleware Prometheus
├── k8s/
│   ├── namespace.yaml       # Namespace anomaly-lab
│   ├── app/deployment.yaml  # Deployment + Service + HPA
│   └── monitoring/
│       ├── prometheus.yaml  # Prometheus + RBAC + auto-discovery
│       └── grafana.yaml     # Grafana + 8 painéis provisionados
├── k6-scripts/
│   ├── config.js            # Endpoints e thresholds compartilhados
│   ├── burst-anomaly.js     # Cenário 1: rajadas (720s)
│   ├── rampup-irregular.js  # Cenário 2: escada assimétrica (780s)
│   └── load-shifting.js     # Cenário 3: mudança de perfil (960s)
├── scripts/
│   ├── Dockerfile           # Imagem Python + scikit-learn
│   ├── export_metrics.py    # Prometheus → CSV com ground truth
│   └── detectors.py         # EWMA + IF + LOF + avaliação
├── datasets/                # GERADO: 9 CSVs anotados
└── results/                 # GERADO: detection_results.csv
```

---

## Comandos

Qualquer comando resolve suas dependências automaticamente.

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
