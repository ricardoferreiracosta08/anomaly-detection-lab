// load-shifting.js — Cenário de Load Shifting (Mudança de Perfil de Carga)
// =====================================================================
// Projeto: Detecção de Anomalias em Kubernetes — PPGCC/UFMA
// Autor:   Ricardo F. Costa
// Data:    Março 2026
// =====================================================================
//
// DESCRIÇÃO DO PADRÃO ANÔMALO:
//   Simula mudanças abruptas no PERFIL da carga, não apenas no volume.
//   O número de VUs pode permanecer relativamente constante, mas a 
//   natureza das requisições muda drasticamente, causando:
//   - Mudança de workload read-heavy → write-heavy
//   - Transição de CPU-bound → memory-bound → I/O-bound
//   - Alteração no mix de endpoints acessados
//
//   Este é o padrão mais sutil e difícil de detectar por métodos
//   baseados apenas em request_rate ou VU count. Requer análise de
//   múltiplas métricas correlacionadas.
//
//   Típico de:
//   - Mudança de comportamento de usuários (horário comercial → batch)
//   - Migração de tráfego entre microsserviços
//   - Ataques slow-rate que mudam o perfil de acesso
//   - Degradação de cache (cache miss rate aumenta progressivamente)
//
// PERFIL DE CARGA:
//   VUs constantes (~50), mas o MIX de requisições muda:
//
//   Fase 1 (Normal):     90% GET light  | 10% GET moderate
//   Fase 2 (Shift→CPU):  20% GET light  | 60% GET heavy   | 20% POST
//   Fase 3 (Recovery):   90% GET light  | 10% GET moderate  
//   Fase 4 (Shift→Write):10% GET light  | 20% GET moderate | 70% POST
//   Fase 5 (Shift→Mixed):30% cada tipo (distribuição uniforme)
//   Fase 6 (Recovery):   90% GET light  | 10% GET moderate
//
// MÉTRICAS ESPERADAS PARA DETECÇÃO:
//   - request_rate estável MAS latência/CPU/memória mudam
//   - Mudança na distribuição de status codes (mais 5xx em writes)
//   - Alteração no perfil de uso de CPU vs. memória vs. I/O
//   - Métricas por endpoint divergem do padrão histórico
//
// USO:
//   k6 run --out json=results/shifting.json load-shifting.js
// =====================================================================

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter, Gauge } from "k6/metrics";
import { ENDPOINTS, DEFAULT_THRESHOLDS, HEADERS, tagPhase, samplePayload } from "./config.js";

// Métricas customizadas
const anomalyErrors = new Rate("anomaly_error_rate");
const phaseLatency  = new Trend("phase_latency", true);
const totalRequests = new Counter("total_requests_count");
const readRequests  = new Counter("read_requests");
const writeRequests = new Counter("write_requests");
const heavyRequests = new Counter("heavy_requests");

// Duração de cada fase em segundos
const PHASE_DURATIONS = [
  { name: "baseline",     start: 0,   end: 150,  desc: "Normal read-heavy" },
  { name: "shift_cpu",    start: 150, end: 300,  desc: "Shift para CPU-heavy" },
  { name: "recovery_1",   start: 300, end: 420,  desc: "Recuperação ao normal" },
  { name: "shift_write",  start: 420, end: 570,  desc: "Shift para write-heavy" },
  { name: "recovery_2",   start: 570, end: 660,  desc: "Recuperação breve" },
  { name: "shift_mixed",  start: 660, end: 810,  desc: "Shift para mixed caótico" },
  { name: "cooldown",     start: 810, end: 930,  desc: "Cool-down final" },
];

export const options = {
  // VUs relativamente constantes — a anomalia está no MIX, não no volume
  stages: [
    { duration: "30s", target: 30 },   // warm-up
    { duration: "2m",  target: 50 },   // baseline normal (Fase 1)
    
    { duration: "10s", target: 50 },   // transição (mantém VUs)
    { duration: "2m",  target: 55 },   // shift CPU (Fase 2) — leve aumento
    { duration: "20s", target: 50 },   // transição
    
    { duration: "2m",  target: 50 },   // recovery (Fase 3)
    
    { duration: "10s", target: 50 },   // transição
    { duration: "2m",  target: 60 },   // shift write (Fase 4) — leve aumento
    { duration: "20s", target: 50 },   // transição
    
    { duration: "1m",  target: 50 },   // recovery breve (Fase 5)
    
    { duration: "10s", target: 55 },   // transição
    { duration: "2m",  target: 55 },   // mixed caótico (Fase 6)
    { duration: "30s", target: 50 },   // transição
    
    { duration: "2m",  target: 0 },    // cool-down (Fase 7)
  ],

  thresholds: {
    ...DEFAULT_THRESHOLDS,
    phase_latency:  ["p(95)<4000"],
    read_requests:  ["count>0"],
    write_requests: ["count>0"],
    heavy_requests: ["count>0"],
  },
};

