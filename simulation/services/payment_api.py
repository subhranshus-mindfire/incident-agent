import logging
import os
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI, Response, status

# Prometheus metrics setup
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulation.payment_api")

app = FastAPI(title="Payment API (Simulation Microservice)", version="2.3.1")


def _burn_cpu_while_active() -> None:
    """Keeps roughly 80% of one core busy while the CPU-burn fault is active, so CPU metrics move."""
    while True:
        if chaos_state.cpu_burn_active:
            busy_until = time.perf_counter() + 0.04
            while time.perf_counter() < busy_until:
                pass
            time.sleep(0.01)
        else:
            time.sleep(0.1)



# Prometheus Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by payment-api",
    ["service", "method", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["service", "method"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
DB_POOL_ACTIVE_CONNECTIONS = Gauge(
    "db_pool_active_connections",
    "Active connections acquired in the database pool",
    ["service"],
)
DB_POOL_MAX_CONNECTIONS = Gauge(
    "db_pool_max_connections",
    "Maximum allowable connections in database pool",
    ["service"],
)

DB_POOL_MAX_CONNECTIONS.labels(service="payment-api").set(50)
DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(4)

LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")


# Chaos state management
class ChaosState:
    deadlock_active: bool = False
    bad_deployment_active: bool = False
    cpu_burn_active: bool = False
    current_version: str = "v2.3.1"
    active_connections: int = 4


chaos_state = ChaosState()

threading.Thread(target=_burn_cpu_while_active, name="cpu-burn", daemon=True).start()


async def push_log_to_loki(level: str, message: str) -> None:
    """Pushes structured log directly into live Grafana Loki."""
    ts_nano = str(int(time.time() * 1e9))
    payload = {
        "streams": [
            {
                "stream": {
                    "service": "payment-api",
                    "level": level.lower(),
                    "environment": "production",
                },
                "values": [[ts_nano, message]],
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{LOKI_URL}/loki/api/v1/push", json=payload)
    except Exception as exc:
        logger.debug(f"Could not push to Loki ({exc}); logged locally: {message}")


class PaymentRequest(BaseModel):
    amount: float = Field(..., gt=0.0)
    currency: str = "USD"
    account_id: str = "acc-45892"


@app.get("/health")
async def health_check() -> dict[str, Any]:
    healthy = not chaos_state.deadlock_active and not chaos_state.bad_deployment_active
    return {
        "status": "healthy" if healthy else "degraded",
        "service": "payment-api",
        "version": chaos_state.current_version,
        "active_chaos": {
            "deadlock": chaos_state.deadlock_active,
            "bad_deployment": chaos_state.bad_deployment_active,
            "cpu_burn": chaos_state.cpu_burn_active,
        },
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/deployments")
async def list_deployments() -> list[dict[str, Any]]:
    return [
        {
            "deployment_id": "DEP-101",
            "service": "payment-api",
            "version": chaos_state.current_version,
            "deployed_at": "2026-11-02T10:00:00Z",
            "status": "FAILED" if chaos_state.bad_deployment_active else "SUCCESS",
            "commit_sha": "c3f81e9",
        },
        {
            "deployment_id": "DEP-100",
            "service": "payment-api",
            "version": "v2.3.0",
            "deployed_at": "2026-11-01T18:00:00Z",
            "status": "SUCCESS",
            "commit_sha": "a1b2c3d",
        },
    ]


@app.post("/pay")
async def process_payment(payload: PaymentRequest) -> Response:
    start_time = time.time()

    # 1. Chaos Simulation: Database Deadlock / Connection Pool Exhaustion
    if chaos_state.deadlock_active:
        DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(50)
        HTTP_REQUESTS_TOTAL.labels(service="payment-api", method="POST", status="500").inc()
        msg = (
            "payment-api ERROR 500: Database connection timeout waiting for connection at 10:15 - "
            "Connection pool exhausted (max 50 connections reached)"
        )
        logger.error(msg)
        await push_log_to_loki("ERROR", msg)
        HTTP_REQUEST_DURATION_SECONDS.labels(service="payment-api", method="POST").observe(1.45)
        return Response(
            content='{"error": "Database connection timeout: pool exhausted"}',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json",
        )

    # 2. Chaos Simulation: Bad Deployment v2.3.1 Syntax/Connection Leak
    if chaos_state.bad_deployment_active:
        HTTP_REQUESTS_TOTAL.labels(service="payment-api", method="POST", status="500").inc()
        msg = f"payment-api ERROR 500: Fatal regression in {chaos_state.current_version} (DEP-101): syntax error in payments_ledger query"
        logger.error(msg)
        await push_log_to_loki("ERROR", msg)
        HTTP_REQUEST_DURATION_SECONDS.labels(service="payment-api", method="POST").observe(0.85)
        return Response(
            content='{"error": "Internal ledger query error"}',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json",
        )

    # Normal successful execution
    latency = 0.035
    if chaos_state.cpu_burn_active:
        latency = 0.450  # Elevated latency under CPU pressure

    DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(4)
    HTTP_REQUESTS_TOTAL.labels(service="payment-api", method="POST", status="200").inc()
    duration = time.time() - start_time + latency
    HTTP_REQUEST_DURATION_SECONDS.labels(service="payment-api", method="POST").observe(duration)

    return Response(
        content=f'{{"status": "processed", "amount": {payload.amount}, "version": "{chaos_state.current_version}"}}',
        status_code=status.HTTP_200_OK,
        media_type="application/json",
    )


# --- CHAOS INJECTION ENDPOINTS ---
@app.post("/chaos/db-deadlock")
async def trigger_deadlock() -> dict[str, str]:
    chaos_state.deadlock_active = True
    DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(50)
    await push_log_to_loki(
        "ERROR",
        "payment-api ERROR 500, Database connection timeout at 10:15; connection pool exhausted",
    )
    logger.warning("Chaos injected: Database Deadlock & Pool Exhaustion")
    return {"message": "Database deadlock and pool exhaustion injected on payment-api"}


@app.post("/chaos/bad-deployment")
async def trigger_bad_deployment() -> dict[str, str]:
    chaos_state.bad_deployment_active = True
    chaos_state.current_version = "v2.3.1"
    await push_log_to_loki(
        "ERROR",
        "payment-api ERROR 500: Regression introduced in DEP-101 (v2.3.1) - unhandled pool lock",
    )
    logger.warning("Chaos injected: Bad Deployment v2.3.1")
    return {"message": "Bad deployment v2.3.1 active on payment-api"}


@app.post("/chaos/cpu-burn")
async def trigger_cpu_burn() -> dict[str, str]:
    chaos_state.cpu_burn_active = True
    logger.warning("Chaos injected: CPU Burn")
    return {"message": "CPU burn simulation active on payment-api"}


@app.post("/chaos/clear")
async def clear_chaos() -> dict[str, str]:
    chaos_state.deadlock_active = False
    chaos_state.bad_deployment_active = False
    chaos_state.cpu_burn_active = False
    DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(4)
    logger.info("All chaos faults cleared. payment-api restored to normal health.")
    return {"message": "All chaos faults cleared. payment-api healthy."}


# --- REMEDIATION TARGET ENDPOINTS ---
@app.post("/remediation/rollback")
async def remediate_rollback() -> dict[str, str]:
    chaos_state.bad_deployment_active = False
    chaos_state.current_version = "v2.3.0"
    await push_log_to_loki("INFO", "payment-api successfully rolled back to v2.3.0 (stable)")
    logger.info("Remediation executed: Rolled back payment-api to v2.3.0")
    return {"status": "SUCCESS", "version": "v2.3.0", "message": "Rolled back to v2.3.0"}


@app.post("/remediation/kill-queries")
async def remediate_kill_queries() -> dict[str, str]:
    chaos_state.deadlock_active = False
    DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(4)
    await push_log_to_loki("INFO", "pg_terminate_backend: 3 blocking transactions terminated.")
    logger.info("Remediation executed: Terminated blocking database queries.")
    return {"status": "SUCCESS", "message": "Terminated blocking transactions. Pool cleared."}


@app.post("/remediation/restart")
async def remediate_restart() -> dict[str, str]:
    chaos_state.deadlock_active = False
    chaos_state.cpu_burn_active = False
    DB_POOL_ACTIVE_CONNECTIONS.labels(service="payment-api").set(4)
    logger.info("Remediation executed: Service restarted.")
    return {"status": "SUCCESS", "message": "Service restarted successfully."}
