// warmup.js — Aquecimento antes de cada execução (não é um cenário do experimento)
// =====================================================================
// Projeto: Detecção de Anomalias em Kubernetes — PPGCC/UFMA
// Autor:   Ricardo F. Costa
// Data:    Outubro 2026
// =====================================================================
//
// POR QUÊ:
//   Entre execuções o cluster fica parado (cooldown). A janela de referência do
//   detector online (5 min) ficava feita só desse silêncio e o tráfego NORMAL do
//   início do roteiro era alarmado (piloto 2: 53–87% de alertas nos primeiros
//   150 s, sem anomalia — ver docs/PILOTOS.md). O aquecimento enche a referência
//   com "normal com carga" antes de o roteiro começar.
//
// O QUE FAZ:
//   Carga constante com o mesmo mix de requisições da fase normal de cada roteiro
//   (cópia fiel da lógica normal de burst-anomaly.js, rampup-irregular.js e
//   load-shifting.js; os roteiros não são alterados). Não gera CSV, não entra na
//   avaliação e não grava summary.
//   Termina com uma rampa de descida (VUS → 0 em RAMP_DOWN s). O bin/experiment.sh
//   começa o roteiro RAMP_DOWN s antes do fim do aquecimento: enquanto o aquecimento
//   desce, o roteiro sobe (0 → VUS em 30 s, sua 1ª rampa) e a carga total fica
//   constante na troca (piloto 3: sem isso, AE/DBSCAN/LOF alarmavam de 15 a 45 s).
//
// VARIÁVEIS (passadas pelo bin/experiment.sh):
//   SCENARIO  burst | rampup | shift   (qual mix normal reproduzir)
//   VUS        VUs constantes (nível no fim da 1ª rampa do roteiro)
//   WARMUP_SECONDS duração total em segundos, rampa de descida incluída
//   RAMP_DOWN  segundos da rampa de descida no fim (padrão 30 = 1ª rampa dos roteiros)
// =====================================================================

import http from "k6/http";
import { sleep } from "k6";
import { ENDPOINTS, tagPhase } from "./config.js";

const SCENARIO = __ENV.SCENARIO || "burst";
const VUS = parseInt(__ENV.VUS || "10", 10);
const SECONDS = parseInt(__ENV.WARMUP_SECONDS || "330", 10);
const RAMP_DOWN = Math.min(parseInt(__ENV.RAMP_DOWN || "30", 10), SECONDS);
const DURATION = `${SECONDS}s`;

export const options = {
  scenarios: {
    warmup: {
      executor: "ramping-vus",
      startVUs: VUS,
      stages: [
        { duration: `${SECONDS - RAMP_DOWN}s`, target: VUS },   // carga normal constante
        { duration: `${RAMP_DOWN}s`, target: 0 },               // desce enquanto o roteiro sobe
      ],
      gracefulRampDown: "0s",
    },
  },
};

// Mix da fase normal de cada roteiro ─────────────────────────────────────────
function normalBurst() {
  // burst-anomaly.js, fase "normal" (VU ≤ 15): só leitura leve, sleep 1–2 s
  http.get(ENDPOINTS.light, tagPhase("warmup"));
  sleep(1 + Math.random());
}

function normalRampup() {
  // rampup-irregular.js, selectEndpoint(): o mix depende do número do VU
  const vus = __VU || 1;
  const pressure = Math.min(vus / 200, 1);
  const roll = Math.random();
  if (roll < 0.2 + pressure * 0.4) {
    http.get(ENDPOINTS.heavy, tagPhase("warmup"));
  } else if (roll < 0.5 + pressure * 0.2) {
    http.get(ENDPOINTS.moderate, tagPhase("warmup"));
  } else if (roll < 0.85) {
    http.get(ENDPOINTS.light, tagPhase("warmup"));
  } else {
    http.post(ENDPOINTS.write, JSON.stringify({ name: `item-${Date.now()}`, value: Math.random() * 1000,
      category: ["compute", "memory", "network", "storage"][Math.floor(Math.random() * 4)] }),
      { headers: { "Content-Type": "application/json" }, tags: { phase: "warmup" } });
  }
  sleep(0.5 + Math.random() * 1.5);
}

function normalShift() {
  // load-shifting.js, fase "baseline": 90% leve, 10% moderada, sleep 0,8–1,2 s
  const url = Math.random() < 0.9 ? ENDPOINTS.light : ENDPOINTS.moderate;
  http.get(url, tagPhase("warmup"));
  sleep(0.8 + Math.random() * 0.4);
}

const MIX = { burst: normalBurst, rampup: normalRampup, shift: normalShift };
if (!MIX[SCENARIO]) {
  throw new Error(`SCENARIO inválido: ${SCENARIO} (use burst, rampup ou shift)`);
}

export default function () {
  MIX[SCENARIO]();
}

export function handleSummary(data) {
  const reqs = data.metrics.http_reqs?.values?.count || 0;
  const fail = data.metrics.http_req_failed?.values?.rate || 0;
  return {
    stdout: `aquecimento ${SCENARIO}: ${VUS} VUs, ${DURATION}, ${reqs} requisições, ${(fail * 100).toFixed(1)}% falhas\n`,
  };
}
