# Decisões de método

Um só lugar para as decisões de método, com data, motivo e estado.

> **Regra:** toda decisão em aberto é fechada **antes** da fase que ela afeta e registrada aqui (data + quem decidiu). Depois de fechada, não muda ao ver resultados. Se mudar, o motivo fica registrado.

## TL;DR — estado

**Todas as decisões estão fechadas.** As de 1 a 13 foram alinhadas com o orientador e registradas em 28/out/2026, antes da Fase 1. O modo D (item 5) foi fechado em 29/out/2026: não será usado. As decisões 14, 15 e 16 foram tomadas por Ricardo em 29/out/2026, depois da Fase 1 e antes da Fase 3, só com dados de ambiente (latência e réplicas, sem olhar F1). A 17 foi tomada no mesmo dia, antes de gerar os números corrigidos (ver o item). A 18 corrige uma métrica secundária da Fase 3, achada no piloto 5 (30/out/2026), antes da Fase 3. No mesmo dia, o limite baixo da sensibilidade do SLO (item 8) passou de 300 para 250 ms, por causa dos baldes do histograma. Falta confirmar de 14 a 18 e esse ajuste do 8 com o orientador.

| # | Decisão | Afeta | O que foi decidido | Estado |
|---|---|---|---|---|
| 1 | Teste pareado ou não pareado | Fases 1 e 3 | pareado na Fase 1, não pareado na Fase 3 | **fechada** (implementada) |
| 2 | Quais comparações fazer | Fase 1 | 6 offline × online + 5 vencedor da regra do B × outros online, por cenário | **fechada** (implementada) |
| 3 | LSTM no rol e como candidato ao B | Fases 1 e 3 | manter; piloto 4: ciclo p95 0,48 s | **fechada** (implementada) |
| 4 | Estado inicial da aplicação | Fases 1 e 3 | reiniciar com 100 itens | **fechada** (implementada) |
| 5 | Detectores no cluster | Fases 1 e 3 | Fase 1 com os 6 num pod; Fase 3 só o do B, **igual nos modos A, B e C** | **fechada**; modo D: **não usado** (29/out/2026) |
| 6 | Tolerância de atraso na avaliação | Fase 1 | sem (principal) e com **30 s** (secundário), offline e online | **fechada** (implementada) |
| 7 | Detector do modo B e métrica principal | Fase 3 | regra registrada em 16/out/2026 (ver item 7); métrica: tempo de reação | **fechada** (implementada) |
| 8 | Valor do SLO | Fase 3 | 500 ms + sensibilidade a **250 ms** e 1 s, calculada na hora (ver o item) | **fechada**; limite baixo ajustado em 30/out/2026, antes da Fase 3 (implementada) |
| 9 | Ameaças à validade | escrita | declarar as limitações listadas no item 9 | **fechada** |
| 10 | Forma do IC (t·S/√N × t·S) | Fases 1 e 3 | t·S/√N; t·S só na coluna `H_tDP`, para comparação | **fechada** (implementada) |
| 11 | Acomodação inicial da avaliação (burn-in) | Fase 1 | 60 s fora da pontuação (`EVAL_SKIP_SECONDS`) | **fechada** (implementada) |
| 12 | Janela do detector online | Fases 1 e 3 | 5 min, valor da qualificação; sensibilidade só por replay | **fechada** (implementada) |
| 13 | ANOVA antes dos pares (slide 65) | Fases 1 e 3 | dispensada, porque as comparações são planejadas | **fechada** |
| 14 | Drift de desempenho ao longo do dia | Fase 3 | manter os blocos sorteados; registrar o p95 do aquecimento (`warmup_p95_ms`) e mostrar o equilíbrio entre A, B e C antes de olhar o tempo de reação | **fechada** em 29/out/2026 (implementada) |
| 16 | Janela exportada além do fim do k6 ("pontos-fantasma") | Fase 3 | na Fase 3, esperar o fim da janela antes de exportar; a Fase 1 é tratada na decisão 17 | **fechada** em 29/out/2026 (implementada) |
| 17 | Avaliação só até o fim do k6 + 15 s | Fases 1 e 3 | Fase 1: **número principal = corrigido** (corte no fim do k6 + 15 s), com o oficial "como rodou" ao lado. Fase 3: scale-ups falsos só até o fim do k6 + 60 s; custo até o fim da janela | **fechada** em 29/out/2026, antes de gerar os números corrigidos |
| 18 | `ready_time_s` nas mesmas janelas do tempo de reação; séries de réplicas salvas | Fase 3 | tempo até pronto só nas janelas com reação e só depois do pedido; `results/hpa/series/` por execução | **fechada** em 30/out/2026, antes da Fase 3 (implementada) |
| 15 | Shift já começa escalado | Fase 3 | manter o shift; tempo de reação só nas janelas com reação, com as janelas sem reação e as réplicas iniciais ao lado | **fechada** em 29/out/2026 (já implementada) |

---

## Cada decisão, com o motivo

### 1. Teste pareado ou não pareado (Fase 1)

**Situação.** Na Fase 1, o F1 offline, o F1 online e os 6 detectores saem das **mesmas execuções**: os dados são pareados. Uma execução "difícil" derruba todos juntos.

**Hoje.** O `stats_tlc.py` usa o t de Student **não pareado** do material (gl = nA + nB − 2) em tudo.

