# Fase 1 — IC da média (TLC) e t de Student

Entrada: `../results_qualificacao/detection_results_offline_online.csv` · 90 avaliações · N por célula: 3 · α = 0.05

## F1

| cenário | detector | N | média | DP | H | IC95% | H/Ȳ | Shapiro p |
|---|---|---|---|---|---|---|---|---|
| burst | EWMA | 3 | 0.431 | 0.089 | 0.221 | 0.210 – 0.652 | 51.3% | 0.958 |
| burst | EWMA_online | 3 | 0.337 | 0.023 | 0.056 | 0.281 – 0.394 | 16.7% | 0.000 |
| burst | IF | 3 | 0.467 | 0.076 | 0.190 | 0.277 – 0.656 | 40.7% | 0.637 |
| burst | IF_online | 3 | 0.462 | 0.147 | 0.365 | 0.097 – 0.827 | 78.9% | 0.816 |
| burst | LOF | 3 | 0.100 | 0.049 | 0.123 | -0.022 – 0.223 | 122.1% | 0.985 |
| burst | LOF_online | 3 | 0.387 | 0.159 | 0.395 | -0.007 – 0.782 | 101.8% | 0.784 |
| burst | DBSCAN | 3 | 0.256 | 0.138 | 0.344 | -0.088 – 0.599 | 134.5% | 0.409 |
| burst | DBSCAN_online | 3 | 0.601 | 0.060 | 0.150 | 0.452 – 0.751 | 24.9% | 0.608 |
| burst | AE | 3 | 0.366 | 0.045 | 0.111 | 0.255 – 0.477 | 30.3% | 0.911 |
| burst | AE_online | 3 | 0.614 | 0.119 | 0.296 | 0.318 – 0.909 | 48.2% | 0.085 |
| rampup | EWMA | 3 | 0.425 | 0.281 | 0.699 | -0.274 – 1.123 | 164.6% | 0.707 |
| rampup | EWMA_online | 3 | 0.193 | 0.169 | 0.419 | -0.226 – 0.612 | 216.7% | 0.233 |
| rampup | IF | 3 | 0.184 | 0.072 | 0.178 | 0.005 – 0.362 | 97.0% | 0.463 |
| rampup | IF_online | 3 | 0.471 | 0.260 | 0.646 | -0.174 – 1.117 | 137.0% | 0.664 |
| rampup | LOF | 3 | 0.035 | 0.035 | 0.086 | -0.051 – 0.120 | 248.4% | 1.000 |
| rampup | LOF_online | 3 | 0.500 | 0.256 | 0.635 | -0.136 – 1.135 | 127.2% | 0.781 |
| rampup | DBSCAN | 3 | 0.158 | 0.144 | 0.357 | -0.199 – 0.514 | 226.1% | 0.598 |
| rampup | DBSCAN_online | 3 | 0.527 | 0.160 | 0.398 | 0.129 – 0.926 | 75.6% | 0.844 |
| rampup | AE | 3 | 0.145 | 0.152 | 0.378 | -0.233 – 0.523 | 260.2% | 0.204 |
| rampup | AE_online | 3 | 0.514 | 0.102 | 0.253 | 0.261 – 0.767 | 49.2% | 0.061 |
| shift | EWMA | 3 | 0.059 | 0.069 | 0.171 | -0.112 – 0.230 | 290.4% | 0.593 |
| shift | EWMA_online | 3 | 0.071 | 0.062 | 0.153 | -0.082 – 0.224 | 216.6% | 0.220 |
| shift | IF | 3 | 0.242 | 0.027 | 0.067 | 0.175 – 0.309 | 27.8% | 0.637 |
| shift | IF_online | 3 | 0.152 | 0.060 | 0.148 | 0.004 – 0.300 | 97.5% | 0.927 |
| shift | LOF | 3 | 0.254 | 0.089 | 0.221 | 0.032 – 0.475 | 87.2% | 0.780 |
| shift | LOF_online | 3 | 0.215 | 0.061 | 0.151 | 0.064 – 0.366 | 70.3% | 0.386 |
| shift | DBSCAN | 3 | 0.205 | 0.022 | 0.055 | 0.149 – 0.260 | 27.1% | 0.926 |
| shift | DBSCAN_online | 3 | 0.232 | 0.068 | 0.169 | 0.063 – 0.401 | 72.8% | 0.242 |
| shift | AE | 3 | 0.189 | 0.051 | 0.128 | 0.061 – 0.317 | 67.6% | 0.890 |
| shift | AE_online | 3 | 0.337 | 0.065 | 0.162 | 0.175 – 0.499 | 48.1% | 0.552 |

