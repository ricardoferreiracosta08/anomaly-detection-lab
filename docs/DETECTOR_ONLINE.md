# Detector online (Fase 2)

## TL;DR

- **O quê:** um pod no cluster (`online-detector`) roda os **mesmos 6 algoritmos** da Fase 1 (EWMA, IF, LOF, DBSCAN, AE, LSTM), mas de outro jeito: a cada 5 s, cada um é ajustado só no **passado recente** e decide se o ponto **de agora** é anômalo.
- **Para quê:** é o que um sistema real consegue fazer (não dá para olhar o futuro) e é o que alimenta o HPA no modo B ([HPA.md](HPA.md)).
- **Como é avaliado:** os alertas ficam gravados no Prometheus durante a carga, viram as colunas `online_<DET>` do CSV e são pontuados contra o mesmo gabarito (`label`) dos offline, aparecendo como `<DET>_online` nos resultados.
- **Dois efeitos a ter em mente:** (1) o procedimento online pode **superar** o offline (sem *masking*, limiar adaptativo); (2) ao vivo, ele sofre **atraso**, que penaliza precisão e recall.

```bash
make detector-logs                                     # o detector está rodando?
make online-replay CSV=datasets/burst_run1.csv         # o procedimento online sobre um CSV, sem cluster
```

---

## 1. Como funciona

A cada `DETECTOR_STEP_SECONDS` (5 s), o pod:

1. consulta no Prometheus as 4 métricas atuais da aplicação: latência p95, CPU, memória e taxa de requisições (as mesmas do offline, definidas em `scripts/prom_queries.py`);
2. guarda o ponto no histórico. Lacuna do Prometheus (NaN) vira o último valor válido;
3. monta a **janela de referência**: os últimos `DETECTOR_WINDOW` pontos (60 = 5 min), **terminando** `DETECTOR_GAP` pontos (6 = 30 s) antes do ponto atual;
4. para cada algoritmo, ajusta o modelo na referência e dá uma nota ao ponto atual;
5. publica as notas em `/metrics`, e o Prometheus as coleta a cada 5 s.

```
tempo ──────────────────────────────────────────────────────────▶
        [──────── referência: 60 pontos (5 min) ────────][ gap 30 s ][agora]
         o modelo aprende o "normal" aqui                  fica de fora  é avaliado
```

**Por que o gap:** os pontos logo antes do atual podem ser o começo de uma anomalia. Se entrassem na referência, o detector "aprenderia" a anomalia no momento em que ela começa.

**Partida do pod:** o detector só decide quando a referência tem pelo menos 20 pontos. Até lá (cerca de 130 s depois que o pod sobe), publica 0. A janela cresce até 60 pontos e daí desliza.

### Aquecimento da carga antes de cada execução

**O problema (piloto 2, [PILOTOS.md](PILOTOS.md)):** entre execuções o cluster fica parado (espera pelas réplicas mínimas + cooldown). A referência de 5 min era feita **desse silêncio**, e o tráfego normal do início do roteiro parecia anômalo: 53–87% dos primeiros 150 s do burst em alerta, sem anomalia nenhuma.

**A correção:** logo antes de cada roteiro, o `bin/experiment.sh` roda o `k6-scripts/warmup.js` por `WARMUP_SECONDS` (padrão 330 s = (60 + 6) × 5 s, ou seja, a referência inteira + o gap). É carga **constante** com o mesmo mix de requisições da fase normal do roteiro:

| Cenário | VUs (nível no fim da 1ª rampa do roteiro) | Mix (copiado da fase normal) |
|---|---|---|
| burst | 10 | só leitura leve; pausa de 1–2 s |
| rampup | 10 | mix do `selectEndpoint()` com VUs 1–10 (~21% pesada, ~29% moderada, ~35% leve, 15% escrita); pausa de 0,5–2 s |
| shift | 30 | 90% leve, 10% moderada; pausa de 0,8–1,2 s |

Ordem: **app reiniciada** (estado limpo, 100 itens por pod) → réplicas no mínimo → cooldown → **aquecimento** (descida nos últimos 30 s) → conferências 15 s antes da descida → roteiro, que começa **30 s antes do fim do aquecimento**. Na Fase 3, tudo isso acontece com o HPA no **modo A**; o modo da execução (B, C ou D) só é aplicado depois da conferência, logo antes do roteiro. Assim, um alarme na passagem "parado → aquecimento" não faz o B escalar antes da hora, e toda execução começa com 2 réplicas ([HPA.md](HPA.md), seção 4).