**Opções.**
- **Não pareado (atual).** É válido, mas conservador: pode dizer "sem diferença" onde há uma.
- **Pareado.** Para cada execução, calcula a diferença (por exemplo, F1 offline − F1 online). Com as 10 diferenças, calcula o IC 95% pela mesma fórmula Ȳ ± t·S/√N. Se o IC não contém o zero, há diferença.

**Proposta.** Pareado na Fase 1. Na Fase 3 continua não pareado, porque lá A, B e C são execuções independentes.

**Adotada em 16/out/2026 (Ricardo); fechada em 28/out/2026, alinhada com o orientador. Implementada em 18/out/2026** (`paired_test` em `scripts/stats_tlc.py`):
- **Fase 1:** cada par (detector × detector, ou offline × online) é comparado **execução a execução**. O pareamento vale nas **duas famílias** do item 2: online × online porque os dois rodaram ao vivo nas mesmas execuções; offline × online porque os dois foram calculados sobre o mesmo CSV. Fórmula: d = Y_A − Y_B em cada execução, IC 95% de d̄ = d̄ ± t(0,975; N−1)·S_d/√N (a mesma fórmula do IC da média), t = d̄/(S_d/√N), gl = N − 1, p bilateral. Diferença significativa se o IC não contém o 0. O relatório (`results/stats/phase1/relatorio.md`) mostra N, a diferença, o IC da diferença, t, gl e p.
- **Fase 3:** continua o t não pareado do material [AR 66] (gl = nA + nB − 2) com o teste visual dos ICs [AR 64].
- `make selftest` (`test_paired_test`): confere a fórmula, o alinhamento pela execução e um caso em que o pareado vê uma melhora constante que o não pareado não vê.

**Não fazer.** Rodar os dois e reportar o que deu diferença. Se quiser mostrar o outro, ele entra como "análise de robustez", declarada como tal.

### 2. Quais comparações fazer (Fase 1)

**Situação.** Hoje a `pairwise` compara **todos os pares**: 12 grupos (6 detectores × offline/online), ou seja, 66 comparações por métrica em cada cenário. Com tantos testes a 95%, cerca de 3 dão "diferente" por acaso.

**Opções.**
- (a) Limitar às comparações que respondem às perguntas: offline × online do mesmo detector, e o melhor contra os demais.
- (b) ANOVA antes, e pares só se ela indicar diferença.
- (c) Manter todos os pares com correção (Bonferroni: p < 0,05/nº de testes).

**Proposta.** (a), definida antes da Fase 1.

**Adotada em 18/out/2026 (Ricardo); fechada em 28/out/2026, alinhada com o orientador. Implementada em 18/out/2026** (`planned_pairs` e `rule_b_ranking` em `scripts/stats_tlc.py`). Só estas comparações, com o teste pareado (decisão 1), **iguais em todos os cenários**:
1. **offline × online do mesmo detector:** 6 por cenário (EWMA × EWMA_online, …, LSTM × LSTM_online);
2. **o vencedor da regra do B × cada um dos outros 5 online:** 5 por cenário. "Vencedor" = o 1º pela regra pré-registrada (maior **média das 3 médias** do F1 online), **o mesmo detector nos 3 cenários**; não se escolhe um "melhor" por cenário. Assim as 5 comparações respondem a uma pergunta só: o escolhido para o B é de fato melhor que os outros, ou empata? O par 1º × 2º, que a regra usa no desempate, está incluído.

**As duas famílias, lado a lado** (19/out/2026):

| Família | Pares (por cenário) | Por que é pareada | Pergunta | Serve para |
|---|---|---|---|---|
| **da escolha** | vencedor online × cada um dos outros 5 online | os dois rodaram ao vivo nas **mesmas 10 execuções** | "Quem detecta melhor ao vivo?" | a **decisão da Fase 3** (regra do B) |
| **offline × online** | EWMA × EWMA_online, IF × IF_online, … (6) | os dois foram calculados sobre o **mesmo CSV** de cada execução | "O desempenho muda quando o detector passa a trabalhar ao vivo?" | a **dissertação** (um achado); **não escolhe ninguém** |

Na Fase 3 (A × B × C), cada modo roda em execuções diferentes: lá o teste é **não pareado**. Os nomes evitam "família A/B" para não confundir com os modos A e B do HPA.

**Hipótese a confirmar na Fase 1 (família offline × online):** a maioria dos trabalhos avalia detectores offline. No piloto 1 (N = 1), o AE foi o pior offline (0,08) e um dos melhores online (0,60 no replay; 0,34 ao vivo, entre os melhores); no replay da qualificação (N = 3), o online superou o offline em 13 de 18 combinações detector × cenário, mas não em todas. Se isso se confirmar com N = 10, é um resultado: *"escolher o detector olhando só a avaliação offline pode levar à escolha errada para uso ao vivo"*. É hipótese, não conclusão: a Fase 1 decide.

**O que a família offline × online mede** (formulação para a dissertação, 18/out/2026): **não** é uma disputa com vencedor pré-definido, e o offline **não** é um teto do online. O offline é a análise retrospectiva (série inteira na mão, mas treino sobre os picos e régua fixa ou contaminada por eles); o online é a operação em tempo real. A comparação mede **o efeito de operar online** sobre cada algoritmo e pode favorecer qualquer lado (no replay da qualificação, o online venceu em 13 de 18 combinações detector × cenário, não em todas). A escolha do detector do B usa só o online. Ver `DETECTOR_ONLINE.md`, seção 4.

