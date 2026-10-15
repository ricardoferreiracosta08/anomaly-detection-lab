// burst-anomaly.js — Cenário de Burst (Rajada Súbita)
// =====================================================================
// Projeto: Detecção de Anomalias em Kubernetes — PPGCC/UFMA
// Autor:   Ricardo F. Costa
// Data:    Março 2026
// =====================================================================
//
// DESCRIÇÃO DO PADRÃO ANÔMALO:
//   Simula rajadas súbitas e repetidas de tráfego, intercaladas com 
//   períodos de carga normal. Este padrão é típico de:
//   - Ataques DDoS de baixa intensidade
//   - Campanhas de marketing virais
//   - Falhas em retry logic de clientes upstream
//   - Cron jobs simultâneos disparando requisições
//
// PERFIL DE CARGA:
//   [Normal 2min] → [BURST 30s] → [Normal 2min] → [BURST 30s] → 
//   [Normal 2min] → [BURST INTENSO 30s] → [Recovery 2min]
//
// MÉTRICAS ESPERADAS PARA DETECÇÃO:
//   - Picos abruptos em request_rate (>5x baseline)
//   - Spike de CPU e memória nos pods
//   - Aumento súbito de latência (p95, p99)
//   - Possível aumento de error_rate (HTTP 5xx)
//
// USO:
//   k6 run --out json=results/burst.json burst-anomaly.js
//   k6 run --out experimental-prometheus-rw burst-anomaly.js
// =====================================================================

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import { ENDPOINTS, DEFAULT_THRESHOLDS, HEADERS, tagPhase, samplePayload } from "./config.js";

// Métricas customizadas para análise posterior
const anomalyErrors   = new Rate("anomaly_error_rate");
const burstLatency    = new Trend("burst_phase_latency", true);
const normalLatency   = new Trend("normal_phase_latency", true);
const totalRequests   = new Counter("total_requests_count");

export const options = {
  stages: [
    // === FASE 1: Baseline normal ===
    { duration: "30s", target: 10 },   // warm-up
    { duration: "2m",  target: 10 },   // baseline estável

    // === FASE 2: Primeiro burst ===
    { duration: "5s",  target: 80 },   // rampa abrupta → 80 VUs
    { duration: "25s", target: 80 },   // sustenta burst
    { duration: "5s",  target: 10 },   // queda abrupta

    // === FASE 3: Recuperação ===
    { duration: "2m",  target: 10 },   // volta ao normal

    // === FASE 4: Segundo burst (mais intenso) ===
    { duration: "5s",  target: 120 },  // rampa → 120 VUs
    { duration: "25s", target: 120 },  // sustenta
    { duration: "5s",  target: 10 },   // queda

    // === FASE 5: Recuperação ===
    { duration: "2m",  target: 10 },   // volta ao normal

    // === FASE 6: Burst máximo ===
    { duration: "3s",  target: 200 },  // rampa explosiva → 200 VUs
    { duration: "30s", target: 200 },  // sustenta carga máxima
    { duration: "5s",  target: 10 },   // queda

    // === FASE 7: Recovery final ===
    { duration: "2m",  target: 0 },    // cool-down gradual
  ],

  thresholds: {
    ...DEFAULT_THRESHOLDS,
    "burst_phase_latency":  ["p(95)<5000"],  // burst pode ter latência alta
    "normal_phase_latency": ["p(95)<500"],   // normal deve ser rápido
  },
};

// Determina a fase atual baseado no tempo de execução
function getCurrentPhase() {
  const elapsed = __ITER !== undefined ? Date.now() : 0;
  const vus = __VU;
  if (vus <= 15) return "normal";
  if (vus <= 85) return "burst_low";
  if (vus <= 125) return "burst_medium";
  return "burst_high";
}

export default function () {
  const phase = getCurrentPhase();
  const isBurst = phase.startsWith("burst");

  group("burst_scenario", function () {
    // Durante burst: mistura de endpoints leves e pesados
    // Durante normal: apenas endpoints leves
    if (isBurst) {
      // 60% heavy, 30% moderate, 10% write — força degradação
      const roll = Math.random();
      let res;

      if (roll < 0.6) {
        res = http.get(ENDPOINTS.heavy, tagPhase(phase));
      } else if (roll < 0.9) {
        res = http.get(ENDPOINTS.moderate, tagPhase(phase));
      } else {
        res = http.post(ENDPOINTS.write, samplePayload(), {
          ...HEADERS,
          ...tagPhase(phase),
        });
      }

      burstLatency.add(res.timings.duration);
      anomalyErrors.add(res.status >= 400);
      totalRequests.add(1);

      check(res, {
        "burst: status < 500": (r) => r.status < 500,
        "burst: duration < 5s": (r) => r.timings.duration < 5000,
      });

      // Sleep curto durante burst para maximizar pressão
      sleep(Math.random() * 0.5);
    } else {
      // Carga normal: leituras leves com sleep maior
      const res = http.get(ENDPOINTS.light, tagPhase(phase));

      normalLatency.add(res.timings.duration);
      anomalyErrors.add(res.status >= 400);
      totalRequests.add(1);

      check(res, {
        "normal: status 200": (r) => r.status === 200,
        "normal: duration < 500ms": (r) => r.timings.duration < 500,
      });

      sleep(1 + Math.random());
    }
  });
}

export function handleSummary(data) {
  const summary = {
    scenario: "burst-anomaly",
    timestamp: new Date().toISOString(),
    total_requests: data.metrics.total_requests_count?.values?.count || 0,
    error_rate: data.metrics.anomaly_error_rate?.values?.rate || 0,
    burst_p95: data.metrics.burst_phase_latency?.values?.["p(95)"] || 0,
    normal_p95: data.metrics.normal_phase_latency?.values?.["p(95)"] || 0,
    http_req_duration_avg: data.metrics.http_req_duration?.values?.avg || 0,
    http_req_duration_p95: data.metrics.http_req_duration?.values?.["p(95)"] || 0,
  };

  const out = {
    stdout: `\n=== BURST ANOMALY SUMMARY ===\n` +
            `Total requests: ${summary.total_requests}\n` +
            `Error rate: ${(summary.error_rate * 100).toFixed(2)}%\n` +
            `Normal p95: ${summary.normal_p95.toFixed(0)}ms\n` +
            `Burst p95: ${summary.burst_p95.toFixed(0)}ms\n` +
            `Latency ratio (burst/normal): ${(summary.burst_p95 / Math.max(summary.normal_p95, 1)).toFixed(1)}x\n`,
  };
  // Summary completo por execução (avg, med, p90, p95, p99...) para o IC do k6.
  // SUMMARY_FILE é passado pelo bin/experiment.sh (ex.: /results/k6/burst_run1.json).
  if (__ENV.SUMMARY_FILE) {
    out[__ENV.SUMMARY_FILE] = JSON.stringify({ scenario_summary: summary, metrics: data.metrics }, null, 2);
  }
  return out;
}
