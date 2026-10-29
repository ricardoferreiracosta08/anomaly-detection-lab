# O projeto explicado (para conversar sobre ele)

> **Explicação didática.** Serve para você conseguir explicar cada parte com as suas palavras, na reunião e na banca. Em caso de divergência, valem [DECISOES_METODO.md](DECISOES_METODO.md) (decisões) e [PILOTOS.md](PILOTOS.md) (pilotos). O mapa técnico é o [ESTADO_DO_PROJETO.md](ESTADO_DO_PROJETO.md).

---

## 1. A ideia em uma imagem 🍔

Pense numa **lanchonete**. O gerente só chama mais atendentes **quando a fila já está enorme**. Até o atendente novo chegar e vestir o avental, os clientes esperam e reclamam.

O **HPA** do Kubernetes faz isso: só cria mais pods (os "atendentes") quando a CPU já está alta, ou seja, quando os pods já estão sobrecarregados. Até o pod novo ficar pronto, a aplicação fica lenta e viola a meta de qualidade (**SLO**: responder em até 500 ms).

**A sua ideia:** colocar um **observador** que vigia a lanchonete o tempo todo e percebe quando "algo estranho está começando", por exemplo um ônibus de turistas parando na porta. Ele avisa o gerente **antes** de a fila explodir. Esse observador é o **detector de anomalias**.

---

## 2. As 3 perguntas e as 3 fases

| Pergunta | Fase | Em uma linha |
|---|---|---|
| **Detectar:** qual detector percebe melhor as anomalias? E continua bom ao vivo? | **Fase 1** | 6 detectores competem, offline e ao vivo |
| **Integrar:** dá para ligar o detector ao HPA sem mexer no Kubernetes? | **Fase 2** | sim: detector → Prometheus Adapter → HPA (já está pronto) |
| **Agir:** o HPA com detector reage antes, pelo mesmo custo? | **Fase 3** | os modos A, B e C competem |

---

## 3. O laboratório

Tudo roda numa VPS, dentro de containers:

- **Aplicação de teste (FastAPI):** a "lanchonete", com 2 a 8 pods.
- **k6:** o gerador de clientes, com 3 roteiros de carga:
  - **burst:** rajadas súbitas (o ônibus de turistas);
  - **rampup:** subida em degraus (a hora do almoço chegando);
  - **shift:** o tipo de pedido muda (todo mundo resolve pedir o prato demorado).
- **Prometheus:** anota a cada 5 s quatro sinais (latência, CPU, memória e requisições por segundo).
- **Detector online:** lê esses sinais e decide "normal ou anômalo".
- **Prometheus Adapter:** entrega o nível de anomalia ao HPA.
- **Grafana:** a tela para você acompanhar.

O **gabarito** (ground truth) é a lista de quando cada pico começa e termina. Ele é conhecido porque você escreveu os roteiros, e é com ele que se confere se o detector acertou.

---

## 4. Os 6 detectores, cada um com o seu jeito de achar estranho

| Detector | Como pensa |
|---|---|
| **EWMA** | "A latência média fugiu muito do normal?" Olha só um sinal. |
| **Isolation Forest** | "Esse ponto é fácil de separar dos outros?" O estranho fica isolado rápido. |
| **LOF** | "Esse ponto está numa região mais vazia que os vizinhos?" |
| **DBSCAN** | "Esse ponto está longe dos grupos normais?" |
| **Autoencoder** | "Consigo reconstruir esta combinação de sinais?" Se não consegue, ela é incomum. |
| **LSTM** | "Pelo último minuto, eu previa isto?" Se o real foge da previsão, é estranho. É o único que olha **a sequência**, como um vídeo em vez de uma foto. Entrou a pedido do orientador. |

### Offline × online: não é "trapaça × honesto"

- **Offline:** o detector vê a execução inteira **depois** que ela acabou. É como assistir à **gravação do dia** (foi o jeito da qualificação).
- **Online:** o detector decide **ao vivo**, a cada 5 s, olhando só os 5 min anteriores. É o que o HPA precisa.