**Não são geradas** as 66 comparações de todos os pares, nem como anexo: o relatório só contém o que foi planejado. O relatório também mostra o ranking da regra do B e aplica o desempate (menor MTTD online) quando 1º × 2º não diferem em nenhum cenário. `make selftest` (`test_planned_pairs`): 11 comparações por cenário e nenhuma outra; o mesmo vencedor nos 3 cenários, mesmo quando outro detector vence um cenário sozinho.

### 3. LSTM no rol e como candidato ao modo B

**Situação.** Implementado offline e online. No replay dos dados da qualificação (N = 3), o F1 ficou burst 0,61, rampup 0,45 e shift 0,36, empatado com AE e DBSCAN.

**Risco.** É o detector mais pesado e atrasa o ciclo de todos (ver item 5).

**Proposta.** Manter, se o ciclo do detector no piloto 4 ficar bem abaixo de 5 s.

**Piloto 4:** ciclo com os 6 detectores p95 0,478 s (média 0,235 s), CPU do pod ~0,03 núcleo, 0 reinícios. Critério atendido.

**Adotada em 16/out/2026 (Ricardo; já implementada); fechada em 28/out/2026, alinhada com o orientador.**

### 4. Estado inicial da aplicação

**Situação.** A aplicação é reiniciada antes de cada execução e começa com 100 itens por pod. Sem o reinício, os pods acumulavam cerca de 4.000 itens (piloto 3).

**Opções.** Manter os 100 itens (atual) ou semear um tamanho fixo maior, mais parecido com uma aplicação em uso.

**Proposta.** Manter 100. O importante é ser igual em todas as execuções.

**Piloto 4:** 100;100 itens por pod no início das 3 execuções (`warmup_log.csv`); a latência de A, B e C voltou a ser comparável (414–539 ms nos picos; no piloto 3, B e C chegaram a 975 e 1.200 ms).

**Adotada em 16/out/2026 (Ricardo; já implementada); fechada em 28/out/2026, alinhada com o orientador.**

### 5. Detectores no cluster (custo da observação)

**Situação.** Os 6 detectores rodam num só pod, um depois do outro, a cada 5 s, disputando CPU com a aplicação.

**Proposta.**
- **Fase 1:** um pod, desde que o ciclo (p95) fique bem abaixo de 5 s. Assim todos veem os mesmos dados.
- **Fase 3:** só o detector do B, como seria em produção.

**Piloto 4:** ciclo p95 0,478 s e CPU do pod ~0,03 núcleo (média de 1 min) com os 6.

**Adotada em 16/out/2026 (Ricardo); fechada em 28/out/2026, alinhada com o orientador.** Na Fase 3, `DETECTOR_ALGOS` passa a ter só o detector do B (e o do D, se usado), fixado junto com a escolha do B.

**Esclarecido em 18/out/2026:** na Fase 3 o detector roda **igual nos modos A, B e C**, não só no B. O pod `online-detector` é um só, implantado com `DETECTOR_ALGOS` fixo, e fica de pé o tempo todo; o modo do HPA só muda quem **lê** o `anomaly_level`. Assim o custo de CPU do detector é o mesmo nos três modos, e a comparação é justa. **Modo D (2º detector) — decidir antes da Fase 3:** ou o D sai (`HPA_MODES=A,B,C`, o padrão), ou os dois detectores (o do B e o do D) rodam em **todos** os modos, e o custo é igual de novo. Proposta: D sai.

**Modo D: fechado em 29/out/2026 (Ricardo): não será usado.** A Fase 3 roda só A, B e C (`HPA_MODES=A,B,C`, o padrão), e o pod do detector na Fase 3 roda só o detector do B.

### 6. Tolerância de atraso na avaliação do online (Fase 1)

**Situação.** O alerta chega alguns segundos depois do início real do pico e pode "transbordar" para depois do fim. Isso conta como erro, mesmo quando o detector acertou. Dois atrasos se somam: os **sinais** (latência p95 e taxa são `rate[30s]`: continuam altos até ~30 s depois do fim do pico) e, no online, o **pipeline** (consulta, publicação, coleta).

**Proposta.** Reportar o F1 online sem tolerância (principal) e com uma tolerância fixa após o fim do pico (secundário). O valor da tolerância é fixado antes.

**Adotada em 16/out/2026 (Ricardo); fechada em 28/out/2026, alinhada com o orientador. Implementada em 18/out/2026** (`tolerance_mask` em `scripts/detectors.py`):
- **Principal:** F1, precisão, recall e MTTD **sem tolerância** (como sempre).
- **Secundário:** `f1_tol`, `precision_tol` e `recall_tol`, com os pontos **normais** até `EVAL_TOLERANCE_SECONDS` depois do fim de cada janela anômala **fora da conta**. **Offline e online**, calculado e reportado para todos, para a comparação offline × online ser justa.
- **Valor: 30 s — adotado em 18/out/2026 (Ricardo); fechado em 28/out/2026, alinhado com o orientador.** Não muda depois de ver resultados. Medido em dados de **piloto e da qualificação, nunca da Fase 1**: segundos de alerta contínuo depois do fim de cada pico.

  | Fonte | Detectores | mediana | p90 | máx |
  |---|---|---|---|---|
  | piloto 4, online **ao vivo** (9 janelas/detector) | EWMA_online · IF_online | 10 · 20 s | 30 · 31 s | 30 · 35 s |
  | | AE · DBSCAN · LOF · LSTM online | 25 · 20 · 15 · 15 s | 82 · 72 · 88 · 100 s | 90–100 s |
  | qualificação, **replay** (só o atraso dos sinais; 30 janelas/detector) | todos os 6 online (180 janelas) | 0 s | **25 s** (p75 10 s) | 135 s |
  | piloto 4, offline | AE, DBSCAN, IF, LOF, LSTM · EWMA | 0 s · 70 s | 0–20 s · 81 s | — |

  **Por que 30 s:** (1) é a janela dos sinais (`rate[30s]`): até 30 s depois do fim, as entradas ainda carregam o pico, por construção; (2) cobre o p90 do transbordo causado só pelos sinais (replay: 25 s), a mediana do online ao vivo (10–25 s) e o p90 dos detectores de atraso puro (EWMA, IF: ~30 s). **Por que não o p90 total (~100 s):** a cauda longa aparece só nos multivariados (que somam memória e CPU de todos os pods) e no EWMA offline (base fixa nos primeiros 150 s): é o estado do sistema depois do escalonamento (pods extras ainda de pé), não atraso; e no burst o intervalo normal entre picos é de 120 s, então 100 s apagaria quase todo o trecho normal. A cauda fica na avaliação, como achado.
