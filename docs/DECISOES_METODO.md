# Decisões de método

Um só lugar para as decisões de método, com data, motivo e estado.

> **Regra:** toda decisão em aberto é fechada **antes** da fase que ela afeta e registrada aqui (data + quem decidiu). Depois de fechada, não muda ao ver resultados. Se mudar, o motivo fica registrado.

## TL;DR — estado

**Todas as decisões que afetam a Fase 1 estão fechadas** (alinhadas com o orientador; registro em 28/out/2026, antes da Fase 1). Em aberto, só o **modo D** (item 5), a decidir antes da Fase 3.

| # | Decisão | Afeta | O que foi decidido | Estado |
|---|---|---|---|---|
| 1 | Teste pareado ou não pareado | Fases 1 e 3 | pareado na Fase 1, não pareado na Fase 3 | **fechada** (implementada) |
| 2 | Quais comparações fazer | Fase 1 | 6 offline × online + 5 vencedor da regra do B × outros online, por cenário | **fechada** (implementada) |
| 3 | LSTM no rol e como candidato ao B | Fases 1 e 3 | manter; piloto 4: ciclo p95 0,48 s | **fechada** (implementada) |
| 4 | Estado inicial da aplicação | Fases 1 e 3 | reiniciar com 100 itens | **fechada** (implementada) |
| 5 | Detectores no cluster | Fases 1 e 3 | Fase 1 com os 6 num pod; Fase 3 só o do B, **igual nos modos A, B e C** | **fechada**; modo D **em aberto** (antes da Fase 3) |
| 6 | Tolerância de atraso na avaliação | Fase 1 | sem (principal) e com **30 s** (secundário), offline e online | **fechada** (implementada) |
| 7 | Detector do modo B e métrica principal | Fase 3 | regra registrada em 16/out/2026 (ver item 7); métrica: tempo de reação | **fechada** (implementada) |
| 8 | Valor do SLO | Fase 3 | 500 ms + sensibilidade a 300 ms e 1 s | **fechada** |
| 9 | Ameaças à validade | escrita | declarar as limitações listadas no item 9 | **fechada** |
| 10 | Forma do IC (t·S/√N × t·S) | Fases 1 e 3 | t·S/√N; t·S só na coluna `H_tDP`, para comparação | **fechada** (implementada) |
| 11 | Acomodação inicial da avaliação (burn-in) | Fase 1 | 60 s fora da pontuação (`EVAL_SKIP_SECONDS`) | **fechada** (implementada) |
| 12 | Janela do detector online | Fases 1 e 3 | 5 min, valor da qualificação; sensibilidade só por replay | **fechada** (implementada) |
| 13 | ANOVA antes dos pares (slide 65) | Fases 1 e 3 | dispensada, porque as comparações são planejadas | **fechada** |

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