O aquecimento não gera CSV, não entra na avaliação e é registrado em `results/warmup_log.csv`: réplicas ao fim (`at_min`), o `anomaly_level` do detector do B (`anomaly_level_b`, lido pelo Adapter como o HPA o veria) e os itens por pod da app (`items_per_pod`). Se o HPA escalar durante o aquecimento, o log avisa que a execução começou fora da condição inicial.

**Transiente da troca (corrigido):** os roteiros começam do zero, com uma rampa de 30 s até o nível normal (0 → 10 ou 0 → 30 VUs). Na 1ª versão do aquecimento, a carga **caía** e voltava a subir na troca, e AE, DBSCAN e LOF alarmavam de 15 a 45 s em **todas** as execuções do piloto 3 (7 de 30 pontos; EWMA nenhum). Agora as rampas se sobrepõem: o aquecimento desce de VUs → 0 nos seus últimos 30 s enquanto o roteiro sobe de 0 → VUs (a 1ª rampa dele), e a carga total fica constante. Os roteiros e o gabarito não mudaram; o início da execução (`start`) continua sendo o início do roteiro. O `make check-inicio` confere.

### Escopo

O detector online é avaliado **em regime**: com a referência formada por carga normal. A **partida a frio** (pod recém-criado, cluster vindo do zero, referência sem carga) fica **fora do escopo**. É uma limitação a declarar no método, não um caso medido.

### A decisão de cada algoritmo

No online, cada algoritmo produz uma **razão** (`anomaly_score`): **acima de 1 = alerta**. No offline (Fase 1, `detectors.py`), cada um tem sua regra própria, aplicada à execução inteira.

| Algoritmo | Nota | Online: razão (alerta se > 1) | Offline: regra de alerta |
|---|---|---|---|
| EWMA | latência p95 suavizada (λ = 0,3) | \|média suavizada − μ\| / (3σ) da latência na referência (K não se aplica) | fora de μ ± **3σ**, com μ e σ dos primeiros 150 s |
| IF | quão fácil é isolar o ponto | (nota − μ) / (K·σ_ef) das notas da referência | os **10%** mais estranhos (`contamination` = 0,1) |
| LOF | densidade local × vizinhos (20) | (nota − μ) / (K·σ_ef) | os **10%** mais estranhos (`contamination` = 0,1) |
| DBSCAN | distância ao ponto-núcleo mais próximo | distância / eps (eps = P90 da k-distância na referência; K não se aplica) | **ruído** (ponto fora de qualquer grupo; min_samples = 8, eps = P90) |
| AE | erro de **reconstrução** do ponto | (erro − μ) / (K·σ_ef) dos erros da referência | erro > **μ + 2σ** dos erros da execução |
| LSTM | erro de **previsão** do ponto a partir dos 12 anteriores | (erro − μ) / (K·σ_ef) dos erros da referência | erro > **μ + 2σ** dos erros de treino; os 12 primeiros pontos = normais |

No online, σ_ef = máx(σ, piso·|μ|) (piso das notas, `DETECTOR_SIGMA_FLOOR` = 0,05) e K = 2 (`DETECTOR_K_SIGMA`). Antes disso, as 4 entradas são padronizadas pela referência com o piso nas entradas (`DETECTOR_FEATURE_FLOOR` = 0,01), exceto no EWMA, que usa a latência bruta.

**Diferença importante:** no offline, IF e LOF **sempre** marcam 10% dos pontos, haja ou não anomalia; AE, LSTM, EWMA e DBSCAN marcam quantos passarem da régua. No online, os seis usam régua adaptativa (μ + K·σ da janela recente), sem proporção fixa.

### LSTM (6º detector)

**O que acrescenta:** a dimensão temporal (previsão do próximo ponto). IF, LOF, DBSCAN e AE olham cada ponto isolado; a LSTM olha a **sequência** e aprende "o que costuma vir depois". Entrou por pedido do orientador, antes da Fase 1 definitiva. Referências: Malhotra et al., *Long Short Term Memory Networks for Anomaly Detection in Time Series*, ESANN 2015; Hundman et al., KDD 2018.