- `EVAL_TOLERANCE_SECONDS=0` → as métricas secundárias ficam iguais às principais (verificado: 54/54).

### 7. Detector do modo B e métrica principal (pré-registro)

**Proposta.**
- **Métrica principal:** tempo de reação.
- **Detector — regra registrada em 16/out/2026 (Ricardo), antes da Fase 1** (texto completo em `docs/HPA.md`, seção 3):
  1. maior **média das 3 médias** do F1 **online** (burst, rampup, shift; cada cenário pesa igual);
  2. **grupo de empate** (esclarecido em 18/out/2026) = o 1º + **todos** os detectores online cuja diferença para o 1º não é significativa em **nenhum** dos 3 cenários (teste pareado, decisão 1, α = 0,05). Grupo só com o 1º → o 1º. Grupo maior → vence o **menor MTTD online** (média das 3 médias) dentro do grupo, mesmo que seja o 3º ou outro;
  3. **MTTD** (esclarecido em 18/out/2026): numa execução, janelas não detectadas ficam **fora da média**; o número de janelas detectadas é reportado ao lado (`windows_detected`/`windows_total`);
  4. **requisito:** p95 do ciclo do detector < 2,5 s. **Verificado pelo ciclo do pod (0,48 s com os 6, piloto 4)**: os 6 rodam no mesmo ciclo, então qualquer um cumpre.

  O relatório da Fase 1 aplica a regra (`rule_b_choice` em `stats_tlc.py`) e escreve a escolha; `make selftest` testa um grupo de 3 em que o 3º vence pelo MTTD.

  Regra fechada em 28/out/2026, alinhada com o orientador; o texto não muda depois de ver os resultados da Fase 1.

Os dois ficam fixados aqui antes da Fase 3. Durante a Fase 3 não se muda o detector, `DETECTOR_*` nem `ANOMALY_TARGET`.

### 8. Valor do SLO (500 ms)

**Situação.** Os 500 ms são uma escolha do experimento: o Kubernetes não define SLO. O valor é o mesmo limite da fase normal do roteiro k6 da qualificação (`normal_phase_latency: p(95)<500`). O conceito de SLO vem de Beyer et al. (2016), *Site Reliability Engineering*, cap. 4.

**Proposta.** Manter 500 ms. Como análise de sensibilidade, recalcular a violação de SLO com outros limites (por exemplo, 300 ms e 1 s). Isso não exige rodar nada de novo. O tempo de reação, a métrica principal, não depende do SLO.

**Decisão — fechada em 28/out/2026, alinhada com o orientador:** 500 ms, com a sensibilidade a 300 ms e 1 s.

**Ajuste de implementação — Ricardo, 30/out/2026, antes da Fase 3** (sem resultado da Fase 3; o piloto 5 não mostrou esses números):
- **"Não exige rodar nada de novo" estava errado.** A % acima de um limite vem dos histogramas de latência do Prometheus, e eles somem em 7 dias (`retention.time=7d`). Então a sensibilidade é calculada **na hora**, em cada execução, junto com o SLO de 500 ms: colunas `slo_viol_anom_250ms_pct` e `slo_viol_anom_1000ms_pct` no `hpa_results.csv` (só nas janelas anômalas, mesma conta do `slo_viol_anom_pct`).
- **300 ms virou 250 ms.** O histograma da app só tem baldes em 5, 10, 25, 50, 100, **250**, **500** ms, **1 s**, 2,5 s, 5 s e 10 s. Com 300 ms seria preciso estimar (supor as requisições espalhadas por igual entre 250 e 500 ms). Com 250 ms a conta é **exata**, como a de 500 ms e a de 1 s. A decisão dizia "por exemplo, 300 ms"; o objetivo (um limite mais apertado e um mais folgado) se mantém. Criar um balde de 300 ms na app foi descartado: mudaria o p95 que o detector e as outras métricas usam.
- Configuração: `SLO_SENSITIVITY_SECONDS=0.25,1` (cada valor tem de ser uma borda de balde). Nenhuma outra métrica muda.

### 9. Ameaças à validade

**Declaradas:**
- cluster de um nó (k3d);
- carga sintética (k6);
- aplicação de teste;
- VPS compartilhada com outros serviços;
- partida a frio fora do escopo;
- detector disputando CPU com a aplicação;
- oscilações de latência num pod só, em instantes irregulares, de origem do ambiente (item 11): entram como ruído, igual para todos os detectores.

