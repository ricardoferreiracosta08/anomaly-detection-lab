# Decisões de método

Um só lugar para as decisões de método: as que **ainda estão em aberto** e dependem do orientador, e as que **já foram tomadas**, com o motivo.

> **Regra:** toda decisão em aberto é fechada **antes** da fase que ela afeta e registrada aqui (data + quem decidiu). Depois de fechada, não muda ao ver resultados. Se mudar, o motivo fica registrado.

## TL;DR — em aberto

| # | Decisão | Afeta | Proposta | Fechar antes de |
|---|---|---|---|---|
| 1 | Teste pareado ou não pareado | Fase 1 | **adotada** (aguarda orientador): pareado; **implementação pendente** | Fase 1 |
| 2 | Quais comparações fazer | Fase 1 | só as que respondem às perguntas | Fase 1 |
| 3 | LSTM no rol e como candidato ao B | Fases 1 e 3 | **adotada** (aguarda orientador): manter; piloto 4: ciclo p95 0,48 s | Fase 1 |
| 4 | Estado inicial da aplicação | Fases 1 e 3 | **adotada** (aguarda orientador): reiniciar com 100 itens | Fase 1 |
| 5 | Detectores no cluster | Fases 1 e 3 | **adotada** (aguarda orientador): Fase 1 num pod; Fase 3 só o do B | Fase 1 |
| 6 | Tolerância de atraso na avaliação do online | Fase 1 | **adotada** (aguarda orientador): sem (principal) e com tolerância; **valor e implementação pendentes** | Fase 1 |
| 7 | Detector do modo B e métrica principal | Fase 3 | **regra registrada em 16/out/2026** (ver item 7); métrica: tempo de reação | Fase 3 |
| 8 | Valor do SLO (500 ms) | Fase 3 | manter + sensibilidade com outros limites | Fase 3 |
| 9 | Ameaças à validade suficientes? | escrita | declarar as limitações | escrita |
| 10 | Forma do IC (t·S/√N × t·S) | Fases 1 e 3 | t·S/√N (atual) | Fase 1 |
| 11 | Acomodação inicial da avaliação (burn-in) | Fase 1 | **adotada** (aguarda orientador): 60 s fora da pontuação (`EVAL_SKIP_SECONDS`) | Fase 1 |

---

## Em aberto

### 1. Teste pareado ou não pareado (Fase 1)

**Situação.** Na Fase 1, o F1 offline, o F1 online e os 6 detectores saem das **mesmas execuções**: os dados são pareados. Uma execução "difícil" derruba todos juntos.

**Hoje.** O `stats_tlc.py` usa o t de Student **não pareado** do material (gl = nA + nB − 2) em tudo.

**Opções.**
- **Não pareado (atual).** É válido, mas conservador: pode dizer "sem diferença" onde há uma.
- **Pareado.** Para cada execução, calcula a diferença (por exemplo, F1 offline − F1 online). Com as 10 diferenças, calcula o IC 95% pela mesma fórmula Ȳ ± t·S/√N. Se o IC não contém o zero, há diferença.

**Proposta.** Pareado na Fase 1. Na Fase 3 continua não pareado, porque lá A, B e C são execuções independentes.

**Adotada em 16/out/2026 (Ricardo); aguardando confirmação do orientador.** **Implementação pendente:** o `stats_tlc.py` ainda calcula só o não pareado; implementar o pareado antes da Fase 1.

**Não fazer.** Rodar os dois e reportar o que deu diferença. Se quiser mostrar o outro, ele entra como "análise de robustez", declarada como tal.

### 2. Quais comparações fazer (Fase 1)

**Situação.** Hoje a `pairwise` compara **todos os pares**: 12 grupos (6 detectores × offline/online), ou seja, 66 comparações por métrica em cada cenário. Com tantos testes a 95%, cerca de 3 dão "diferente" por acaso.

**Opções.**
- (a) Limitar às comparações que respondem às perguntas: offline × online do mesmo detector, e o melhor contra os demais.
- (b) ANOVA antes, e pares só se ela indicar diferença.
- (c) Manter todos os pares com correção (Bonferroni: p < 0,05/nº de testes).

**Proposta.** (a), definida antes da Fase 1.