// Determina a fase atual baseado no tempo decorrido desde o início
// Usa um cálculo aproximado baseado na iteração e no __VU
function getPhaseByTime() {
  // Abordagem simplificada: usa uma variável de ambiente ou calcula
  // Em produção, seria melhor usar um SharedArray ou scenario executors
  const now = Date.now();
  
  // Fallback: determina pela iteração relativa do VU
  // Para uma abordagem mais precisa, use scenarios com exec functions
  const iter = __ITER || 0;
  
  // Cada iteração leva ~1-2s, então:
  // Fase 1: iters 0-75  (baseline ~2.5min)
  // Fase 2: iters 76-150 (shift_cpu ~2.5min)  
  // Fase 3: iters 151-210 (recovery ~2min)
  // Fase 4: iters 211-285 (shift_write ~2.5min)
  // Fase 5: iters 286-330 (recovery ~1.5min)
  // Fase 6: iters 331-405 (mixed ~2.5min)
  // Fase 7: iters 406+   (cooldown)
  
  if (iter < 75)  return "baseline";
  if (iter < 150) return "shift_cpu";
  if (iter < 210) return "recovery";
  if (iter < 285) return "shift_write";
  if (iter < 330) return "recovery";
  if (iter < 405) return "shift_mixed";
  return "cooldown";
}

// Define o mix de requisições para cada fase
function getEndpointMix(phase) {
  const roll = Math.random();
  
  switch (phase) {
    case "baseline":
    case "recovery":
    case "cooldown":
      // 90% light, 10% moderate — perfil "normal"
      if (roll < 0.9)  return { url: ENDPOINTS.light, type: "read" };
      return { url: ENDPOINTS.moderate, type: "read" };

    case "shift_cpu":
      // 20% light, 60% heavy (CPU-bound), 20% write
      if (roll < 0.2)  return { url: ENDPOINTS.light, type: "read" };
      if (roll < 0.8)  return { url: ENDPOINTS.heavy, type: "heavy" };
      return { url: ENDPOINTS.write, type: "write" };

    case "shift_write":
      // 10% light, 20% moderate, 70% write
      if (roll < 0.1)  return { url: ENDPOINTS.light, type: "read" };
      if (roll < 0.3)  return { url: ENDPOINTS.moderate, type: "read" };
      return { url: ENDPOINTS.write, type: "write" };

    case "shift_mixed":
      // 25% cada tipo — distribuição caótica
      if (roll < 0.25) return { url: ENDPOINTS.light, type: "read" };
      if (roll < 0.50) return { url: ENDPOINTS.moderate, type: "read" };
      if (roll < 0.75) return { url: ENDPOINTS.heavy, type: "heavy" };
      return { url: ENDPOINTS.write, type: "write" };

    default:
      return { url: ENDPOINTS.light, type: "read" };
  }
}

export default function () {
  const phase = getPhaseByTime();
  const endpoint = getEndpointMix(phase);

  group(`load_shifting_${phase}`, function () {
    let res;

    if (endpoint.type === "write") {
      res = http.post(endpoint.url, samplePayload(), {
        ...HEADERS,
        tags: { phase: phase, endpoint_type: endpoint.type },
      });
      writeRequests.add(1);
    } else {
      res = http.get(endpoint.url, {
        tags: { phase: phase, endpoint_type: endpoint.type },
      });
      if (endpoint.type === "heavy") {
        heavyRequests.add(1);
      } else {
        readRequests.add(1);
      }
    }

    phaseLatency.add(res.timings.duration);
    anomalyErrors.add(res.status >= 400);
    totalRequests.add(1);

    check(res, {
      "status < 500":       (r) => r.status < 500,
      "duration < 4s":      (r) => r.timings.duration < 4000,
      "response received":  (r) => r.body !== null,
    });

    // Sleep constante — anomalia não está no volume
    sleep(0.8 + Math.random() * 0.4);
  });
}

export function handleSummary(data) {
  const summary = {
    scenario: "load-shifting",
    timestamp: new Date().toISOString(),
    total_requests: data.metrics.total_requests_count?.values?.count || 0,
    read_requests:  data.metrics.read_requests?.values?.count || 0,
    write_requests: data.metrics.write_requests?.values?.count || 0,
    heavy_requests: data.metrics.heavy_requests?.values?.count || 0,
    error_rate:     data.metrics.anomaly_error_rate?.values?.rate || 0,
    latency_avg:    data.metrics.phase_latency?.values?.avg || 0,
    latency_p95:    data.metrics.phase_latency?.values?.["p(95)"] || 0,
    latency_p99:    data.metrics.phase_latency?.values?.["p(99)"] || 0,
  };

  const readPct  = ((summary.read_requests / summary.total_requests) * 100).toFixed(1);
  const writePct = ((summary.write_requests / summary.total_requests) * 100).toFixed(1);
  const heavyPct = ((summary.heavy_requests / summary.total_requests) * 100).toFixed(1);

  return {
    "results/shifting-summary.json": JSON.stringify(summary, null, 2),
    stdout: `\n=== LOAD SHIFTING SUMMARY ===\n` +
            `Total requests: ${summary.total_requests}\n` +
            `  Read:  ${summary.read_requests} (${readPct}%)\n` +
            `  Write: ${summary.write_requests} (${writePct}%)\n` +
            `  Heavy: ${summary.heavy_requests} (${heavyPct}%)\n` +
            `Error rate: ${(summary.error_rate * 100).toFixed(2)}%\n` +
            `Latency avg: ${summary.latency_avg.toFixed(0)}ms\n` +
            `Latency p95: ${summary.latency_p95.toFixed(0)}ms\n` +
            `Latency p99: ${summary.latency_p99.toFixed(0)}ms\n`,
  };
}