Os dois são calculados sobre **a mesma execução**.

**Cuidado com uma ideia errada:** o offline **não** é um "teto" do online. Ele vê o futuro, mas tem duas desvantagens:

1. **Acostuma com o pico** (*masking*): se 17% do dia foi rajada, ele aprende a rajada como "normal".
2. **Régua ruim:**
   - IF e LOF offline marcam **sempre os 10% mais estranhos do dia** (`contamination`), haja anomalia ou não: num dia calmo, inventam alarmes; num dia caótico, perdem metade.
   - AE e LSTM offline usam uma régua calculada **com os picos dentro**: os picos inflam a média e o limiar sobe.

O online usa outra régua: "**bem acima do que foi normal nos últimos 5 min**", sem cota. Resultado no replay da qualificação: **o online ganhou em 13 de 18 combinações** de detector e carga, mas não em todas (o EWMA, por exemplo, perdeu no burst e no rampup). No piloto 1, o AE foi de **0,08 offline** para **0,60 online sem o atraso do cluster** (0,34 ao vivo, ainda entre os melhores).

**Então para que o offline?**
- **Ligação com a qualificação**, que foi toda offline.
- Mostrar que **avaliar só offline engana** sobre o uso real. Isso é um achado: "não escolha o detector de produção olhando só a avaliação offline".
- É o caso de uso de um **post-mortem**: depois de um incidente, com o dia inteiro na mão.
- A comparação offline × online mede **o efeito de operar ao vivo** sobre cada algoritmo, e pode favorecer qualquer lado.

**O campeão do HPA sai só do online.**

---

## 5. A Fase 3: os três modos de HPA

| Modo | Regra | Papel |
|---|---|---|
| **A** | escala com CPU a 50% | o HPA de hoje (referência) |
| **B** | CPU a 50% **ou** alerta do detector | a sua proposta |
| **C** | escala com CPU a 35% | o controle: escala mais cedo **sem** detector |

O **C** é a peça mais esperta do desenho. Se o B ganhar do A, pode ser só porque escalou mais e gastou mais. O C responde: "escalar cedo **sem** detector já basta?". O B só é bom de verdade se ganhar do A **e** não perder para o C no custo.

**O que se mede em cada pico:**
- **Tempo de reação** (métrica principal): do início do pico até o HPA pedir mais pods.
- **Latência** e % de requisições acima de 500 ms durante o pico.
- **Custo:** pods × segundos.
- **Scale-ups falsos:** pedidos de pods fora dos picos.

---

## 6. Como cada execução roda (a receita)

1. Reinicia a aplicação: estado limpo, 100 itens por pod ("atendentes novos, caderno de pedidos zerado").
2. Espera voltar a 2 pods e descansa 2 min.
3. **Aquecimento de 5,5 min** com carga normal, para o detector aprender o "normal" de verdade (e não o silêncio).
4. Na troca para o roteiro, a carga do aquecimento desce enquanto a do roteiro sobe ("rampas sobrepostas": troca de turno sem esvaziar a loja).
5. Confere se está tudo igual: 2 pods, 100 itens, nível de anomalia 0.
6. Liga o modo da execução e roda o roteiro.

A ordem das execuções é sorteada. Toda execução começa idêntica. Na Fase 3, o detector roda **igual nos modos A, B e C**; o modo só muda quem ouve o alarme.

---

## 7. A história dos pilotos: uma investigação 🔍

Cada piloto custa cerca de 1 h. O experimento definitivo custa **cerca de 43 h**. Os pilotos existem para achar defeitos antes.

**Piloto 1:**
- **Achado:** o online sem atraso (replay) acertou mais que o offline em 4 de 5 detectores, mas ao vivo perdeu bastante. Por quê?

**Piloto 2: o observador que só conhecia a loja vazia.**
- **Achado:** alarme falso em **53–87%** do começo de cada execução. Entre as execuções o sistema ficava parado, e o detector aprendia "normal = silêncio".
- **Consequência:** o B "ganhou" porque escalou à toa, com **48% a mais de custo**.
- **Correção:** aquecimento antes de cada execução.