**Decisão — fechada em 28/out/2026, alinhada com o orientador:** a lista acima basta para o escopo do mestrado e entra na dissertação.

**Acrescentadas em 29/out/2026, depois da Fase 1** (achados de ambiente; tratamento nos itens 14, 15 e 16):
- **drift de desempenho ao longo do dia:** com a mesma carga e a app reiniciada, a latência da fase normal subiu de 2 a 5 vezes entre a madrugada e o meio-dia (item 14);
- **shift fora da condição inicial:** nas 10 execuções do shift, o HPA já tinha escalado no aquecimento (3 a 7 réplicas ao fim dele, em vez de 2) (item 15);
- **alertas na "fase normal" que sobe:** no rampup e no shift, o roteiro aumenta a carga antes da 1ª anomalia do gabarito. O rampup vai de 10 para 40 e depois 65 usuários ("degraus 1 e 2"), e o shift de 30 para 50. Os detectores online alarmam em 57–99% desses pontos (exceto o EWMA), contra 5–19% no burst, cujo roteiro fica no nível do aquecimento. Isso baixa a precisão online nesses cenários, igual para todos os detectores. Na Fase 3, o B pode escalar antes da 1ª anomalia (`false_scaleups`). Gabarito, roteiros e aquecimento não mudam. Os pilotos 3 e 4, que validaram "alertas iniciais perto de 0%", foram só com burst. Detalhes: [FASE1_EXPLICADA.md](FASE1_EXPLICADA.md), seção 5;
- **pontos-fantasma no fim do CSV:** a janela exportada passa do fim do k6, e os últimos pontos repetem o último valor dos gauges, inclusive alertas (até 23% do CSV no rampup). Igual à qualificação. Sensibilidade: o LSTM continua escolhido (item 16).

### 10. Forma do IC

**Situação.** O `stats_tlc.py` usa Ȳ ± t·S/√N. Um exemplo do material usa a forma t·S, que está guardada na coluna `H_tDP` para comparação.

**Proposta.** Manter t·S/√N, que é o IC da média.

**Decisão — fechada em 28/out/2026, alinhada com o orientador:** t·S/√N. A forma t·S fica só na coluna `H_tDP`, para comparação.

### 11. Acomodação inicial da avaliação (burn-in) — piloto 4

**Situação.** No piloto 4, nos 150 s antes do 1º pico, com carga constante, a latência p95 oscilou em dois tipos de episódio:

| Tipo | Quando | Onde | Leitura |
|---|---|---|---|
| **1º: logo após a troca aquecimento → roteiro** | A 20–35 s (9 → 19 ms), B 30–50 s (5 → 33 ms), C 15–35 s (5 → 9 ms) | nos 2 pods (A), mais em um (B: 51–55 ms × 6–15 ms) | **sistemático, do procedimento**: nas 3 execuções, no mesmo trecho; a taxa de requisições sobe 8–14% entre 10 e 35 s (A 6,6 → 7,6; B 6,6 → 7,2; C 6,6 → 7,3 req/s) |
| **2º: um pod só, instantes irregulares** | B pod crxf8 90–110 s (35 ms) e 140–150 s (31 ms); C pod pr6c5 80–100 s (até 240 ms) | um pod, o outro quase normal | **ruído do ambiente**, igual para todos os detectores: não tratar |

Hipóteses descartadas: réplicas da execução anterior descendo no aquecimento (o código espera as 2 réplicas antes do aquecimento; memória estável no início do B); pod novo somando memória (o degrau do C veio depois dos alertas). Hipótese **improvável, não descartada**: retreino do LSTM a cada 60 s (segue o relógio do pod do detector, que não bate com o roteiro). Detalhes: [PILOTOS.md](PILOTOS.md), piloto 4.

**Decisão — adotada em 16/out/2026 (Ricardo), antes da Fase 1; fechada em 28/out/2026, alinhada com o orientador.**
- Na avaliação da **Fase 1** (offline **e** online, mesma regra), os pontos com `offset_seconds` < **60 s** (`EVAL_SKIP_SECONDS`) **não entram** em F1, precisão, recall e MTTD. Os detectores continuam rodando sobre a série inteira; só a pontuação ignora o trecho. Vale também no `make online-replay`.
- **Nenhum pico é cortado:** a 1ª anomalia do gabarito começa aos **150 s** (burst e shift) e **175 s** (rampup), conferido em `ANOMALY_PHASES`. O gabarito, os roteiros k6 e os parâmetros dos detectores não mudam.
- **Os alarmes entre 60 s e a 1ª anomalia continuam contando** (o 2º tipo de episódio é ruído real).
- **Efeito registrado, sem mudança:** o EWMA offline aprende o "normal" nos primeiros 150 s (parâmetro da qualificação), e esse trecho inclui a oscilação da troca (15–55 s). Efeito possível: limiar um pouco mais largo no EWMA offline. Não se corrige, porque os parâmetros do EWMA são os da qualificação; fica escrito para explicar um EWMA offline diferente do esperado.
- **Não se aplica à Fase 3:** as métricas do HPA (`hpa_metrics.py`) olham os picos e os scale-ups; nenhuma delas pontua alertas no trecho inicial.
- `EVAL_SKIP_SECONDS=0` reproduz a avaliação antiga e a da qualificação (verificado: offline 45/45 com `results_qualificacao/`, LSTM 9/9, replay online 54/54).
- Por quê 60 s: cobre o 1º tipo de episódio nas 3 execuções (até 50 s) com folga, longe da 1ª anomalia (150 s). Descartar o transiente inicial ("burn-in") é procedimento padrão em avaliação de desempenho, desde que decidido antes e registrado.

