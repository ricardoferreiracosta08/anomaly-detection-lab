# Detector online (Fase 2)

## TL;DR

- **O quê:** um pod no cluster (`online-detector`) roda os **mesmos 5 algoritmos** da Fase 1 (EWMA, IF, LOF, DBSCAN, AE), mas de outro jeito: a cada 5 s, cada um é ajustado só no **passado recente** e decide se o ponto **de agora** é anômalo.
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

**Aquecimento:** o detector só decide quando a referência tem pelo menos 20 pontos. Até lá (cerca de 130 s depois que o pod sobe), publica 0. A janela cresce até 60 pontos e daí desliza.

### A decisão de cada algoritmo

Cada algoritmo produz uma **razão** (`anomaly_score`): **acima de 1 = alerta**.

| Algoritmo | Razão | Equivale a |
|---|---|---|
| IF, LOF, AE | (nota do ponto − μ) / (K·σ), com μ e σ das notas da própria referência | nota > μ + K·σ (`DETECTOR_K_SIGMA`, K = 2) |
| EWMA | \|média suavizada − μ\| / (3σ) da latência na referência (λ = 0,3) | fora de μ ± 3σ (K não se aplica) |
| DBSCAN | distância ao ponto-núcleo mais próximo / eps (eps = P90 da k-distância na referência) | longe de qualquer região densa (K não se aplica) |

O AE é retreinado a cada `DETECTOR_AE_RETRAIN` passos (12 = 1 min), porque treinar uma rede a cada 5 s seria caro. Os outros são reajustados a cada passo.

### O que é publicado

| Métrica | Valor | Uso |
|---|---|---|
| `anomaly_score{detector}` | razão (>1 = alerta) | Grafana |
| `anomaly_alert{detector}` | 0 ou 1 a cada passo | vira a coluna `online_<DET>` do CSV e é avaliado (F1 etc.) |
| `anomaly_level{detector}` | média dos últimos `DETECTOR_LEVEL_POINTS` alertas (3): 0; 0,33; 0,67; 1 | lido pelo HPA no modo B, via Prometheus Adapter |

Os 5 publicam sempre. O HPA, quando está no modo B, lê **só** o `anomaly_level` do detector escolhido (`HPA_B_DETECTOR`).

## 2. Como os alertas viram resultado

```
durante a carga:  app ──métricas──▶ Prometheus ──▶ pod online-detector (5 algoritmos)
                                        ▲                       │
                                        └──── alertas (5) ──────┘
depois da carga:  Prometheus ──▶ CSV (métricas + label + online_*) ──▶ detectors.py ──▶ F1 dos 10
```

1. No fim da carga, o `export_metrics.py` puxa do Prometheus as 4 métricas, o `label` (gabarito do roteiro do k6) e as 5 séries `anomaly_alert`, alinhadas nos mesmos instantes de 5 s.
2. O `detectors.py` **roda** os 5 offline sobre as 4 métricas e **apenas pontua** as colunas `online_*`, que já são decisões tomadas ao vivo. As duas pontuações usam o mesmo código de precisão, recall, F1 e MTTD.

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

## 6. Resultados preliminares (não conclusivos)

**Uma execução** (burst, run 1, N = 1). Não há IC nem teste com N = 1; serve só para ver o padrão.

| Detector | Offline | Replay | Ao vivo |
|---|---|---|---|
| EWMA | 0,49 | 0,42 | 0,22 |
| IF | 0,50 | 0,63 | 0,45 |
| LOF | 0,30 | 0,52 | 0,31 |
| DBSCAN | 0,44 | 0,67 | 0,34 |
| AE | 0,08 | 0,60 | 0,34 |

Leitura: o replay supera o offline em 4 de 5 detectores; ao vivo perde cerca de 0,2 de F1 em relação ao replay, quase toda em precisão (padrão de atraso). No replay dos 9 CSVs da qualificação (N = 3), o padrão foi parecido no burst e no rampup, mas no shift o online não ajudou: IF (0,24 → 0,15) e LOF (0,25 → 0,22) pioraram e o DBSCAN ficou praticamente igual (0,21 → 0,23), coerente com a limitação das anomalias longas. As 10 repetições dirão se isso se sustenta.

## 7. Variáveis do `.env`

| Variável | Padrão | O que controla |
|---|---|---|
| `DETECTOR_ALGOS` | `EWMA,IF,LOF,DBSCAN,AE` | algoritmos que rodam (aceitos: esses 5) |
| `DETECTOR_STEP_SECONDS` | `5` | intervalo entre decisões |
| `DETECTOR_WINDOW` | `60` | tamanho da referência (60 × 5 s = 5 min) |
| `DETECTOR_GAP` | `6` | pontos recentes fora da referência (30 s) |
| `DETECTOR_K_SIGMA` | `2` | K do limiar μ + K·σ (IF, LOF, AE); menor = mais alertas |
| `DETECTOR_LEVEL_POINTS` | `3` | alertas usados no `anomaly_level` |
| `DETECTOR_AE_RETRAIN` | `12` | retreino do AE (passos) |

Depois de mudar qualquer uma: `make detector-deploy` (só recria o pod se a configuração mudou). Nunca mude durante um experimento.

## 8. Código

- `scripts/online_detector.py`: o serviço (classe `OnlineDetector`) e o modo `--replay`.
- `scripts/prom_queries.py`: as consultas PromQL das 4 métricas (as mesmas do offline).
- `scripts/export_metrics.py`: exporta as colunas `online_<DET>`.
- `scripts/detectors.py`: pontua `online_<DET>` como `<DET>_online`.
- `k8s/detector/online-detector.yaml`: Deployment e Service do pod.
- Dashboard Grafana **"Detector Online & HPA"**: scores, alertas, níveis e réplicas.