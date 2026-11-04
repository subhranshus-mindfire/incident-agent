import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

logger = logging.getLogger("simulation.chaos_client")


def _urllib_call(
    method: str, url: str, data: dict[str, Any] | None = None, timeout: float = 5.0
) -> tuple[int, Any]:
    """Fallback HTTP caller using Python standard library (no dependencies required)."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Refusing non-HTTP URL: {url}")
    req = urllib.request.Request(url, method=method)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as response:
            status_code = response.getcode()
            raw = response.read().decode("utf-8")
            try:
                content = json.loads(raw)
            except Exception:
                content = raw
            return status_code, content
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            content = json.loads(raw)
        except Exception:
            content = {"error": raw}
        return err.code, content
    except Exception as exc:
        return 500, {"error": str(exc)}


class ChaosClient:
    """Client for controlling simulation faults, traffic generation, and verification.

    Works both with `httpx` (when installed in virtualenv/Docker) and standard library
    `urllib` (when run with bare system Python on host).
    """

    def __init__(self, base_url: str = "http://localhost:8080") -> None:
        self.base_url = base_url.rstrip("/")

    async def get_health(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}/health")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(_urllib_call, "GET", f"{self.base_url}/health")
        return data  # type: ignore[no-any-return]

    async def inject_deadlock(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(f"{self.base_url}/chaos/db-deadlock")
                logger.info("Injected DB deadlock on payment-api")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(
            _urllib_call, "POST", f"{self.base_url}/chaos/db-deadlock"
        )
        logger.info("Injected DB deadlock on payment-api")
        return data  # type: ignore[no-any-return]

    async def inject_bad_deployment(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(f"{self.base_url}/chaos/bad-deployment")
                logger.info("Injected bad deployment v2.3.1 on payment-api")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(
            _urllib_call, "POST", f"{self.base_url}/chaos/bad-deployment"
        )
        logger.info("Injected bad deployment v2.3.1 on payment-api")
        return data  # type: ignore[no-any-return]

    async def inject_cpu_burn(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(f"{self.base_url}/chaos/cpu-burn")
                logger.info("Injected CPU burn on payment-api")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(_urllib_call, "POST", f"{self.base_url}/chaos/cpu-burn")
        logger.info("Injected CPU burn on payment-api")
        return data  # type: ignore[no-any-return]

    async def clear_chaos(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(f"{self.base_url}/chaos/clear")
                logger.info("Cleared all chaos faults on payment-api")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(_urllib_call, "POST", f"{self.base_url}/chaos/clear")
        logger.info("Cleared all chaos faults on payment-api")
        return data  # type: ignore[no-any-return]

    async def generate_traffic(self, count: int = 10) -> list[int]:
        """Generates traffic through /pay to exercise metrics and logs."""
        status_codes: list[int] = []
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                for idx in range(count):
                    payload = {"amount": 25.50 + idx, "currency": "USD", "account_id": f"acc-{idx}"}
                    try:
                        res = await client.post(f"{self.base_url}/pay", json=payload)
                        status_codes.append(res.status_code)
                    except Exception as exc:
                        logger.warning(f"Request {idx} failed: {exc}")
                        status_codes.append(500)
            return status_codes

        for idx in range(count):
            payload = {"amount": 25.50 + idx, "currency": "USD", "account_id": f"acc-{idx}"}
            code, _ = await asyncio.to_thread(
                _urllib_call, "POST", f"{self.base_url}/pay", data=payload
            )
            status_codes.append(code)
        return status_codes

    async def rollback(self) -> dict[str, Any]:
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(f"{self.base_url}/remediation/rollback")
                return res.json()  # type: ignore[no-any-return]
        _, data = await asyncio.to_thread(
            _urllib_call, "POST", f"{self.base_url}/remediation/rollback"
        )
        return data  # type: ignore[no-any-return]