**Como decide (online):**
1. as 4 features são padronizadas com μ e σ da referência, como nos outros;
2. a rede (1 camada LSTM com `LSTM_HIDDEN` = 16 unidades → camada linear com 4 saídas) é treinada na **referência** para prever cada ponto a partir dos `LSTM_SEQ_LEN` = 12 anteriores (1 min), com Adam por `LSTM_EPOCHS` = 30 épocas;
3. a sequência de entrada do ponto atual são os 12 pontos **imediatamente anteriores** a ele (os do gap inclusive); a nota é o erro quadrático médio da previsão do ponto atual;
4. a decisão usa o mesmo μ + K·σ_ef (com piso) das notas da referência, como IF, LOF e AE;
5. retreina a cada `LSTM_RETRAIN` = 12 passos (1 min), como o AE, para caber no ciclo de 5 s.

**Offline:** mesmo protocolo dos outros (treina na execução inteira); alerta se o erro > μ + 2σ dos erros de treino (mesmo critério do AE). Os primeiros 12 pontos não têm histórico e contam como normais (a 1ª janela anômala começa no ponto 30 ou depois).

**Reprodutível:** `torch.manual_seed(42)`, algoritmos determinísticos e 1 thread de CPU (`torch.set_num_threads(1)`, que também limita o uso de CPU no pod). PyTorch só CPU. Código: `scripts/lstm_model.py`. Arquitetura **fixa**: só muda com base no replay da qualificação, com o motivo documentado, nunca olhando a Fase 1 definitiva.

### Piso relativo nas entradas

**O problema (piloto 3, alertas em 140–145 s no A):** antes de ir aos algoritmos, cada uma das 4 features é padronizada pela referência: (valor − μ) / σ. A memória fica quase constante numa execução (σ ≈ 0,005 MB). Um salto de 0,25 MB aos 135 s, provavelmente uma coleta de lixo do Python, virou ~**50 desvios** e os 4 multivariados alarmaram juntos, com taxa e latência normais. O único piso era técnico (σ < 1e-9 → 1). É o mesmo mecanismo do σ ≈ 0 das notas, em outro lugar.