### 3. LSTM no rol e como candidato ao modo B

**Situação.** Implementado offline e online. No replay dos dados da qualificação (N = 3), o F1 ficou burst 0,61, rampup 0,45 e shift 0,36, empatado com AE e DBSCAN.

**Risco.** É o detector mais pesado e atrasa o ciclo de todos (ver item 5).

**Proposta.** Manter, se o ciclo do detector no piloto 4 ficar bem abaixo de 5 s.

**Piloto 4:** ciclo com os 6 detectores p95 0,478 s (média 0,235 s), CPU do pod ~0,03 núcleo, 0 reinícios. Critério atendido.

**Adotada em 16/out/2026 (Ricardo; já implementada); aguardando confirmação do orientador.**

### 4. Estado inicial da aplicação

**Situação.** A aplicação é reiniciada antes de cada execução e começa com 100 itens por pod. Sem o reinício, os pods acumulavam cerca de 4.000 itens (piloto 3).

**Opções.** Manter os 100 itens (atual) ou semear um tamanho fixo maior, mais parecido com uma aplicação em uso.

**Proposta.** Manter 100. O importante é ser igual em todas as execuções.

**Piloto 4:** 100;100 itens por pod no início das 3 execuções (`warmup_log.csv`); a latência de A, B e C voltou a ser comparável (414–539 ms nos picos; no piloto 3, B e C chegaram a 975 e 1.200 ms).

**Adotada em 16/out/2026 (Ricardo; já implementada); aguardando confirmação do orientador.**

### 5. Detectores no cluster (custo da observação)

**Situação.** Os 6 detectores rodam num só pod, um depois do outro, a cada 5 s, disputando CPU com a aplicação.

**Proposta.**
- **Fase 1:** um pod, desde que o ciclo (p95) fique bem abaixo de 5 s. Assim todos veem os mesmos dados.
- **Fase 3:** só o detector do B, como seria em produção.

**Piloto 4:** ciclo p95 0,478 s e CPU do pod ~0,03 núcleo (média de 1 min) com os 6.

**Adotada em 16/out/2026 (Ricardo); aguardando confirmação do orientador.** Na Fase 3, `DETECTOR_ALGOS` passa a ter só o detector do B (e o do D, se usado), fixado junto com a escolha do B.

### 6. Tolerância de atraso na avaliação do online (Fase 1)

**Situação.** O alerta online chega alguns segundos depois do início real do pico e pode "transbordar" para depois do fim. Isso conta como erro, mesmo quando o detector acertou.

**Proposta.** Reportar o F1 online sem tolerância (principal) e com uma tolerância fixa após o fim do pico (secundário). O valor da tolerância é fixado antes.

**Adotada em 16/out/2026 (Ricardo); aguardando confirmação do orientador.** **Pendente:** fixar o valor da tolerância e implementar (a avaliação calcula só o F1 sem tolerância) antes da Fase 1.

### 7. Detector do modo B e métrica principal (pré-registro)

**Proposta.**
- **Métrica principal:** tempo de reação.
- **Detector — regra registrada em 16/out/2026 (Ricardo), antes da Fase 1** (texto completo em `docs/HPA.md`, seção 3):
  1. maior **média das 3 médias** do F1 **online** (burst, rampup, shift; cada cenário pesa igual);
  2. **empate** = diferença entre o 1º e o 2º não significativa em **nenhum** dos 3 cenários (teste t adotado na decisão 1, α = 0,05) → desempata o **menor MTTD online**; se o 1º for significativamente melhor em pelo menos um cenário, ele fica;
  3. **requisito:** p95 do ciclo do detector < 2,5 s (`make detector-ciclo`).

  Falta só a confirmação do orientador; o texto não muda depois de ver os resultados da Fase 1.

Os dois ficam fixados aqui antes da Fase 3. Durante a Fase 3 não se muda o detector, `DETECTOR_*` nem `ANOMALY_TARGET`.

### 8. Valor do SLO (500 ms)

**Situação.** Os 500 ms são uma escolha do experimento: o Kubernetes não define SLO. O valor é o mesmo limite da fase normal do roteiro k6 da qualificação (`normal_phase_latency: p(95)<500`). O conceito de SLO vem de Beyer et al. (2016), *Site Reliability Engineering*, cap. 4.

