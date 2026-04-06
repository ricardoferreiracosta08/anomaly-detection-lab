// config.js — Configurações para cenários de carga anômala
// Target: FastAPI no K3D via port-forward (localhost:8080)

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

export const ENDPOINTS = {
  health:   `${BASE_URL}/health`,
  light:    `${BASE_URL}/api/v1/items`,
  moderate: `${BASE_URL}/api/v1/items/search?q=workload`,
  heavy:    `${BASE_URL}/api/v1/items/report`,
  write:    `${BASE_URL}/api/v1/items`,
};

export const DEFAULT_THRESHOLDS = {
  http_req_duration: ["p(95)<2000"],
  http_req_failed:   ["rate<0.30"],
};

export function tagPhase(phase) {
  return { tags: { phase } };
}

export function samplePayload() {
  return JSON.stringify({
    name: `item-${Date.now()}`,
    value: Math.random() * 1000,
    category: ["compute", "memory", "network", "storage"][Math.floor(Math.random() * 4)],
  });
}

export const HEADERS = {
  headers: { "Content-Type": "application/json" },
};
