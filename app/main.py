"""
FastAPI Application for Anomaly Detection Experiments
PPGCC/UFMA — Ricardo F. Costa — 2026

Endpoints with different load profiles for load-shifting experiments:
  /health         → health check (no load)
  /api/v1/items   → GET: light read (~1ms)
  /api/v1/items   → POST: write with validation (~5ms)
  /api/v1/items/search → GET: moderate query (~10ms)
  /api/v1/items/report → GET: CPU-heavy computation (~50-200ms)
  /metrics        → Prometheus metrics (auto)
"""

import os
import time
import math
import random
import hashlib
from typing import Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "endpoint"]
)
ITEMS_TOTAL = Gauge("app_items_total", "Total items in store")

# ---------------------------------------------------------------------------
# Middleware: instrument every request automatically
# ---------------------------------------------------------------------------
class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        # Skip /metrics and /health from instrumentation
        if path in ("/metrics", "/health"):
            return await call_next(request)

        # Normalize path to avoid cardinality explosion
        endpoint = path.rstrip("/")

        IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            elapsed = time.perf_counter() - start
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(elapsed)
            IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()

        return response

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="K8s Anomaly Detection Lab", version="2.0.0")
app.add_middleware(PrometheusMiddleware)

# In-memory store
items_store: dict = {}
_counter = 0

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ItemCreate(BaseModel):
    name: str
    value: float
    category: str = "general"

class ItemResponse(BaseModel):
    id: str
    name: str
    value: float
    category: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Health check — no load."""
    return {"status": "healthy", "hostname": os.getenv("HOSTNAME", "unknown")}


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/items", response_model=list[ItemResponse])
def list_items(limit: int = Query(default=20, le=100)):
    """Light read — returns items from memory. ~1ms."""
    result = list(items_store.values())[:limit]
    ITEMS_TOTAL.set(len(items_store))
    return result


@app.post("/api/v1/items", response_model=ItemResponse, status_code=201)
def create_item(item: ItemCreate):
    """Write with validation — ~5ms."""
    global _counter
    _counter += 1
    item_id = f"item-{_counter:06d}"

    # Simulate validation overhead
    _ = hashlib.sha256(item.name.encode()).hexdigest()

    record = {"id": item_id, "name": item.name, "value": item.value, "category": item.category}
    items_store[item_id] = record
    ITEMS_TOTAL.set(len(items_store))
    return record


@app.get("/api/v1/items/search")
def search_items(
    q: str = Query(default="item", min_length=1),
    category: str = Query(default=""),
):
    """Moderate load — filtering and sorting. ~10ms."""
    results = list(items_store.values())

    # Filter
    if q:
        results = [i for i in results if q.lower() in i["name"].lower()]
    if category:
        results = [i for i in results if i["category"] == category]

    # Sort (adds CPU work)
    results.sort(key=lambda x: x["value"], reverse=True)

    # Simulate additional processing
    time.sleep(0.005 + random.random() * 0.005)

    return {"count": len(results), "results": results[:50]}


@app.get("/api/v1/items/report")
def generate_report():
    """CPU-heavy computation — ~50-200ms.
    
    Simulates a real analytics/report endpoint by doing:
    - Aggregations over items
    - Statistical calculations
    - Hash computations (CPU-bound)
    """
    n_iterations = int(os.getenv("REPORT_COMPLEXITY", "5000"))

    # CPU-bound work: hash chain
    data = b"anomaly-detection-experiment"
    for i in range(n_iterations):
        data = hashlib.sha256(data).digest()

    # Statistical computations over items
    values = [i["value"] for i in items_store.values()] or [0.0]
    n = len(values)
    mean_val = sum(values) / n
    variance = sum((v - mean_val) ** 2 for v in values) / n
    std_val = math.sqrt(variance) if variance > 0 else 0

    # Category aggregation
    categories: dict = {}
    for item in items_store.values():
        cat = item["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "total_value": 0.0}
        categories[cat]["count"] += 1
        categories[cat]["total_value"] += item["value"]

    return {
        "total_items": n,
        "mean_value": round(mean_val, 2),
        "std_value": round(std_val, 2),
        "categories": categories,
        "hash_iterations": n_iterations,
        "hostname": os.getenv("HOSTNAME", "unknown"),
    }


# ---------------------------------------------------------------------------
# Startup: seed some initial data
# ---------------------------------------------------------------------------
@app.on_event("startup")
def seed_data():
    """Seed initial items for search/report endpoints to have data."""
    global _counter
    cats = ["compute", "memory", "network", "storage", "general"]
    for i in range(100):
        _counter += 1
        item_id = f"item-{_counter:06d}"
        items_store[item_id] = {
            "id": item_id,
            "name": f"workload-{random.choice(cats)}-{i}",
            "value": round(random.uniform(1, 1000), 2),
            "category": random.choice(cats),
        }
    ITEMS_TOTAL.set(len(items_store))
