# HPA: modos, experimento e análise (Fases 2 e 3)

## TL;DR

- **Pergunta da Fase 3:** um HPA que também escuta o detector de anomalias (modo **B**) reage mais cedo e degrada menos a latência do que o HPA padrão por CPU (modo **A**)? E esse ganho vem **do detector** ou só de escalar mais (modo **C**)?
- **Como:** os 3 modos × 3 cargas × `REPS` repetições, em ordem sorteada (`make hpa-experiment`). Cada execução gera uma linha de métricas; a estatística compara os modos par a par, por cenário.
- **Métrica principal** (definida antes de rodar): **tempo de reação** (início da anomalia → HPA pede mais réplicas).
- **Detector do modo B:** o melhor da Fase 1, fixado em `HPA_B_DETECTOR` **antes** da Fase 3 e não trocado depois.

```bash
make hpa-mode HPA_MODE=B && make phase2-check   # B recebe a métrica de anomalia?
make hpa-experiment                              # Fase 3 completa (≈ 32 h com REPS=10, aquecimento incluído)
less results/stats/phase3/relatorio.md           # resultado
```

---

## 1. Como o HPA decide

O HPA olha suas métricas periodicamente (a cada 15 s) e calcula, **para cada métrica**, quantas réplicas seriam necessárias. Depois usa **a maior** delas, dentro dos limites `minReplicas=2` e `maxReplicas=8`.

**Pela CPU** (todos os modos):

```
réplicas desejadas = ceil( réplicas atuais × CPU média / alvo )
```

A CPU é medida em relação ao `request` do pod (100m). Alvo 50% = 50m de uso médio por pod.

**Pela anomalia** (modos B e D): o detector online publica `anomaly_level`, a fração de alertas nos últimos 3 pontos (0; 0,33; 0,67; 1). O Prometheus Adapter entrega esse valor ao HPA como métrica externa, com alvo `ANOMALY_TARGET=500m` (0,5):

```
réplicas desejadas = ceil( réplicas atuais × anomaly_level / 0,5 )
```

| `anomaly_level` | Com 2 réplicas | Efeito |
|---|---|---|
| 0 ou 0,33 (0 ou 1 alerta em 3) | 0 ou 2 | nada (CPU decide) |
| 0,67 (2 alertas em 3) | 3 | +1 réplica |
| 1 (3 alertas em 3) | 4 | dobra |

Como o HPA usa a maior das duas, **o detector só antecipa o scale-up; nunca impede** o escalonamento por CPU. Se o detector errar para menos, o modo B se comporta como o A.

**Comportamento** (igual em todos os modos, para a comparação ser justa):
- **Subida:** espera 30 s de estabilização; no máximo +2 pods a cada 60 s.
- **Descida:** espera 120 s; no máximo −1 pod a cada 60 s.

## 2. Os modos

| Modo | O HPA decide por | Manifesto | Papel no experimento |
|---|---|---|---|
| **A** | CPU > 50% | `k8s/hpa/hpa-cpu.yaml` | **referência**: o HPA padrão, reativo |
| **B** | CPU > 50% **ou** anomalia (`HPA_B_DETECTOR`) | `k8s/hpa/hpa-anomaly.yaml` | **tratamento**: o HPA proativo, a proposta da dissertação |
| **C** | CPU > 35% (`HPA_C_CPU_TARGET`) | `k8s/hpa/hpa-cpu.yaml` | **controle**: escalar mais cedo **sem** detector |
| D (opcional) | CPU > 50% **ou** anomalia (`HPA_D_DETECTOR`) | `k8s/hpa/hpa-anomaly.yaml` | **ablação**: outro detector no lugar do de B |

A troca é feita na hora, sem reiniciar nada: `make hpa-mode HPA_MODE=X`. O modo atual fica na etiqueta `hpa-mode` do HPA (`make hpa-status`).

### Por que existe o modo C