**Proposta.** Manter 500 ms. Como análise de sensibilidade, recalcular a violação de SLO com outros limites (por exemplo, 300 ms e 1 s). Isso não exige rodar nada de novo. O tempo de reação, a métrica principal, não depende do SLO.

### 9. Ameaças à validade

**Declaradas:**
- cluster de um nó (k3d);
- carga sintética (k6);
- aplicação de teste;
- VPS compartilhada com outros serviços;
- partida a frio fora do escopo;
- detector disputando CPU com a aplicação;
- oscilações de latência num pod só, em instantes irregulares, de origem do ambiente (item 11): entram como ruído, igual para todos os detectores.

**Pergunta.** Isso é suficiente para o escopo do mestrado?

### 10. Forma do IC

**Situação.** O `stats_tlc.py` usa Ȳ ± t·S/√N. Um exemplo do material usa a forma t·S, que está guardada na coluna `H_tDP` para comparação.

**Proposta.** Manter t·S/√N, que é o IC da média. Confirmar com o orientador.

### 11. Acomodação inicial da avaliação (burn-in) — piloto 4

**Situação.** No piloto 4, nos 150 s antes do 1º pico, com carga constante, a latência p95 oscilou em dois tipos de episódio:

| Tipo | Quando | Onde | Leitura |
|---|---|---|---|
| **1º: logo após a troca aquecimento → roteiro** | A 20–35 s (9 → 19 ms), B 30–50 s (5 → 33 ms), C 15–35 s (5 → 9 ms) | nos 2 pods (A), mais em um (B: 51–55 ms × 6–15 ms) | **sistemático, do procedimento**: nas 3 execuções, no mesmo trecho; a taxa de requisições sobe 8–14% entre 10 e 35 s (A 6,6 → 7,6; B 6,6 → 7,2; C 6,6 → 7,3 req/s) |
| **2º: um pod só, instantes irregulares** | B pod crxf8 90–110 s (35 ms) e 140–150 s (31 ms); C pod pr6c5 80–100 s (até 240 ms) | um pod, o outro quase normal | **ruído do ambiente**, igual para todos os detectores: não tratar |

Hipóteses descartadas: réplicas da execução anterior descendo no aquecimento (o código espera as 2 réplicas antes do aquecimento; memória estável no início do B); pod novo somando memória (o degrau do C veio depois dos alertas); retreino do LSTM a cada 60 s (segue o relógio do pod do detector, não sincronizado com o roteiro). Detalhes: [PILOTOS.md](PILOTOS.md), piloto 4.

**Decisão — adotada em 16/out/2026 (Ricardo), antes da Fase 1; aguardando confirmação do orientador.**
- Na avaliação da **Fase 1** (offline **e** online, mesma regra), os pontos com `offset_seconds` < **60 s** (`EVAL_SKIP_SECONDS`) **não entram** em F1, precisão, recall e MTTD. Os detectores continuam rodando sobre a série inteira; só a pontuação ignora o trecho. Vale também no `make online-replay`.
- **Nenhum pico é cortado:** a 1ª anomalia do gabarito começa aos **150 s** (burst e shift) e **175 s** (rampup), conferido em `ANOMALY_PHASES`. O gabarito, os roteiros k6 e os parâmetros dos detectores não mudam.
- **Os alarmes entre 60 s e a 1ª anomalia continuam contando** (o 2º tipo de episódio é ruído real).
- **Não se aplica à Fase 3:** as métricas do HPA (`hpa_metrics.py`) olham os picos e os scale-ups; nenhuma delas pontua alertas no trecho inicial.
- `EVAL_SKIP_SECONDS=0` reproduz a avaliação antiga e a da qualificação (verificado: offline 45/45 com `results_qualificacao/`, LSTM 9/9, replay online 54/54).
- Por quê 60 s: cobre o 1º tipo de episódio nas 3 execuções (até 50 s) com folga, longe da 1ª anomalia (150 s). Descartar o transiente inicial ("burn-in") é procedimento padrão em avaliação de desempenho, desde que decidido antes e registrado.

**Fechar antes de:** Fase 1 (fechada; falta a confirmação do orientador).
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