## Teste t (F1, slide 66) e teste visual (slide 64)

| cenário | par | t | gl | p | visual | conclusão |
|---|---|---|---|---|---|---|
| burst | EWMA × EWMA_online | 1.76 | 4 | 0.1529 | Caso 2 | sem diferença significativa |
| burst | EWMA × IF | -0.53 | 4 | 0.6236 | Caso 2 | sem diferença significativa |
| burst | EWMA × IF_online | -0.32 | 4 | 0.7682 | Caso 2 | sem diferença significativa |
| burst | EWMA × LOF | 5.63 | 4 | 0.0049 | Caso 3 | médias diferentes |
| burst | EWMA × LOF_online | 0.41 | 4 | 0.7014 | Caso 2 | sem diferença significativa |
| burst | EWMA × DBSCAN | 1.84 | 4 | 0.1390 | Caso 2 | sem diferença significativa |
| burst | EWMA × DBSCAN_online | -2.75 | 4 | 0.0514 | Caso 2 | sem diferença significativa |
| burst | EWMA × AE | 1.13 | 4 | 0.3228 | Caso 2 | sem diferença significativa |
| burst | EWMA × AE_online | -2.13 | 4 | 0.1001 | Caso 2 | sem diferença significativa |
| burst | EWMA_online × IF | -2.81 | 4 | 0.0483 | Caso 2 | médias diferentes |
| burst | EWMA_online × IF_online | -1.45 | 4 | 0.2200 | Caso 2 | sem diferença significativa |
| burst | EWMA_online × LOF | 7.56 | 4 | 0.0016 | Caso 1 | médias diferentes |
| burst | EWMA_online × LOF_online | -0.54 | 4 | 0.6177 | Caso 2 | sem diferença significativa |
| burst | EWMA_online × DBSCAN | 1.01 | 4 | 0.3696 | Caso 2 | sem diferença significativa |
| burst | EWMA_online × DBSCAN_online | -7.10 | 4 | 0.0021 | Caso 1 | médias diferentes |
| burst | EWMA_online × AE | -0.99 | 4 | 0.3786 | Caso 2 | sem diferença significativa |
| burst | EWMA_online × AE_online | -3.95 | 4 | 0.0169 | Caso 2 | médias diferentes |
| burst | IF × IF_online | 0.05 | 4 | 0.9634 | Caso 2 | sem diferença significativa |
| burst | IF × LOF | 6.98 | 4 | 0.0022 | Caso 1 | médias diferentes |
| burst | IF × LOF_online | 0.78 | 4 | 0.4796 | Caso 2 | sem diferença significativa |
| burst | IF × DBSCAN | 2.31 | 4 | 0.0818 | Caso 2 | sem diferença significativa |
| burst | IF × DBSCAN_online | -2.40 | 4 | 0.0746 | Caso 2 | sem diferença significativa |
| burst | IF × AE | 1.97 | 4 | 0.1201 | Caso 2 | sem diferença significativa |
| burst | IF × AE_online | -1.80 | 4 | 0.1465 | Caso 2 | sem diferença significativa |
| burst | IF_online × LOF | 4.04 | 4 | 0.0156 | Caso 2 | médias diferentes |
| burst | IF_online × LOF_online | 0.60 | 4 | 0.5826 | Caso 2 | sem diferença significativa |
| burst | IF_online × DBSCAN | 1.77 | 4 | 0.1512 | Caso 2 | sem diferença significativa |
| burst | IF_online × DBSCAN_online | -1.52 | 4 | 0.2032 | Caso 2 | sem diferença significativa |
| burst | IF_online × AE | 1.08 | 4 | 0.3395 | Caso 2 | sem diferença significativa |
| burst | IF_online × AE_online | -1.39 | 4 | 0.2373 | Caso 2 | sem diferença significativa |
| burst | LOF × LOF_online | -2.99 | 4 | 0.0404 | Caso 2 | médias diferentes |
| burst | LOF × DBSCAN | -1.83 | 4 | 0.1414 | Caso 2 | sem diferença significativa |
| burst | LOF × DBSCAN_online | -11.14 | 4 | 0.0004 | Caso 1 | médias diferentes |
| burst | LOF × AE | -6.91 | 4 | 0.0023 | Caso 1 | médias diferentes |
| burst | LOF × AE_online | -6.90 | 4 | 0.0023 | Caso 1 | médias diferentes |
| burst | LOF_online × DBSCAN | 1.08 | 4 | 0.3394 | Caso 2 | sem diferença significativa |
| burst | LOF_online × DBSCAN_online | -2.18 | 4 | 0.0947 | Caso 2 | sem diferença significativa |
| burst | LOF_online × AE | 0.23 | 4 | 0.8330 | Caso 2 | sem diferença significativa |
| burst | LOF_online × AE_online | -1.97 | 4 | 0.1198 | Caso 2 | sem diferença significativa |
| burst | DBSCAN × DBSCAN_online | -3.97 | 4 | 0.0166 | Caso 3 | médias diferentes |
| burst | DBSCAN × AE | -1.31 | 4 | 0.2589 | Caso 2 | sem diferença significativa |
| burst | DBSCAN × AE_online | -3.40 | 4 | 0.0274 | Caso 3 | médias diferentes |
| burst | DBSCAN_online × AE | 5.44 | 4 | 0.0056 | Caso 3 | médias diferentes |
| burst | DBSCAN_online × AE_online | -0.16 | 4 | 0.8809 | Caso 2 | sem diferença significativa |
| burst | AE × AE_online | -3.37 | 4 | 0.0280 | Caso 2 | médias diferentes |
| rampup | EWMA × EWMA_online | 1.22 | 4 | 0.2887 | Caso 2 | sem diferença significativa |
| rampup | EWMA × IF | 1.44 | 4 | 0.2243 | Caso 2 | sem diferença significativa |
| rampup | EWMA × IF_online | -0.21 | 4 | 0.8428 | Caso 2 | sem diferença significativa |
| rampup | EWMA × LOF | 2.38 | 4 | 0.0756 | Caso 2 | sem diferença significativa |
| rampup | EWMA × LOF_online | -0.34 | 4 | 0.7498 | Caso 2 | sem diferença significativa |
| rampup | EWMA × DBSCAN | 1.46 | 4 | 0.2170 | Caso 2 | sem diferença significativa |
| rampup | EWMA × DBSCAN_online | -0.55 | 4 | 0.6118 | Caso 2 | sem diferença significativa |
| rampup | EWMA × AE | 1.51 | 4 | 0.2049 | Caso 2 | sem diferença significativa |
| rampup | EWMA × AE_online | -0.52 | 4 | 0.6312 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × IF | 0.09 | 4 | 0.9344 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × IF_online | -1.56 | 4 | 0.1948 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × LOF | 1.60 | 4 | 0.1854 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × LOF_online | -1.73 | 4 | 0.1582 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × DBSCAN | 0.28 | 4 | 0.7950 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × DBSCAN_online | -2.49 | 4 | 0.0677 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × AE | 0.37 | 4 | 0.7334 | Caso 2 | sem diferença significativa |
| rampup | EWMA_online × AE_online | -2.82 | 4 | 0.0476 | Caso 2 | médias diferentes |
| rampup | IF × IF_online | -1.85 | 4 | 0.1386 | Caso 2 | sem diferença significativa |
| rampup | IF × LOF | 3.25 | 4 | 0.0314 | Caso 2 | médias diferentes |
| rampup | IF × LOF_online | -2.06 | 4 | 0.1087 | Caso 2 | sem diferença significativa |
| rampup | IF × DBSCAN | 0.28 | 4 | 0.7911 | Caso 2 | sem diferença significativa |
| rampup | IF × DBSCAN_online | -3.38 | 4 | 0.0277 | Caso 2 | médias diferentes |
| rampup | IF × AE | 0.40 | 4 | 0.7112 | Caso 2 | sem diferença significativa |
| rampup | IF × AE_online | -4.59 | 4 | 0.0101 | Caso 3 | médias diferentes |
| rampup | IF_online × LOF | 2.89 | 4 | 0.0447 | Caso 2 | médias diferentes |
| rampup | IF_online × LOF_online | -0.13 | 4 | 0.8998 | Caso 2 | sem diferença significativa |
| rampup | IF_online × DBSCAN | 1.83 | 4 | 0.1412 | Caso 2 | sem diferença significativa |
| rampup | IF_online × DBSCAN_online | -0.32 | 4 | 0.7668 | Caso 2 | sem diferença significativa |
| rampup | IF_online × AE | 1.88 | 4 | 0.1340 | Caso 2 | sem diferença significativa |
| rampup | IF_online × AE_online | -0.27 | 4 | 0.8035 | Caso 2 | sem diferença significativa |
| rampup | LOF × LOF_online | -3.12 | 4 | 0.0355 | Caso 2 | médias diferentes |
| rampup | LOF × DBSCAN | -1.45 | 4 | 0.2219 | Caso 2 | sem diferença significativa |
| rampup | LOF × DBSCAN_online | -5.20 | 4 | 0.0065 | Caso 1 | médias diferentes |
| rampup | LOF × AE | -1.23 | 4 | 0.2863 | Caso 2 | sem diferença significativa |
| rampup | LOF × AE_online | -7.73 | 4 | 0.0015 | Caso 1 | médias diferentes |
| rampup | LOF_online × DBSCAN | 2.02 | 4 | 0.1136 | Caso 2 | sem diferença significativa |
| rampup | LOF_online × DBSCAN_online | -0.16 | 4 | 0.8813 | Caso 2 | sem diferença significativa |
| rampup | LOF_online × AE | 2.06 | 4 | 0.1082 | Caso 2 | sem diferença significativa |
| rampup | LOF_online × AE_online | -0.09 | 4 | 0.9312 | Caso 2 | sem diferença significativa |
| rampup | DBSCAN × DBSCAN_online | -2.97 | 4 | 0.0410 | Caso 2 | médias diferentes |
| rampup | DBSCAN × AE | 0.10 | 4 | 0.9232 | Caso 2 | sem diferença significativa |
| rampup | DBSCAN × AE_online | -3.51 | 4 | 0.0247 | Caso 2 | médias diferentes |
| rampup | DBSCAN_online × AE | 2.99 | 4 | 0.0402 | Caso 2 | médias diferentes |
| rampup | DBSCAN_online × AE_online | 0.12 | 4 | 0.9104 | Caso 2 | sem diferença significativa |
| rampup | AE × AE_online | -3.49 | 4 | 0.0251 | Caso 2 | médias diferentes |
| shift | EWMA × EWMA_online | -0.22 | 4 | 0.8354 | Caso 2 | sem diferença significativa |
| shift | EWMA × IF | -4.28 | 4 | 0.0128 | Caso 3 | médias diferentes |
| shift | EWMA × IF_online | -1.77 | 4 | 0.1511 | Caso 2 | sem diferença significativa |
| shift | EWMA × LOF | -3.00 | 4 | 0.0401 | Caso 2 | médias diferentes |
| shift | EWMA × LOF_online | -2.94 | 4 | 0.0424 | Caso 2 | médias diferentes |
| shift | EWMA × DBSCAN | -3.49 | 4 | 0.0252 | Caso 2 | médias diferentes |
| shift | EWMA × DBSCAN_online | -3.10 | 4 | 0.0362 | Caso 3 | médias diferentes |
| shift | EWMA × AE | -2.62 | 4 | 0.0587 | Caso 2 | sem diferença significativa |
| shift | EWMA × AE_online | -5.08 | 4 | 0.0071 | Caso 3 | médias diferentes |
| shift | EWMA_online × IF | -4.40 | 4 | 0.0117 | Caso 3 | médias diferentes |
| shift | EWMA_online × IF_online | -1.64 | 4 | 0.1758 | Caso 2 | sem diferença significativa |
| shift | EWMA_online × LOF | -2.92 | 4 | 0.0430 | Caso 2 | médias diferentes |
| shift | EWMA_online × LOF_online | -2.88 | 4 | 0.0449 | Caso 2 | médias diferentes |
| shift | EWMA_online × DBSCAN | -3.54 | 4 | 0.0241 | Caso 2 | médias diferentes |
| shift | EWMA_online × DBSCAN_online | -3.05 | 4 | 0.0382 | Caso 2 | médias diferentes |
| shift | EWMA_online × AE | -2.55 | 4 | 0.0633 | Caso 2 | sem diferença significativa |
| shift | EWMA_online × AE_online | -5.14 | 4 | 0.0068 | Caso 3 | médias diferentes |
| shift | IF × IF_online | 2.37 | 4 | 0.0766 | Caso 2 | sem diferença significativa |
| shift | IF × LOF | -0.22 | 4 | 0.8370 | Caso 2 | sem diferença significativa |
| shift | IF × LOF_online | 0.71 | 4 | 0.5188 | Caso 2 | sem diferença significativa |
| shift | IF × DBSCAN | 1.84 | 4 | 0.1391 | Caso 2 | sem diferença significativa |
| shift | IF × DBSCAN_online | 0.23 | 4 | 0.8292 | Caso 2 | sem diferença significativa |
| shift | IF × AE | 1.58 | 4 | 0.1890 | Caso 2 | sem diferença significativa |
| shift | IF × AE_online | -2.33 | 4 | 0.0802 | Caso 2 | sem diferença significativa |
| shift | IF_online × LOF | -1.64 | 4 | 0.1763 | Caso 2 | sem diferença significativa |
| shift | IF_online × LOF_online | -1.27 | 4 | 0.2718 | Caso 2 | sem diferença significativa |
| shift | IF_online × DBSCAN | -1.43 | 4 | 0.2270 | Caso 2 | sem diferença significativa |
| shift | IF_online × DBSCAN_online | -1.53 | 4 | 0.2004 | Caso 2 | sem diferença significativa |
| shift | IF_online × AE | -0.81 | 4 | 0.4641 | Caso 2 | sem diferença significativa |
| shift | IF_online × AE_online | -3.62 | 4 | 0.0224 | Caso 3 | médias diferentes |
| shift | LOF × LOF_online | 0.63 | 4 | 0.5657 | Caso 2 | sem diferença significativa |
| shift | LOF × DBSCAN | 0.93 | 4 | 0.4069 | Caso 2 | sem diferença significativa |
| shift | LOF × DBSCAN_online | 0.33 | 4 | 0.7561 | Caso 2 | sem diferença significativa |
| shift | LOF × AE | 1.09 | 4 | 0.3365 | Caso 2 | sem diferença significativa |
| shift | LOF × AE_online | -1.31 | 4 | 0.2619 | Caso 2 | sem diferença significativa |
| shift | LOF_online × DBSCAN | 0.27 | 4 | 0.7991 | Caso 2 | sem diferença significativa |
| shift | LOF_online × DBSCAN_online | -0.33 | 4 | 0.7577 | Caso 2 | sem diferença significativa |
| shift | LOF_online × AE | 0.56 | 4 | 0.6035 | Caso 2 | sem diferença significativa |
| shift | LOF_online × AE_online | -2.37 | 4 | 0.0766 | Caso 2 | sem diferença significativa |
| shift | DBSCAN × DBSCAN_online | -0.67 | 4 | 0.5414 | Caso 2 | sem diferença significativa |
| shift | DBSCAN × AE | 0.49 | 4 | 0.6528 | Caso 2 | sem diferença significativa |
| shift | DBSCAN × AE_online | -3.32 | 4 | 0.0293 | Caso 2 | médias diferentes |
| shift | DBSCAN_online × AE | 0.88 | 4 | 0.4291 | Caso 2 | sem diferença significativa |
| shift | DBSCAN_online × AE_online | -1.92 | 4 | 0.1266 | Caso 2 | sem diferença significativa |
| shift | AE × AE_online | -3.09 | 4 | 0.0367 | Caso 2 | médias diferentes |

Com mais de 2 detectores por cenário, os testes par a par são exploratórios: o slide 65 indica ANOVA antes dos pares.