Suponha que o B vença o A: reage mais cedo e a latência sobe menos. A banca vai perguntar: **"foi o detector, ou o B simplesmente liga mais pods?"** Qualquer HPA que escale mais cedo vai reagir antes e gastar mais. Para separar as duas explicações, é preciso um concorrente que escale mais cedo **sem detector nenhum**. O jeito mais simples é baixar o alvo de CPU: é o modo C.

Leitura dos resultados:

| Resultado | Conclusão |
|---|---|
| B reage antes que A **e** antes que C | o detector antecipa algo que a CPU não vê: ganho real do detector |
| B ≈ C no tempo de reação, mas B gasta menos pod·s ou tem menos scale-ups falsos | mesmo ganho por um custo menor: o detector escala na hora certa, não sempre |
| C ≥ B em tudo | o ganho do B era só escalar mais; o detector não se paga |

O valor 35% é um ponto de partida. O ideal é calibrar o C para gastar **mais ou menos o mesmo** pod·s que o B, e aí comparar só a qualidade da reação. Uma forma: rodar um piloto (`make hpa-experiment REPS=2`), olhar `pod_seconds` de B e C, ajustar `HPA_C_CPU_TARGET` e só então rodar a Fase 3 definitiva. Vale combinar isso com o orientador.

### O modo D

**Não usado na dissertação** (decisão de 29/out/2026, [DECISOES_METODO.md](DECISOES_METODO.md), item 5): a Fase 3 roda só A, B e C. O código continua disponível. Opcional (só roda se `D` estiver em `HPA_MODES`). Mesma regra do B com outro detector, por padrão o EWMA (univariado, só latência) contra o do B (multivariado). Responde: "o tipo de detector importa para o HPA?". Comparação gerada: D × B.

## 3. Escolha do detector do modo B (pré-registro)

1. Rode a Fase 1 completa (`make experiment`).
2. Escolha o detector pelo **F1 online** (linhas `<DET>_online` em `results/stats/phase1/relatorio.md` e na aba `1_IC_detectores` de `estatistica.xlsx`; dados brutos em `results/detection_results.csv`), com a regra abaixo, **registrada em 16/out/2026, antes da Fase 1**:

   > **Regra de escolha do detector do modo B.**
   > 1. Para cada detector, calcule a média do F1 **online** em cada cenário (burst, rampup, shift) e depois a **média das 3 médias**: cada cenário pesa igual, e ninguém ganha por ser ótimo numa carga só.
   > 2. Escolhe-se o de **maior média das 3 médias**.
   > 3. **Empate:** o **grupo de empate** é o 1º mais **todos** os detectores online cuja diferença para o 1º **não é significativa em nenhum dos 3 cenários** (teste pareado, decisão 1 de `DECISOES_METODO.md`, α = 0,05). Se o grupo tem só o 1º, ele fica. Se tem mais de um, vence o de **menor MTTD online** (média das 3 médias) dentro do grupo, seja ele o 1º, o 2º ou outro.
   > 4. **MTTD:** numa execução, as janelas anômalas **não detectadas ficam fora da média** (o MTTD só existe onde houve alerta); o número de janelas detectadas (ex.: 96/100 na Fase 1: 3, 4 e 3 janelas por execução × 10) é reportado ao lado, para não premiar quem detecta pouco mas rápido.
   > 5. **Requisito:** p95 do ciclo < 2,5 s. **Verificado pelo ciclo do pod com os 6 detectores juntos** (piloto 4: 0,48 s): como os 6 rodam no mesmo ciclo, qualquer um cumpre.
   >
   > O relatório da Fase 1 aplica a regra sozinho e escreve a escolha (seção "Comparações planejadas").

   Por que o MTTD desempata: para o HPA, detectar antes é escalar antes.
3. Fixe no `.env`: `HPA_B_DETECTOR=<escolhido>`. Pode ser qualquer um dos 6: EWMA, IF, LOF, DBSCAN, AE ou **LSTM** (o 6º, temporal). O `make hpa-mode` recusa um detector fora de `DETECTOR_ALGOS`. Se for o LSTM, confira antes no painel "Saúde do detector" que o p95 do ciclo está bem abaixo de 5 s (piloto 4, [PILOTOS.md](PILOTOS.md)).
4. Não troque depois de ver a Fase 3. Trocar o detector após ver o resultado invalida o teste estatístico (seria escolher o que deu certo).