**Fechar antes de:** Fase 1 (fechada em 28/out/2026).

### 12. Janela do detector online (5 min)

**Situação.** A janela de referência do detector online (`DETECTOR_WINDOW` = 60 pontos = 5 min, mais o gap de 30 s) é um **parâmetro do detector ao vivo**: diferente do SLO e da ANOVA, que são análise, ela não pode mudar depois da Fase 1 sem rodar tudo de novo.

**Decisão — adotada em 18/out/2026 (Ricardo); fechada em 28/out/2026, alinhada com o orientador.** Fixada em **5 min**, o valor da qualificação. A sensibilidade a outras janelas só é avaliada por **replay**, como análise complementar declarada como tal, sem mudar o experimento.

**Fechar antes de:** Fase 1.

### 13. ANOVA antes dos pares (slide 65)

**Situação.** O material recomenda ANOVA antes das comparações par a par com 3 ou mais grupos. A ANOVA protege contra muitas comparações feitas **sem plano**.

**Decisão — fechada em 28/out/2026, alinhada com o orientador.** Dispensar a ANOVA: as comparações são **planejadas e definidas antes** (decisão 2: 11 por cenário na Fase 1; B×A, B×C e C×A na Fase 3), cada uma respondendo a uma pergunta da pesquisa.

**Fechar antes de:** Fase 1.

### 14. Drift de desempenho ao longo do dia

**Situação.** A Fase 1 rodou em 29/out/2026, das 00h24 às 13h (Brasília). Em todos os cenários, a mesma carga ficou mais lenta com o passar do dia. A app é reiniciada a cada execução, então o estado da aplicação não explica a piora.

| Medida | Madrugada | Fim da manhã (depois das ~10h) |
|---|---|---|
| p95 na fase normal, burst | ~5 ms | 23–26 ms |
| p95 na fase normal, rampup | ~21 ms | 84–117 ms |
| p95 na fase normal, shift | ~16 ms | 72–80 ms |
| vazão do k6, burst | 54,7 req/s | 31,5–32,3 req/s |

O p95 é a mediana dos pontos da fase normal, pelo Prometheus. Gráfico: `01_drift_por_hora.png`, gerado a partir dos dados da Fase 1.

A piora não foi contínua: houve um episódio isolado por volta das 05h30–06h (burst_run5 com 21,6 ms e rampup_run5 com 50 ms), que voltou ao normal às 07h. A subida forte começou depois das ~09h30.

Hipóteses ainda não verificadas: carga diurna dos outros serviços da VPS; throttling da app no limite de 300m; algo crescendo no cluster.

**Efeito.**
- **Fase 1:** nenhum. Os 6 detectores viram a mesma execução, e o teste pareado cancela o que é da execução.
- **Fase 3:** A, B e C rodam em execuções diferentes, e o teste não é pareado. Um modo que caísse mais nas horas lentas pareceria pior só por isso. O desenho já reduz esse risco: cada repetição roda os 9 pares (modo × cenário) em **ordem sorteada**, num bloco de ~3,5 h ([experiment.sh](../bin/experiment.sh)). Assim, o drift tende a cair igual nos três modos, e o efeito que sobra é aumentar a variação (ICs mais largos), não favorecer um modo.

**Decisão — Ricardo, 29/out/2026, antes da Fase 3.**
1. **Manter o desenho**: blocos por repetição, com ordem sorteada.
2. **Medir o ambiente em cada execução, antes do tratamento:**
   - a coluna `warmup_p95_ms` do `results/warmup_log.csv` guarda o p95 da latência nos últimos 4 min do aquecimento, lido antes da descida;
   - o aquecimento roda sempre no modo A, então essa medida não depende do modo;
   - o p95 do resumo do k6 **não serve** para isso, porque já sofre o efeito do modo.
3. **Mostrar o equilíbrio antes de olhar o tempo de reação:**
   - por cenário, IC da média do `warmup_p95_ms` em A, B e C, com o horário de cada execução;
   - se os ICs não se sobrepuserem, o desequilíbrio é relatado como limitação, sem correção não planejada.
4. **Não excluir nem refazer execuções** por estarem lentas, e não mudar o limite de CPU da app: isso mudaria o HPA e quebraria a comparação com a Fase 1.
5. **Diagnosticar a causa só observando:** consumo da VPS ao longo do dia e throttling no Grafana. O objetivo é explicar a causa na dissertação, sem mexer em outros serviços da VPS.
6. **Declarar** como ameaça à validade (item 9).

**Fechar antes de:** Fase 3.

### 15. Shift já começa escalado (Fase 3)

**Situação.** Nas 10 execuções do shift na Fase 1, o HPA escalou durante o aquecimento: 3 a 7 réplicas ao fim dele, em vez de 2 (`at_min=0` no `warmup_log.csv`). O motivo é que a carga normal do shift (30 VUs) passa de 50% de CPU em 2 pods. O número de réplicas cresceu ao longo do dia, junto com o drift (item 14). Burst e rampup começaram com 2 réplicas; a única exceção foi uma execução do rampup, com 3. Na Fase 3, o aquecimento é sempre no modo A, então isso vale igual para A, B e C. Consequência: num pico do shift, o HPA pode já ter réplicas suficientes e não precisar escalar, e aí o tempo de reação fica sem valor.

