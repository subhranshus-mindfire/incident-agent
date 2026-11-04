"""Shared observability clients.

Built once per process so their HTTP connection pools are reused. Tools and routes take these
through this module instead of constructing a client on every call.
"""

from functools import lru_cache

from app.services.loki_service import LokiService
from app.services.prometheus_service import PrometheusService


@lru_cache
def get_prometheus_service() -> PrometheusService:
    return PrometheusService()


@lru_cache
def get_loki_service() -> LokiService:
    return LokiService()