**A correção (`DETECTOR_FEATURE_FLOOR`, padrão 0,01; 0 = desligado):** σ_entrada = máx(σ, piso·|μ|), por feature. Com 1% de 82,7 MB = 0,83 MB, os 0,25 MB viram ~0,3σ: sem alarme. Latência, CPU e taxa têm σ real bem acima de 1% da média e quase não mudam. Vale para IF, LOF, DBSCAN, AE e LSTM (o EWMA usa a latência bruta). O `make selftest` (`test_feature_floor`) confere. Validação: [seção 8](#8-validação-do-piso-nas-entradas).

### Piso relativo do σ

**O problema:** com a referência quase constante (cluster ocioso), o σ das notas vai a ~0 e qualquer variação mínima vira uma razão enorme. No Grafana do piloto 2, o AE chegou a ~10⁵.

**A correção (`DETECTOR_SIGMA_FLOOR` = **0,05**, decidido em 16/out; 0 = desligado):** o σ usado no limiar nunca é menor que uma fração da média: σ_ef = máx(σ, piso·|μ|). Vale para IF, LOF, AE e LSTM; EWMA e DBSCAN não usam essa razão.

**Exemplo:** μ = 0,001, σ = 1e-7, e o ponto atual 2% acima da média (nota = 0,00102, diferença = 2e-5), com K = 2:
- sem piso: 2e-5 / (2 × 1e-7) = **100** → alerta;
- com piso 0,05: σ_ef = máx(1e-7, 0,05 × 0,001) = 5e-5; 2e-5 / (2 × 5e-5) = **0,2** → normal.

Uma variação grande (50%) continua alarmando com piso (razão 5). O `make selftest` (`test_sigma_floor`) confere esses números.

O AE é retreinado a cada `DETECTOR_AE_RETRAIN` passos (12 = 1 min), porque treinar uma rede a cada 5 s seria caro. Os outros são reajustados a cada passo.

### O que é publicado

| Métrica | Valor | Uso |
|---|---|---|
| `anomaly_score{detector}` | razão (>1 = alerta) | Grafana |
| `anomaly_alert{detector}` | 0 ou 1 a cada passo | vira a coluna `online_<DET>` do CSV e é avaliado (F1 etc.) |
| `anomaly_level{detector}` | média dos últimos `DETECTOR_LEVEL_POINTS` alertas (3): 0; 0,33; 0,67; 1 | lido pelo HPA no modo B, via Prometheus Adapter |

Os 6 publicam sempre. O HPA, quando está no modo B, lê **só** o `anomaly_level` do detector escolhido (`HPA_B_DETECTOR`).

## 2. Como os alertas viram resultado

```
durante a carga:  app ──métricas──▶ Prometheus ──▶ pod online-detector (6 algoritmos)
                                        ▲                       │
                                        └──── alertas (5) ──────┘
depois da carga:  Prometheus ──▶ CSV (métricas + label + online_*) ──▶ detectors.py ──▶ F1 dos 10
```

1. No fim da carga, o `export_metrics.py` puxa do Prometheus as 4 métricas, o `label` (gabarito do roteiro do k6) e as 5 séries `anomaly_alert`, alinhadas nos mesmos instantes de 5 s.
2. O `detectors.py` **roda** os 6 offline sobre as 4 métricas e **apenas pontua** as colunas `online_*`, que já são decisões tomadas ao vivo. As duas pontuações usam o mesmo código de precisão, recall, F1 e MTTD.

O HPA não participa disso: na Fase 1 ele fica no modo A (só CPU).

## 3. Três formas de usar os mesmos algoritmos

| Forma | Vê | Treina em | Atraso do cluster | Onde aparece |
|---|---|---|---|---|
| **Offline** | a execução inteira, depois que terminou | a execução inteira (anomalias incluídas) | não | `<DET>` em `detection_results.csv` |
| **Online ao vivo** | só o passado | janela de 5 min, 30 s antes do ponto | **sim** | `<DET>_online` em `detection_results.csv` |
| **Replay** | só o passado | igual ao online | não | `make online-replay` |

O replay separa duas perguntas: *"o procedimento online é bom?"* (replay × offline) e *"quanto o cluster custa?"* (ao vivo × replay).

## 4. Por que o online pode superar o offline

São os mesmos algoritmos, mas a pergunta é outra:

1. **O que é "normal" (masking).** O offline treina na execução inteira. No burst, cerca de 17% dos pontos são anômalos, e o modelo aprende os picos como parte do normal, deixando de estranhá-los. O online treina no passado recente, ainda limpo quando o pico começa.
2. **O limiar.** IF e LOF offline usam `contamination = 0,1`: marcam sempre os 10% de pontos mais estranhos, haja ou não anomalia. O online marca o que foge de μ + K·σ da janela recente, seja qual for a proporção.
3. **Carga que muda.** O offline faz um modelo único para todos os regimes da execução. A janela se adapta ao regime atual (pesa mais no rampup e no shift).

**Exceção: EWMA.** Já é sequencial por natureza (sempre compara com uma média do passado), então a janela pouco acrescenta.

## 5. Limitações

### Anomalias longas

Se a anomalia dura mais que o gap + a janela, ela entra na referência e o detector **se acostuma**: para de alertar no meio dela. No shift, as janelas anômalas duram 150 s. Os pontos finais delas já têm parte da anomalia na referência.

### LSTM: pouco dado na janela

A referência tem 60 pontos (5 min); com sequências de 12, sobram ~48 exemplos de treino. É pouco para uma rede neural: ela aprende o padrão de curto prazo, não sazonalidades nem regimes longos. A arquitetura pequena (16 unidades, 30 épocas) é proposital, para não decorar esses poucos exemplos. Aumentar a janela daria mais dados, mas deixaria o detector mais lento para se adaptar (decisão em aberto: janela do detector).

### Custo da observação

O detector online também é uma carga no sistema que ele observa:

- **um pod para os 6:** o `online-detector` é um único programa Python. A cada 5 s ele faz **uma** consulta ao Prometheus (as 4 métricas do mesmo instante), calcula EWMA, IF, LOF, DBSCAN, AE e LSTM **em sequência** e publica os 6 alertas juntos, no fim do ciclo;
- **disputa CPU com a aplicação:** o pod roda dentro do cluster, nos mesmos núcleos (`CLUSTER_CPUS`) que a app, com limite de 0,5 núcleo. A disputa é **igual nos 3 modos do HPA**, então não favorece nenhum; mas existe;
- **o ciclo é único:** um detector pesado (LSTM, AE, nos ciclos de retreino) atrasa a publicação de **todos** os alertas, inclusive o do detector que o HPA usa no modo B. Entre os detectores não há atraso relativo (saem juntos), mas o atraso absoluto vale para todos;
- **o laboratório é o pior caso:** em produção rodaria só o detector escolhido. Aqui rodam os 6, para avaliá-los sobre exatamente os mesmos dados ("mesma foto").

**Medido:** em cada piloto e na Fase 1, a CPU do pod `online-detector` e o p95 de `detector_step_seconds` (`make detector-ciclo`; ao fim de `make experiment` e `make hpa-experiment` o resultado é salvo em `results/detector_ciclo_<fase>.txt`). No replay com 0,5 núcleo: ciclo médio 0,47 s, p95 1,13 s (seção 7).

**Em aberto (decidir com o piloto 4):** na Fase 3, rodar **só** o detector do modo B (`DETECTOR_ALGOS=<HPA_B_DETECTOR>`, mais o do D se houver). A Fase 3 não calcula F1, então os outros 5 só gastariam CPU disputando com a app. Fica igual a produção e continua justo entre A, B e C.

### Atraso ao vivo

Cada alerta passa por uma cadeia:
1. o Prometheus coleta a app (5 s);
2. o detector consulta, calcula e publica (5 s);
3. o Prometheus coleta o alerta (5 s).

O alerta chega alguns segundos depois do fato. A avaliação é ponto a ponto, então o atraso é penalizado duas vezes:
- **no começo** da janela anômala, o alerta ainda não chegou: falso negativo (cai o recall);
- **depois do fim**, o alerta ainda toca: falso positivo (cai a precisão).

O replay não sofre isso. A diferença ao vivo × replay estima o custo do atraso.

**Medir o atraso:** desloque os alertas ao vivo para trás de k passos e veja onde o F1 é máximo. Roda na imagem de análise:

```bash
cat > /tmp/lag.py <<'EOF'
import sys, pandas as pd, numpy as np
d = pd.read_csv(sys.argv[1]); y = d["label"].values.astype(int)
cols = [c for c in d.columns if c.startswith("online_")]
print("F1 do alerta online deslocado k passos para trás (k × 5 s)")
print("det     " + "".join(f"  k={k:<4}" for k in range(7)))
for c in cols:
    a = (d[c].fillna(0).values > 0).astype(int); row = []
    for k in range(7):
        p = np.r_[a[k:], np.zeros(k, int)]
        tp = int((p & y).sum()); fp = int((p & (1 - y)).sum()); fn = int(((1 - p) & y).sum())
        row.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    print(f"{c[7:]:<8}" + "".join(f"  {v:.3f} " for v in row))
EOF
docker run --rm -i -v $PWD/datasets:/datasets anomaly-lab/analysis:latest - /datasets/burst_run1.csv < /tmp/lag.py
```

- Pico do F1 em k = 2–3 para todos: o atraso do pipeline é de 10–15 s.
- Pico em k = 0: não é atraso; a diferença vem de outra fonte (por exemplo, dados ao vivo diferentes do CSV exportado).

### Decisão de método (a fixar ANTES do experimento definitivo)

Há duas formas honestas de reportar o online:

1. **Como ele é, atraso incluído.** É o que o HPA realmente recebe e o número relevante para a Fase 3.
2. **Também com uma tolerância fixa** (por exemplo, alertas até X s após o fim da janela contam como acerto), para separar a qualidade do algoritmo do custo da infraestrutura.

A tolerância, se usada, é decidida agora e escrita no método. Não pode ser escolhida olhando os resultados finais. O mesmo vale para o K: foi escolhido nos dados da qualificação (K = 2) e não é reajustado na Fase 1 definitiva.

## 6. Validação do piso

Replay dos 9 CSVs reais da qualificação (3 cenários × 3 repetições), com piso 0 e com piso 0,05; F1 ponto a ponto, média das 3 repetições. Dados: [validacao/piso_sigma.csv](validacao/piso_sigma.csv) (médias, com precisão, recall e alarmes) e [validacao/piso_sigma_por_execucao.csv](validacao/piso_sigma_por_execucao.csv).

| Cenário | Detector | F1 piso 0 | F1 piso 0,05 | Diferença |
|---|---|---|---|---|
| burst | EWMA | 0,337 | 0,337 | 0 |
| burst | IF | 0,462 | 0,462 | 0 |
| burst | LOF | 0,387 | 0,391 | +0,003 |
| burst | DBSCAN | 0,601 | 0,601 | 0 |
| burst | AE | 0,614 | 0,614 | 0 |
| rampup | EWMA | 0,193 | 0,193 | 0 |
| rampup | IF | 0,471 | 0,471 | 0 |
| rampup | LOF | 0,500 | 0,500 | 0 |
| rampup | DBSCAN | 0,527 | 0,527 | 0 |
| rampup | AE | 0,514 | 0,514 | 0 |
| shift | EWMA | 0,071 | 0,071 | 0 |
| shift | IF | 0,152 | 0,152 | 0 |
| shift | LOF | 0,215 | 0,210 | -0,005 |
| shift | DBSCAN | 0,232 | 0,232 | 0 |
| shift | AE | 0,337 | 0,337 | 0 |

**Leitura:** o F1 **não mudou** em 14 de 15 combinações; só o LOF variou (+0,003 no burst, −0,005 no shift), dentro do ruído. Com piso 0, o replay reproduz exatamente o `results_qualificacao/online_replay_K2.csv` (45/45), ou seja, o código sem piso é o mesmo de antes. O piso não custa F1 com carga, mas esta validação **não mostra o benefício dele**: esses CSVs não têm trechos de cluster ocioso (σ ≈ 0), que é onde ele age. O benefício aparece ao vivo (piloto 3: `make check-inicio` e Grafana).

**Decisão (16/out): piso = 0,05.** Motivo: no regime com carga ele não alterou o F1 (tabela acima), e com o cluster quase ocioso ele impede as razões de ~10⁵ que o piloto 2 mostrou. É uma proteção sem custo medido. Fixado antes do experimento definitivo e não reajustado depois.

## 7. Validação do LSTM

Os 9 CSVs reais da qualificação (3 cenários × 3 repetições), **sem cluster**: LSTM offline (`detectors.py`) e replay online (`online_detector.py`, piso 0,05), junto com os outros 5. F1 ponto a ponto, média das 3 repetições. Dados: [validacao/lstm_qualificacao.csv](validacao/lstm_qualificacao.csv) (com precisão e recall), [por execução](validacao/lstm_qualificacao_por_execucao.csv) e [tempo de ciclo](validacao/lstm_qualificacao_ciclo.csv).

| Detector | burst offline | burst replay | rampup offline | rampup replay | shift offline | shift replay |
|---|---|---|---|---|---|---|
| EWMA | 0,431 | 0,337 | 0,425 | 0,193 | 0,059 | 0,071 |
| IF | 0,467 | 0,462 | 0,184 | 0,471 | 0,242 | 0,152 |
| LOF | 0,100 | 0,391 | 0,035 | 0,500 | 0,254 | 0,210 |
| DBSCAN | 0,256 | 0,601 | 0,158 | 0,527 | 0,205 | 0,232 |
| AE | 0,366 | 0,614 | 0,145 | 0,514 | 0,189 | 0,337 |
| **LSTM** | **0,336** | **0,605** | **0,043** | **0,453** | **0,113** | **0,379** |

**Leitura (N = 3, padrão, não conclusão):**
- **Online (replay):** o LSTM fica entre os melhores. No burst, 0,605, empatado com AE (0,614) e DBSCAN (0,601). No rampup, 0,453, abaixo dos outros multivariados (0,47–0,53). No **shift**, 0,379, o **melhor dos 6**. É o cenário em que a anomalia está na *mudança de perfil*, e é onde a dimensão temporal mais ajuda.
- **Offline:** fraco (0,04–0,34), como AE e LOF offline. Treinando na execução inteira, ele aprende os picos como "normal" (*masking*, seção 4) e o limiar μ + 2σ marca poucos pontos (precisão alta, recall baixo).
- **Os outros 5 não mudaram:** offline idêntico ao `results_qualificacao/detection_results.csv` (45/45) e replay idêntico à validação do piso (45/45).

**Tempo de ciclo** (replay com o mesmo limite do pod: 0,5 núcleo; 1.485 ciclos; 6 detectores):

| Versão | média | p95 | máximo | limite |
|---|---|---|---|---|
| retreino do LSTM **defasado** 6 passos do AE (adotada) | 0,47 s | **1,13 s** | 3,92 s | 5 s |
| 1ª versão: retreinos de AE e LSTM no mesmo ciclo (descartada) | 0,47 s | 1,27 s | 4,81 s | 5 s |

Na 1ª versão, os ciclos com os dois retreinos juntos levavam 1,2–1,8 s em média e chegavam perto do limite. Defasar o retreino do LSTM meio período (o AE retreina num ciclo, o LSTM 6 ciclos depois) resolveu sem mudar `LSTM_RETRAIN` (12) nem a arquitetura. O PyTorch também passou a ser carregado na partida do serviço, não no 1º ciclo. **Memória:** pico de ~410 MiB no processo de validação; o limite do pod subiu de 384 Mi para 768 Mi (`k8s/detector/online-detector.yaml`) para não ser morto por falta de memória.

**Parâmetros:** nenhum foi mudado por causa desta validação (`LSTM_SEQ_LEN` = 12, `LSTM_HIDDEN` = 16, `LSTM_EPOCHS` = 30, `LSTM_RETRAIN` = 12, semente 42).

## 8. Validação do piso nas entradas

Replay dos 9 CSVs da qualificação com os 6 detectores e o piso das notas em 0,05, com piso nas entradas 0 e 0,01; F1 ponto a ponto, média das 3 repetições. Dados: [validacao/piso_entrada.csv](validacao/piso_entrada.csv) (com precisão, recall e alarmes) e [por execução](validacao/piso_entrada_por_execucao.csv).

| Cenário | Detector | F1 piso 0 | F1 piso 0,01 | Diferença |
|---|---|---|---|---|
| burst | EWMA | 0,337 | 0,337 | 0 |
| burst | IF | 0,462 | 0,462 | 0 |
| burst | LOF | 0,391 | 0,382 | -0,009 |
| burst | DBSCAN | 0,601 | 0,601 | 0 |
| burst | AE | 0,614 | 0,597 | -0,017 |
| burst | LSTM | 0,605 | 0,606 | 0 |
| rampup | EWMA | 0,193 | 0,193 | 0 |
| rampup | IF | 0,471 | 0,471 | 0 |
| rampup | LOF | 0,500 | 0,500 | 0 |
| rampup | DBSCAN | 0,527 | 0,527 | 0 |
| rampup | AE | 0,514 | 0,517 | +0,003 |
| rampup | LSTM | 0,453 | 0,451 | -0,002 |
| shift | EWMA | 0,071 | 0,071 | 0 |
| shift | IF | 0,152 | 0,152 | 0 |
| shift | LOF | 0,210 | 0,205 | -0,005 |
| shift | DBSCAN | 0,232 | 0,225 | -0,008 |
| shift | AE | 0,337 | 0,365 | +0,028 |
| shift | LSTM | 0,379 | 0,356 | -0,023 |

**Leitura:** com piso 0, o replay é idêntico ao da validação do LSTM (54/54), ou seja, o código sem piso não mudou. Com 0,01, o F1 ficou igual em 10 das 18 combinações e mudou pouco nas outras, **nos dois sentidos** (de −0,023 a +0,028; média −0,002): AE melhora no shift (+0,028), LSTM e AE perdem um pouco no shift/burst (−0,023 e −0,017). EWMA, IF e LOF/DBSCAN no rampup não mudam. Não há perda sistemática; as variações estão no tamanho do ruído com N = 3. Ao contrário do piso das notas, este piso **age** com carga, em trechos em que alguma feature fica quase constante (na qualificação, sobretudo a memória). O benefício principal, o fim do alarme por salto de memória, só aparece ao vivo (piloto 4: `make check-inicio`).

## 9. Resultados preliminares (não conclusivos)

**Uma execução** (burst, run 1, N = 1). Não há IC nem teste com N = 1; serve só para ver o padrão.

| Detector | Offline | Replay | Ao vivo |
|---|---|---|---|
| EWMA | 0,49 | 0,42 | 0,22 |
| IF | 0,50 | 0,63 | 0,45 |
| LOF | 0,30 | 0,52 | 0,31 |
| DBSCAN | 0,44 | 0,67 | 0,34 |
| AE | 0,08 | 0,60 | 0,34 |

Leitura: o replay supera o offline em 4 de 5 detectores; ao vivo perde cerca de 0,2 de F1 em relação ao replay, quase toda em precisão (padrão de atraso). No replay dos 9 CSVs da qualificação (N = 3), o padrão foi parecido no burst e no rampup, mas no shift o online não ajudou: IF (0,24 → 0,15) e LOF (0,25 → 0,22) pioraram e o DBSCAN ficou praticamente igual (0,21 → 0,23), coerente com a limitação das anomalias longas. As 10 repetições dirão se isso se sustenta.

## 10. Variáveis do `.env`

| Variável | Padrão | O que controla |
|---|---|---|
| `DETECTOR_ALGOS` | `EWMA,IF,LOF,DBSCAN,AE,LSTM` | algoritmos que rodam (aceitos: esses 6) |
| `DETECTOR_STEP_SECONDS` | `5` | intervalo entre decisões |
| `DETECTOR_WINDOW` | `60` | tamanho da referência (60 × 5 s = 5 min) |
| `DETECTOR_GAP` | `6` | pontos recentes fora da referência (30 s) |
| `DETECTOR_K_SIGMA` | `2` | K do limiar μ + K·σ (IF, LOF, AE, LSTM); menor = mais alertas |
| `DETECTOR_SIGMA_FLOOR` | `0.05` | piso relativo do σ: σ_ef = máx(σ, piso·\|μ\|) (IF, LOF, AE, LSTM); `0` = desligado |
| `DETECTOR_FEATURE_FLOOR` | `0.01` | piso relativo na padronização das entradas: σ_entrada = máx(σ, piso·\|μ\|) (IF, LOF, DBSCAN, AE, LSTM); `0` = desligado |
| `DETECTOR_LEVEL_POINTS` | `3` | alertas usados no `anomaly_level` |
| `DETECTOR_AE_RETRAIN` | `12` | retreino do AE (passos) |
| `LSTM_SEQ_LEN` | `12` | pontos anteriores usados na previsão (1 min) |
| `LSTM_HIDDEN` | `16` | unidades da camada LSTM |
| `LSTM_EPOCHS` | `30` | épocas de treino (Adam, lote único) |
| `LSTM_RETRAIN` | `12` | retreino da LSTM no online (passos); aumentar se o ciclo ficar lento |

Depois de mudar qualquer uma: `make detector-deploy` (só recria o pod se a configuração mudou). Nunca mude durante um experimento.

Fora do detector, mas ligado a ele: `WARMUP_SECONDS` (padrão `330`; `0` desliga), o aquecimento antes de cada execução, lido pelo `bin/experiment.sh`.

## 11. Código

- `scripts/online_detector.py`: o serviço (classe `OnlineDetector`) e o modo `--replay` (que também mostra o tempo por ciclo: média, p95, máximo).
- `scripts/lstm_model.py`: a LSTM preditiva (usada pelo offline e pelo online).
- `scripts/prom_queries.py`: as consultas PromQL das 4 métricas (as mesmas do offline).
- `scripts/export_metrics.py`: exporta as colunas `online_<DET>`.
- `scripts/detectors.py`: pontua `online_<DET>` como `<DET>_online`.
- `scripts/check_inicio.py` (`make check-inicio`): alertas antes da 1ª anomalia de cada CSV.
- `k6-scripts/warmup.js` e `bin/experiment.sh` (`warmup`): o aquecimento antes de cada execução.
- `k8s/detector/online-detector.yaml`: Deployment e Service do pod.
- Dashboard Grafana **"Detector Online & HPA"**: scores, alertas, níveis e réplicas.