**Piloto 3:**
- **Achado:** o aquecimento funcionou (zero scale-up falso, custo igual), e o B reagiu 10 s antes. Mas apareceram mais 3 problemas:
  - a carga caía e voltava na troca aquecimento → roteiro;
  - a aplicação acumulava dados de uma execução para outra (**100 → 4.000 itens**): o caderno que nunca era jogado fora, com cada execução mais lenta que a anterior;
  - um salto minúsculo de memória (0,25 MB) parecia gigantesco para o detector.
- **Correções:** rampas sobrepostas, reinício da aplicação e uma "régua mínima" nos sinais.

**Piloto 4 (configuração final, com o LSTM):**
- **Achado:** tudo voltou a ficar coerente:
  - B reagiu em **42 s**, contra **48 s** do A, com **+3%** de custo;
  - C reagiu em **38 s**, mas com **+14%** de custo;
  - o detector inteiro decide em **0,48 s** (p95), gastando ~0,03 de núcleo.
- **Restou:** pequenas oscilações de latência de dois tipos:
  1. **logo depois da troca, sempre:** o procedimento ainda mexe um pouco → acomodação de 60 s;
  2. **soluços num pod só, em horas aleatórias:** ruído do ambiente.
- **Hipóteses testadas:** pods descendo no aquecimento (descartada); pod novo somando memória (descartada); retreino do LSTM (improvável).

O resultado mais valioso dos pilotos não são os números (N = 1 não prova nada), e sim os **4 vieses encontrados e corrigidos**.

---

## 8. As regras de avaliação

- **Acomodação de 60 s:** o primeiro minuto de cada execução não entra na nota da Fase 1, por causa da oscilação da troca. O primeiro pico só começa aos 150 s, então nenhum pico é cortado.
- **Tolerância de 30 s (nota complementar):**
  - O detector ao vivo sempre alerta um pouco atrasado, porque os próprios sinais "lembram" o pico por 30 s (eles são médias dos últimos 30 s).
  - Na nota complementar, esses alertas atrasados não contam como erro (offline e online, para ser justo).
  - A nota principal continua **sem perdão**.
  - O valor foi **medido** nos pilotos, não chutado.
  - Alertas que passam de 30 s são outro fenômeno (o detector estranhando o sistema "pós-pico", com pods extras ainda de pé) e viram um achado, não um perdão.
- **Tempo até detectar (MTTD):** um pico que o detector não percebeu fica fora da média do tempo, e o placar "percebeu X de 100 picos" vai ao lado. Assim ninguém ganha por perceber pouco, mas rápido.

---

## 9. A estatística

1. **10 execuções** por condição. Cada execução vira **1 número** (um F1, um tempo de reação…).
2. Com os 10 números: **média e IC 95%**, a faixa onde a média verdadeira provavelmente está.
3. Comparação:
   - **Fase 1, pareada:** todos os detectores fazem **a mesma prova** (as mesmas execuções), então se compara prova a prova. É mais justo e mais sensível.
   - **Fase 3, não pareada:** A, B e C são execuções diferentes.
4. **Só as comparações planejadas**, 11 por cenário em vez de 66, em **duas famílias**:

   | Família | O que compara | Pergunta | Para que serve |
   |---|---|---|---|
   | **da escolha** | o campeão online × cada um dos outros 5 online | "Quem detecta melhor ao vivo?" | **decide a Fase 3** (o detector do B) |
   | **offline × online** | cada detector offline × ele mesmo online (6) | "O desempenho muda quando o detector passa a trabalhar ao vivo?" | **um achado da dissertação**; não escolhe ninguém |

   As **duas são pareadas**, porque nas duas os números saem das **mesmas 10 execuções**: o campeão e os outros rodaram ao vivo juntos; o IF offline e o IF online foram calculados sobre o mesmo CSV. Na Fase 3, A, B e C são execuções diferentes, e por isso lá o teste é não pareado.

   **O achado que pode sair da família offline × online:** no piloto 1, o AE foi o **pior** offline (0,08) e um dos **melhores** online (0,60 sem o atraso do cluster; 0,34 ao vivo, ainda entre os melhores). Se isso se confirmar na Fase 1, a mensagem é forte: *"escolher o detector olhando só a avaliação offline (o jeito mais comum na literatura) pode levar à escolha errada para quem vai usá-lo ao vivo"*.

   (Os nomes "da escolha" e "offline × online" evitam "família A/B", que confundiria com os modos A e B do HPA.)

   Comparar tudo com tudo gera "diferenças" por acaso: é como jogar 66 moedas e achar que a que deu 5 caras seguidas é especial.