## 4. O que é medido em cada execução

### Condição inicial: igual em todos os modos

Antes de **cada** execução da Fase 3, o `bin/experiment.sh` faz sempre a mesma sequência (a Fase 1 faz a mesma, já no modo A):

1. aplica o **modo A** (só CPU);
2. **reinicia a app** (`rollout restart deploy/fastapi-app`) e espera o rollout: pods novos, com os 100 itens da semente;
3. espera as réplicas no mínimo (2) e aplica o `COOLDOWN`;
4. roda o **aquecimento** (`WARMUP_SECONDS`, padrão 330 s: carga normal constante do cenário, sem CSV), ainda no modo A, terminando com uma descida de 30 s;
5. 15 s antes dessa descida, confere as réplicas, lê o `anomaly_level` do detector do B (`HPA_B_DETECTOR`), como o HPA o veria pelo Adapter, e os **itens por pod** da app;
6. **só então** aplica o modo da execução (B, C ou D; no A nada muda);
7. o roteiro começa **30 s antes do fim do aquecimento**: o aquecimento desce (10 → 0 VUs) enquanto o roteiro sobe (0 → 10), e a carga total fica constante na troca.

**Interruptores no `.env`** (para desligar uma correção sem mexer no código, se um piloto mostrar problema): `RESTART_APP=0` não reinicia a app; `WARMUP_OVERLAP=0` tira a sobreposição; `WARMUP_SECONDS=0` tira o aquecimento.

**Por quê:** o aquecimento serve para o detector aprender "normal com carga" ([DETECTOR_ONLINE.md](DETECTOR_ONLINE.md)), mas a passagem "cluster parado → aquecimento" pode gerar alarmes. Se o aquecimento rodasse já no modo B, esses alarmes fariam o B escalar **antes** do roteiro, e as execuções do B começariam com mais réplicas que as do A e do C. Aquecendo sempre no modo A, **toda execução começa com 2 réplicas**, qualquer que seja o modo.

**Por que reiniciar a app:** ela guarda os itens em memória, por pod, e cada POST acrescenta um; `/report`, `/search` e o GET leve percorrem todos. Sem reiniciar, cada execução herdava o estado das anteriores (piloto 3: 4.055 e 3.850 itens por pod, contra 100 da semente; memória no início A 82,7 → C 85,7 → B 89,1 MB, na ordem em que rodaram). Isso é um **viés de ordem**, que vale para as duas fases. O reinício também tira o "pod frio" dos 2 pods base, porque o aquecimento de 330 s vem depois dele.

**Por que sobrepor as rampas:** os roteiros começam do zero (rampa de 30 s). Sem sobreposição, a carga caía e voltava na troca, e AE, DBSCAN e LOF alarmavam de 15 a 45 s em todas as execuções do piloto 3.

**Registro:** `results/warmup_log.csv`, uma linha por execução: réplicas ao fim do aquecimento (`at_min` = 1 se no mínimo), `anomaly_level_b`, `items_per_pod` (ex.: `112;108`; devem ser parecidos em todas as execuções do mesmo cenário) e `warmup_p95_ms`: o p95 da latência nos últimos 4 min do aquecimento, que roda sempre no modo A e por isso mede só o ambiente. Ele serve para mostrar, antes de olhar o tempo de reação, que a lentidão do dia ficou equilibrada entre A, B e C (decisão 14 em [DECISOES_METODO.md](DECISOES_METODO.md)). No shift, o tempo de reação conta só as janelas com reação, e `windows_no_reaction` e as réplicas ao fim do aquecimento vão ao lado (decisão 15). Um `anomaly_level_b` ≥ 0,5 indica que o B escalaria logo que aplicado, ou seja, alarme residual do aquecimento; vale olhar junto com `false_scaleups`.