**Decisão — Ricardo, 29/out/2026, antes da Fase 3.**
- Manter o shift como está: o roteiro k6 e o gabarito não mudam.
- O **tempo de reação** é a média só das janelas com reação, isto é, com aumento das réplicas desejadas até `REACTION_GRACE_SECONDS` (60 s) depois do fim da janela. É o que o [hpa_metrics.py](../scripts/hpa_metrics.py) já calcula.
- Ao lado do tempo de reação, por modo, reportar:
  - as janelas sem reação (`windows_no_reaction` / `n_windows`);
  - as réplicas ao fim do aquecimento (`available` no `warmup_log.csv`).
- O shift é lido **à parte** de burst e rampup, como já é feito por cenário; o texto deixa claro que ele parte de outra condição inicial.

**Fechar antes de:** Fase 3.

### 16. Janela exportada além do fim do k6 ("pontos-fantasma")

**Situação.** A janela exportada de cada execução (`DURATION` no [experiment.sh](../bin/experiment.sh)) é a da qualificação: burst 720 s, rampup 780 s, shift 960 s. Os roteiros k6 acabam antes: 618 s, 560 s e 910 s. A exportação rodava ~15 s depois do fim do k6, ou seja, pedia ao Prometheus pontos que **ainda não existiam**.

Para esses pontos do futuro, o Prometheus devolve:
- **vazio**, nas métricas de taxa (latência, CPU, req/s);
- o **último valor repetido**, por até 5 min, nos gauges (memória, alertas online, réplicas).

Tamanho do efeito na Fase 1:

| Cenário | Pontos-fantasma por execução | % do CSV | Alertas repetidos = 1 nas 10 execuções |
|---|---|---|---|
| burst | ~12 | 9% | nenhum |
| rampup | ~36 | 23% | IF 109, AE 144, LOF 36, LSTM 36 |
| shift | 2 | 1% | 12–20 por detector |

A qualificação tem o mesmo rabo (o `rampup_run1` dela está vazio depois de ~590 s, com a memória repetida). Os alertas repetidos com valor 1 contam como falso positivo.

**Sensibilidade na Fase 1** (a primeira conta, só online; o tratamento definitivo é a decisão 17). A conta reproduz exatamente os F1 oficiais; depois foram tirados os pontos-fantasma. O F1 online médio passa de 0,476 para 0,481 no LSTM e de 0,464 para 0,476 no IF. **A escolha não muda:** o LSTM segue em 1º. O burst não tem fantasmas, e nele o IF continua significativamente diferente do LSTM, então fica fora do empate. E o critério de desempate (MTTD) não depende do rabo. A folga entre os dois cai de 0,012 para 0,005, o que reforça a frase "o IF foi melhor no burst" no texto.

**Decisão — Ricardo, 29/out/2026, antes da Fase 3.**
- **Fase 1:** os CSVs ficam como foram, igual à qualificação. A avaliação passou a cortar os pontos não medidos (decisão 17).
- **Fase 3:** antes de exportar o CSV e calcular as métricas do HPA, o script espera até início + `DURATION` + 15 s. Assim, o `pod_seconds` (custo) e o CSV só têm dado medido: o fim da janela passa a ser o HPA real descendo depois da carga, não a última contagem de réplicas repetida. A janela continua a mesma da Fase 1 e dos pilotos. Custo: ~2,7 h a mais na Fase 3 (de ~32 para ~35 h).

**Fechar antes de:** Fase 3.

---

### 17. Avaliação só até o fim do k6 + 15 s (Fases 1 e 3)

**Situação.** Item 16: o fim de cada CSV tem pontos **não medidos**. São pontos-fantasma (o último valor repetido) e pontos "meio-fantasmas" (taxas calculadas com dados velhos), e eles entravam na avaliação como pontos normais.

**Decisão — Ricardo, 29/out/2026**, registrada **antes** de gerar os números corrigidos. Antes dela, já tinha sido vista só a conta de sensibilidade do F1 online (item 16).

**Fase 1:**
1. **Corte:** a avaliação usa só os pontos com `offset_seconds` ≤ **fim do roteiro k6 + 15 s**: burst 618 + 15 = **633 s**, rampup 560 + 15 = **575 s**, shift 910 + 15 = **925 s**. Os 15 s são o intervalo do último scrape, o mesmo `sleep 15` do script antes de exportar.
2. **Igual para todos:** os 6 detectores, offline e online, nas 10 execuções de cada cenário. Os detectores offline também **só veem** os pontos até o corte, porque o resto não é dado. O corte vem do **roteiro**, não dos resultados: o número não foi escolhido olhando F1.
3. **Número principal = o corrigido.** O número oficial "como rodou" (sem corte, igual à qualificação) vai **ao lado**, numa tabela, com este motivo: pontos não medidos não podem ser avaliados.
4. Os CSVs brutos **não mudam**: o corte é aplicado na leitura (`EVAL_END_MARGIN_SECONDS=15`; `off` reproduz o oficial).
5. **A escolha do B não reabre.** A regra do item 7, aplicada aos números oficiais, deu LSTM. Se o corrigido der outro resultado, isso é relatado, e a Fase 3 segue com o LSTM, que foi o fixado pela regra pré-registrada.
6. **Não se aplica à qualificação** por enquanto: os CSVs dela têm o mesmo rabo, e a sensibilidade fica para depois.

**Fase 3** (`hpa_metrics.py`):
- **Scale-ups falsos:** só contam os aumentos de réplicas desejadas até o **fim do k6 + 60 s** (`REACTION_GRACE_SECONDS`, a mesma margem do tempo de reação). Depois disso não há mais carga, e o que acontece não é decisão sobre a carga do roteiro.
- **Custo (`pod_seconds`):** vai até o **fim da janela** (`DURATION`), que agora é medida de verdade (item 16). Os pods que ficam depois da carga são custo real do modo.

