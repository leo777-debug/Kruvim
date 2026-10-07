"""Prometheus metrics exposed at /metrics."""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter("kruvim_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("kruvim_http_request_seconds", "HTTP latency", ["method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
SIMULATIONS = Counter("kruvim_simulations_total", "Simulations finished", ["status"])
SIM_ACTIONS = Counter("kruvim_sim_actions_total", "Agent actions executed", ["platform", "action"])
LLM_CALLS = Counter("kruvim_llm_calls_total", "LLM calls", ["provider", "role", "outcome"])
LLM_TOKENS = Counter("kruvim_llm_tokens_total", "LLM tokens", ["provider", "kind"])
JOBS_RUNNING = Gauge("kruvim_jobs_running", "Background jobs currently running", ["kind"])
CONNECTOR_RUNS = Counter("kruvim_datapool_runs_total", "Data pool connector runs", ["connector", "outcome"])


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
