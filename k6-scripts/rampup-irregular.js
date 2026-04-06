// rampup-irregular.js — Cenário de Ramp-Up Irregular (Escada Assimétrica)
// =====================================================================
// Projeto: Detecção de Anomalias em Kubernetes — PPGCC/UFMA
// Autor:   Ricardo F. Costa
// Data:    Março 2026
// =====================================================================
//
// DESCRIÇÃO DO PADRÃO ANÔMALO:
//   Simula um crescimento de carga irregular, com degraus assimétricos
//   e patamares de duração variável. Diferente de um ramp-up linear,
//   este padrão apresenta:
//   - Saltos abruptos alternados com crescimento gradual
//   - Patamares curtos que não permitem estabilização
//   - Recuos parciais seguidos de novos picos
//   - Padrão "dente de serra" que desafia baselines fixos
//
//   Típico de:
//   - Tráfego orgânico imprevisível (redes sociais, viral)
//   - Sistemas com múltiplos clientes com padrões dessincronizados
//   - Ambientes com auto-scaling instável (thrashing)
//   - Degradação gradual de dependências externas
//
// PERFIL DE CARGA (VUs ao longo do tempo):
//
//   200|                                          ___
//      |                                    _____|
//   150|                              _____|
//      |                   ____      |
//   100|              ____|    |_____|
//      |         ____|
//    50|    ____|
//      |   |
//    10|___|
//      |________________________________________________> tempo
//       B  S1  S2   S3  recuo  S4    S5    S6   pico  CD
//
// MÉTRICAS ESPERADAS PARA DETECÇÃO:
//   - Taxa de crescimento de request_rate irregular
//   - Variância alta em CPU/memória entre janelas temporais
//   - Latência oscilante (não monotonicamente crescente)
//   - HPA pode oscilar (scale-up/scale-down repetidos)
//
// USO:
//   k6 run --out json=results/rampup.json rampup-irregular.js
// =====================================================================

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import { ENDPOINTS, DEFAULT_THRESHOLDS, HEADERS, tagPhase, samplePayload } from "./config.js";

// Métricas customizadas
const anomalyErrors = new Rate("anomaly_error_rate");
const stepLatency   = new Trend("step_latency", true);
const totalRequests = new Counter("total_requests_count");

export const options = {
  stages: [
    // === Baseline ===
    { duration: "30s", target: 10 },    // warm-up

    // === Degrau 1: Salto moderado ===
    { duration: "10s", target: 40 },    // salto rápido
    { duration: "45s", target: 40 },    // patamar curto

    // === Degrau 2: Crescimento gradual ===
    { duration: "30s", target: 60 },    // subida lenta
    { duration: "1m",  target: 65 },    // patamar com leve drift

    // === Degrau 3: Salto grande ===
    { duration: "5s",  target: 100 },   // salto abrupto
    { duration: "30s", target: 100 },   // patamar breve

    // === Recuo parcial (confunde baselines) ===
    { duration: "10s", target: 55 },    // queda parcial (não total)
    { duration: "1m",  target: 55 },    // estabiliza abaixo do pico

    // === Degrau 4: Novo salto acima do anterior ===
    { duration: "10s", target: 110 },   // ultrapassa pico anterior
    { duration: "30s", target: 110 },   // patamar

    // === Degrau 5: Crescimento acelerado ===
    { duration: "15s", target: 150 },   // aceleração
    { duration: "30s", target: 155 },   // drift leve

    // === Degrau 6: Pico máximo ===
    { duration: "10s", target: 200 },   // pico
    { duration: "1m",  target: 200 },   // sustenta

    // === Cool-down irregular ===
    { duration: "15s", target: 120 },   // queda parcial
    { duration: "30s", target: 80 },    // continua caindo
    { duration: "20s", target: 30 },    // quase normal
    { duration: "1m",  target: 0 },     // encerra
  ],

  thresholds: {
    ...DEFAULT_THRESHOLDS,
    step_latency: ["p(95)<3000"],
  },
};

// Distribuição de endpoints varia com a carga
// Mais VUs = mais requisições pesadas (simula comportamento real)
function selectEndpoint() {
  const vus = __VU || 1;
  const pressure = Math.min(vus / 200, 1); // 0..1

  const roll = Math.random();
  if (roll < 0.2 + pressure * 0.4) {
    // Quanto mais carga, mais requisições pesadas
    return { url: ENDPOINTS.heavy, type: "heavy" };
  } else if (roll < 0.5 + pressure * 0.2) {
    return { url: ENDPOINTS.moderate, type: "moderate" };
  } else if (roll < 0.85) {
    return { url: ENDPOINTS.light, type: "light" };
  } else {
    return { url: ENDPOINTS.write, type: "write" };
  }
}

export default function () {
  group("rampup_irregular", function () {
    const endpoint = selectEndpoint();
    let res;

    if (endpoint.type === "write") {
      res = http.post(endpoint.url, samplePayload(), {
        ...HEADERS,
        tags: { endpoint_type: endpoint.type },
      });
    } else {
      res = http.get(endpoint.url, {
        tags: { endpoint_type: endpoint.type },
      });
    }

    stepLatency.add(res.timings.duration);
    anomalyErrors.add(res.status >= 400);
    totalRequests.add(1);

    check(res, {
      "status < 500":     (r) => r.status < 500,
      "duration < 3s":    (r) => r.timings.duration < 3000,
      "body not empty":   (r) => r.body && r.body.length > 0,
    });

    // Sleep variável: mais curto sob carga alta (mais pressão)
    const baseSleep = 0.5;
    const jitter = Math.random() * 1.5;
    sleep(baseSleep + jitter);
  });
}

export function handleSummary(data) {
  const summary = {
    scenario: "rampup-irregular",
    timestamp: new Date().toISOString(),
    total_requests: data.metrics.total_requests_count?.values?.count || 0,
    error_rate: data.metrics.anomaly_error_rate?.values?.rate || 0,
    step_p50: data.metrics.step_latency?.values?.["p(50)"] || 0,
    step_p95: data.metrics.step_latency?.values?.["p(95)"] || 0,
    step_p99: data.metrics.step_latency?.values?.["p(99)"] || 0,
    http_req_duration_avg: data.metrics.http_req_duration?.values?.avg || 0,
  };

  return {
    "results/rampup-summary.json": JSON.stringify(summary, null, 2),
    stdout: `\n=== RAMP-UP IRREGULAR SUMMARY ===\n` +
            `Total requests: ${summary.total_requests}\n` +
            `Error rate: ${(summary.error_rate * 100).toFixed(2)}%\n` +
            `Step latency p50: ${summary.step_p50.toFixed(0)}ms\n` +
            `Step latency p95: ${summary.step_p95.toFixed(0)}ms\n` +
            `Step latency p99: ${summary.step_p99.toFixed(0)}ms\n`,
  };
}