**Resultado (gerado depois do registro acima).**
- **Reprodução:** a avaliação "como rodou" refeita com `EVAL_END_MARGIN_SECONDS=off` bateu célula por célula com a oficial (360 linhas, 0 diferenças), assim como os ICs, os testes t e o ranking da regra do B.
- **Corrigido (principal):** F1 online médio LSTM 0,485 (era 0,476), IF 0,482 (0,464), AE 0,458 (0,435).
- **Regra do B:** LSTM. O IF segue fora do empate (difere no burst e no shift).
- **Offline × online:** 14 a favor do online, 2 do offline (EWMA), 2 sem diferença, igual ao "como rodou".
- **Offline:** é o que mais muda. O LOF sobe de 0,156 para 0,208 e o IF cai de 0,252 para 0,232.
- **Saída:** `fase1_corrigido/` (fora do `results/` oficial).

**Fechar antes de:** gerar os números corrigidos da Fase 1 e rodar a Fase 3.

### 18. Tempo até pronto nas mesmas janelas do tempo de reação; séries de réplicas salvas (Fase 3)

**Situação (piloto 5, 30/out/2026).** No B, o `ready_time_s` (25 s) saiu **menor** que o `reaction_time_s` (40 s), com 1 janela sem reação. Não faz sentido o pod ficar pronto antes de ser pedido. A causa estava no código: as duas médias usavam **janelas diferentes**.
- `reaction_time_s`: só as janelas em que as réplicas desejadas subiram;
- `ready_time_s`: qualquer janela em que as **disponíveis** subiram, mesmo sem reação nela.

No piloto, a 2ª janela do B começou com o HPA já escalado: os pods tinham sido pedidos **antes** dela (scale-up contado como falso). Um desses pods ficou pronto logo no início da janela, e esse atraso curto entrou na média do "pronto" sem ter havido reação. O mesmo pode acontecer dentro de uma janela com reação, se um pod pedido antes dela ficar pronto antes do novo pedido.

Segundo ponto: as séries de réplicas (desejadas e disponíveis) **não eram salvas**. O `hpa_results.csv` guarda só o resumo, e o Prometheus apaga tudo depois de 7 dias (`retention.time=7d`). Sem as séries, não daria para rever nem explicar uma métrica depois da Fase 3.

**Decisão — Ricardo, 30/out/2026, antes da Fase 3**, só com dados de piloto:
1. **`ready_time_s`** usa as **mesmas janelas** do `reaction_time_s` (as que tiveram reação). Em cada uma, é o 1º aumento das réplicas disponíveis **depois do pedido**, medido do início da janela. Assim, `ready_time_s` ≥ `reaction_time_s` em cada janela: é o tempo até os pods **daquela reação** ficarem prontos.
2. A métrica **principal** (`reaction_time_s`), `windows_no_reaction`, os scale-ups falsos e o custo **não mudam**.
3. **Séries salvas:** cada execução grava `results/hpa/series/<modo>_<cen>_runN.csv` (timestamp, offset, desejadas, disponíveis; passo de 5 s). Com `make hpa-recalc DIR=…`, as métricas de um `hpa_results.csv` são recalculadas pelo Prometheus enquanto ele tiver os dados, sem sobrescrever nada.
4. **Limite que fica:** p95 e SLO nas janelas vêm dos histogramas do Prometheus e **não** podem ser refeitos depois dos 7 dias. O tempo de reação, o tempo até pronto, os scale-ups e o custo podem, a partir das séries.

**Fechar antes de:** Fase 3.

---

## Já decididas

| Decisão | Motivo | Validação |
|---|---|---|
| Aquecimento de 330 s com a carga base do cenário, sempre no modo A | o detector aprendia o "silêncio" entre execuções: 53–87% de alarmes falsos no início (piloto 2) | piloto 3: 0–26%; zero scale-ups falsos; piloto 4: A com 0% nos 6 (B e C: ver item 11) |
| Rampas sobrepostas na troca aquecimento → roteiro (`WARMUP_OVERLAP=30`) | a carga caía e voltava na troca: alarmes em 15–45 s, só nos multivariados (piloto 3) | piloto 4: taxa constante na troca; restou oscilação tratada pelo item 11 |
| Reiniciar a aplicação antes de cada execução (`RESTART_APP=1`) | o estado acumulava entre execuções: ~4.000 itens por pod (piloto 3) | piloto 4: 100 itens por pod em todas as execuções |
| Piso nas notas (`DETECTOR_SIGMA_FLOOR=0.05`) | referência quase constante gerava notas ~10⁵ (piloto 2) | replay: F1 idêntico |
| Régua mínima nas entradas (`DETECTOR_FEATURE_FLOOR=0.01`) | 0,25 MB de memória pareceu 50× o normal (piloto 3) | replay: F1 de −0,023 a +0,028, média −0,002 |
| Modo C como controle (CPU 35%) | separar o ganho da detecção do ganho de ter mais pods (piloto 2) | piloto 3: custo igual nos três modos; piloto 4: C +14% de custo e 1 scale-up falso (escala por CPU) |
| Estatística: IC da média + teste t + teste visual dos ICs | material da disciplina | validado com o exemplo do material |

Detalhes dos pilotos: [PILOTOS.md](PILOTOS.md).