**Acomodação inicial da avaliação (`EVAL_SKIP_SECONDS`): não se aplica à Fase 3.** O descarte dos primeiros 60 s vale só para a pontuação dos detectores na Fase 1 (F1, precisão, recall, MTTD). As métricas do HPA olham os picos (tempo de reação, latência e SLO nas janelas anômalas, que começam aos 150/175 s) e os scale-ups; nenhuma pontua alertas no trecho inicial. O `slo_viol_all_pct` (execução inteira) também não muda: é uma métrica de contexto, não a principal. Ver [DECISOES_METODO.md](DECISOES_METODO.md), item 11.

### Métricas

Cada execução (modo × cenário × repetição) gera **uma linha** em `results/hpa/hpa_results.csv` (`scripts/hpa_metrics.py`). As "janelas anômalas" são o ground truth do roteiro do k6 (as mesmas da Fase 1).

| Coluna | O que é | Melhor |
|---|---|---|
| `reaction_time_s` | **principal.** Início de cada janela anômala → 1º aumento das réplicas **desejadas**; média nas janelas | menor |
| `ready_time_s` | idem, até o 1º aumento das réplicas **disponíveis** (pod pronto) | menor |
| `windows_no_reaction` / `n_windows` | janelas sem nenhum scale-up (não entram na média do tempo de reação) | menor |
| `p95_anom_ms` | p95 da latência medida no servidor, só dentro das janelas anômalas | menor |
| `slo_viol_anom_pct` | % de requisições acima de 500 ms (`SLO_SECONDS`) nas janelas anômalas | menor |
| `slo_viol_all_pct` | idem, na execução inteira | menor |
| `pod_seconds` | **custo:** soma de réplicas disponíveis × tempo | menor |
| `scaleups` / `false_scaleups` | aumentos no total / fora das janelas anômalas (+60 s de tolerância) | menos falsos |
| `k6_p95_ms`, `k6_error_rate` | p95 e erros vistos pelo k6 (lado cliente) | menor |

**Cuidado com o tempo de reação indefinido.** O `reaction_time_s` mede quando o HPA pede **mais** pods do que tinha no início do pico. Se o sistema já está escalado quando o pico chega (por exemplo, depois de scale-ups falsos), não há aumento: a janela conta como "sem reação" e fica fora da média. "Não reagiu porque já estava preparado" e "não reagiu porque falhou" ficam iguais. Leia sempre junto com `windows_no_reaction`, `false_scaleups` e `pod_seconds` (ver [PILOTOS.md](PILOTOS.md), piloto 2).

### Por que a Fase 3 não calcula F1

A Fase 3 mede o **HPA** (reação, latência, custo), não a qualidade dos detectores. O F1 que vale para comparar e escolher detectores é o da **Fase 1**, com o HPA no modo A.

No modo **B**, o F1 nem seria comparável: o HPA reage ao detector, os pods extras baixam a latência e mudam os próprios dados que os detectores leem. É um circuito fechado: o detector influencia aquilo que está medindo.

Mesmo assim, os CSVs da Fase 3 (`datasets_hpa/`) têm as colunas `online_*` e o gabarito. Para calcular o F1 como observação (válido nas execuções do modo A), use um diretório de saída separado, para não sobrescrever o da Fase 1:

```bash
mkdir -p results/hpa/detect && chmod 777 results/hpa/detect
docker run --rm -v $PWD/datasets_hpa:/datasets_hpa -v $PWD/results:/results anomaly-lab/analysis:latest \
  detectors.py --input /datasets_hpa/ --output /results/hpa/detect/ --impute zero
```

## 5. Análise estatística

`make hpa-analyze` (já chamado no fim do `make hpa-experiment`) gera `results/stats/phase3/`:

- **IC da média por célula** (cenário × modo), para cada métrica: Ȳ ± t(0,975; N−1)·S/√N [AR, slides 49–52].
- **Comparações, por cenário e métrica, com t de Student** (p-valor) e teste visual de sobreposição dos ICs [AR, slides 64 e 66]:

