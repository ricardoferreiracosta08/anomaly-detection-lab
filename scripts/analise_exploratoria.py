"""Análise exploratória da Fase 3 (feita depois de ver os resultados; descritiva).
Lê as séries de réplicas pedidas gravadas em cada execução (results/hpa/series/*.csv,
uma linha a cada 5 s) e calcula, para cada modo e anomalia do gabarito:
  - réplicas pedidas no início da anomalia (média das 10 execuções);
  - quantas janelas começaram no teto (maxReplicas = 8).
Nenhuma execução nova; nenhum dado alterado.
Uso: python3 analise_exploratoria.py <pasta results/hpa/series>
"""
import sys, glob, os
import pandas as pd

SERIES = sys.argv[1]
TETO = 8
GAB = {"burst": [(150, 185), (305, 345), (465, 500)],
       "rampup": [(175, 210), (280, 320), (335, 380), (395, 465)],
       "shift": [(150, 300), (420, 570), (660, 810)]}

linhas = []
for f in sorted(glob.glob(os.path.join(SERIES, "*.csv"))):
    modo, cen, run = os.path.basename(f)[:-4].split("_")
    s = pd.read_csv(f).set_index("offset_seconds")["desired"]
    for k, (ini, _) in enumerate(GAB[cen], 1):
        antes = s[s.index <= ini]
        v = antes.iloc[-1] if len(antes) else s.iloc[0]
        linhas.append(dict(modo=modo, cenario=cen, run=run, anomalia=k, replicas_inicio=v, no_teto=v >= TETO))
d = pd.DataFrame(linhas)
print("Réplicas pedidas no início de cada anomalia (média das execuções):")
print(d.pivot_table(index="modo", columns=["cenario", "anomalia"], values="replicas_inicio", aggfunc="mean").round(1).to_string())
print("\nJanelas iniciadas no teto (soma / total):")
g = d.groupby(["cenario", "modo"]).no_teto.agg(["sum", "count"])
print(g.to_string())
d.to_csv("exploratoria_replicas.csv", index=False)
