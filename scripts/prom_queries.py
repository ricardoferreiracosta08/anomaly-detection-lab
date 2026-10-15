"""
prom_queries.py — Consultas PromQL compartilhadas
PPGCC/UFMA — Ricardo F. Costa — 2026

Uma única fonte para as 4 features dos detectores. Usada por:
  - export_metrics.py   (range query → CSV offline, Fase 1)
  - online_detector.py  (instant query a cada 5 s, Fase 2)
Assim o detector online vê exatamente as mesmas métricas que o offline.
"""
import os

NAMESPACE = os.environ.get("NAMESPACE", "anomaly-lab")
RATE_WINDOW = os.environ.get("RATE_WINDOW", "30s")

FEATURES = ["latency_p95", "cpu_percent", "memory_mb", "request_rate"]


def queries(ns: str = NAMESPACE, w: str = RATE_WINDOW) -> dict:
    return {
        "latency_p95": (
            f'histogram_quantile(0.95, '
            f'sum(rate(http_request_duration_seconds_bucket{{namespace="{ns}"}}[{w}])) by (le))'
        ),
        "cpu_percent": (
            f'sum(rate(container_cpu_usage_seconds_total'
            f'{{namespace="{ns}", container="fastapi"}}[{w}])) * 100'
        ),
        "memory_mb": (
            f'sum(container_memory_usage_bytes'
            f'{{namespace="{ns}", container="fastapi"}}) / 1024 / 1024'
        ),
        "request_rate": (
            f'sum(rate(http_requests_total{{namespace="{ns}"}}[{w}]))'
        ),
        "error_rate": (
            f'sum(rate(http_requests_total{{namespace="{ns}", status=~"5.."}}[{w}]))'
            f' / clamp_min(sum(rate(http_requests_total{{namespace="{ns}"}}[{w}])), 0.001)'
        ),
    }


def online_alert_query(detector: str, ns: str = NAMESPACE) -> str:
    """Alerta (0/1) publicado pelo online_detector para um detector."""
    return f'max(anomaly_alert{{namespace="{ns}", detector="{detector}"}})'