**Volume:**
- **Fase 1:** 30 execuções, 36 condições (6 detectores × 2 formas × 3 cargas), cerca de 11 h.
- **Fase 3:** 90 execuções, cerca de 32 h.
- **Qualificação, para comparar:** era a mesma lógica com N = 3, só offline e 3 detectores.

---

## 10. Como o detector do B será escolhido (regra escrita antes) 🏆

1. Vence o de **maior F1 online**, na média das 3 cargas (cada carga pesa igual, então ninguém ganha por ser ótimo numa só).
2. **Empate:** se outros não forem estatisticamente diferentes dele em **nenhuma** carga, formam um "grupo de empate". Dentro do grupo, vence **o que detecta mais rápido**, porque detectar antes é escalar antes.
3. Na Fase 3, só ele roda, **igual nos modos A, B e C**, para o custo do detector não pesar só num modo.

**Por que escrever antes:** se você escolhesse depois de ver os resultados, poderia (sem querer) escolher o que favorece a sua hipótese. Isso é o **pré-registro**, a sua maior proteção na banca. O relatório da Fase 1 aplica a regra sozinho e escreve o vencedor.

---

## 11. As limitações (e por que são aceitáveis)

| Limitação | Por que não invalida |
|---|---|
| Um nó só (k3d) | a comparação é **relativa**: A, B e C rodam no mesmo ambiente |
| Carga sintética (k6) | é o que permite ter o gabarito exato |
| Aplicação de teste | controlada e igual em todas as execuções |
| VPS compartilhada | os núcleos do k6 são separados, a ordem é sorteada e o ruído fica registrado |
| O detector usa CPU | foi medido: ~0,03 de núcleo, igual nos três modos |
| Partida a frio fora do escopo | o detector é avaliado em regime (depois do aquecimento) |

---

## 12. Onde você está agora 📍

**Pronto:**
- o laboratório inteiro;
- os 6 detectores;
- os 4 vieses corrigidos;
- as regras de avaliação e estatística implementadas e testadas (19 testes);
- as decisões de método fechadas com o orientador (28/out/2026);
- a documentação completa.

**Falta:**
1. Atualizar a VPS (`git pull`, `make build-analysis`, `make selftest`).
2. **Rodar a Fase 1** (~11 h). A regra escolhe o detector do B.
3. Antes da Fase 3: checar os "soluços" de um pod (o modo D não será usado: a Fase 3 compara só A, B e C).
4. **Rodar a Fase 3** (~32 h), analisar e escrever.

```
Pilotos 1–4 ✅ → decisões fechadas ✅ → Fase 1 (~11 h) → campeão → Fase 3 (~32 h) → análise e escrita
```

---

## As 6 frases para você saber dizer

1. "O HPA reage tarde porque espera a CPU subir; o detector tenta avisar antes."
2. "O modo C separa o ganho de detectar do ganho de simplesmente ter mais pods."
3. "O offline não é um teto: avaliar só offline engana sobre o uso real; o detector do HPA é escolhido pelo desempenho ao vivo."
4. "Os pilotos acharam quatro vieses que teriam invalidado 43 h de experimento."
5. "Toda regra de escolha e de avaliação foi escrita antes de ver os resultados."
6. "As limitações afetam o valor absoluto, não a comparação entre A, B e C."