| Par | Pergunta |
|---|---|
| B × A | o HPA proativo é melhor que o padrão? |
| B × C | o ganho é do detector ou só de escalar mais cedo? |
| C × A | escalar mais cedo, por si só, ajuda? |
| D × B | o tipo de detector importa? (se houver D) |

- **Figuras:** IC por modo para tempo de reação, p95 nas anomalias, % acima do SLO e custo.
- **Saídas:** `relatorio.md` (leitura rápida), `estatistica.xlsx` (uma aba por análise), PNGs.

Nota para discutir com o orientador: com 3 ou mais modos, o material recomenda ANOVA antes das comparações par a par [AR, slide 65]. O pipeline faz os testes t (não pareados) por cenário. Se ele pedir, a ANOVA entra como etapa anterior.

## 6. Ver o HPA agindo (teste manual, sem estatística)

```bash
make hpa-mode HPA_MODE=B
make phase2-check              # anomaly_level do detector chegando pelo Adapter
make test-burst                # uma carga burst (≈ 12 min)
```

Enquanto roda:
- **Grafana › "Detector Online & HPA"**: `anomaly_level` subindo, seguido das réplicas desejadas e disponíveis.
- **Terminal:** `kubectl -n anomaly-lab get hpa fastapi-hpa -w` mostra as decisões ao vivo (coluna TARGETS com CPU e `anomaly_level`).

Repita com `HPA_MODE=A` para ver a diferença. No fim, `make hpa-mode HPA_MODE=A` volta ao padrão.

## 7. Variáveis do `.env`

| Variável | Padrão | O que controla |
|---|---|---|
| `HPA_MODE` | `A` | modo aplicado no `make up` |
| `HPA_MODES` | `A,B,C` | modos rodados pelo `make hpa-experiment` (acrescente `D` para a ablação) |
| `HPA_B_DETECTOR` | `IF` | detector do modo B (troque pelo vencedor da Fase 1; aceita EWMA, IF, LOF, DBSCAN, AE, LSTM) |
| `HPA_D_DETECTOR` | `EWMA` | detector do modo D |
| `HPA_C_CPU_TARGET` | `35` | alvo de CPU do modo C (%) |
| `ANOMALY_TARGET` | `500m` | alvo do `anomaly_level` (0,5 = age com 2 de 3 alertas) |
| `DETECTOR_K_SIGMA` | `2` | sensibilidade do detector online (menor = mais alertas) |
| `SLO_SECONDS` | `0.5` | limite de latência usado nas métricas de SLO |
| `REPS` | `10` | repetições |

## 8. Problemas comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| `phase2-check` sem dados | Adapter iniciando ou detector sem amostras | esperar ≈ 1 min; `make detector-logs`; `kubectl -n anomaly-lab logs deploy/prometheus-adapter` |
| HPA B mostra `<unknown>` na métrica externa | Adapter sem a métrica ou detector errado no seletor | `make phase2-check`; conferir `HPA_B_DETECTOR` em `DETECTOR_ALGOS` |
| B nunca escala pela anomalia | `anomaly_level` não chega a 0,67 | Grafana; baixar `DETECTOR_K_SIGMA` ou `ANOMALY_TARGET` e `make detector-deploy` (antes da Fase 3, nunca durante) |
| muitas janelas sem reação em todos os modos | a carga não força scale-up | conferir no Grafana se a CPU passa do alvo nos picos |
| "réplicas não voltaram ao mínimo" | descida lenta (120 s + 1 pod/min) | normal com 8 réplicas; `BASELINE_TIMEOUT` controla a espera |
| "o HPA escalou durante o aquecimento" | CPU do aquecimento acima de 50% no modo A (carga normal pesada demais para 2 réplicas) | `results/warmup_log.csv` (`at_min=0`); a execução começa fora da condição inicial: avaliar se refaz |
| `anomaly_level_b` ≥ 0,5 no `warmup_log.csv` | detector do B ainda alarmando ao fim do aquecimento | `make check-inicio DIR=datasets_hpa`; Grafana no fim do aquecimento; conferir o piso e o `WARMUP_SECONDS` |