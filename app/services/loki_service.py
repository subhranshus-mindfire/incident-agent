import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config.config import settings
from app.constants.patterns import (
    SERVICE_IDENTIFIER_PATTERN,
)
from app.exceptions.domain import ExternalServiceException
from app.schemas.telemetry import (
    LogEntry,
    LogQueryResult,
    LogStream,
)
from app.utils.http_client import get_shared_http_client

logger = logging.getLogger("incident_agent.loki_service")

# Strict identifier validation for LogQL label injection defense


def service_selector(service: str) -> str:
    """A LogQL stream selector for one service. The name is validated first, so it cannot change the query."""
    if not SERVICE_IDENTIFIER_PATTERN.match(service.strip()):
        raise ValueError(f"Invalid service identifier '{service}'.")
    return f'{{service="{service.strip()}"}}'


class LokiService:
    """Production client for querying Grafana Loki with log deduplication, redaction, and token budgeting."""

    # PII and Secret Redaction Patterns
    REDACTION_PATTERNS = [
        # Bearer tokens & JWTs
        (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
        (
            re.compile(r"\beyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\b"),
            "[REDACTED_JWT]",
        ),
        # AWS Access / Secret Keys
        (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
        # Passwords, Secrets, API keys in JSON/URL/Log formats
        (
            re.compile(
                r"""(?i)(["']?(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)["']?\s*[:=]\s*["']?)([^"' \s,;]{3,})(["']?)"""
            ),
            r"\1[REDACTED]\3",
        ),
        # Credit Card Numbers
        (
            re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
            "[REDACTED_CARD]",
        ),
    ]

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 8.0,
        max_retries: int = 3,
        max_line_length: int = 400,
    ) -> None:
        self.base_url = (base_url or settings.LOKI_URL).rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds, connect=4.0)
        self.max_retries = max_retries
        self.max_line_length = max_line_length
        self._custom_client = client

    def _get_client(self) -> httpx.AsyncClient:
        """Returns the shared connection pool client or custom test client."""
        if self._custom_client is not None and not self._custom_client.is_closed:
            return self._custom_client
        return get_shared_http_client()

    async def close(self) -> None:
        """Closes custom client if owned locally."""
        if self._custom_client is not None and not self._custom_client.is_closed:
            await self._custom_client.aclose()
            self._custom_client = None

    def _validate_service(self, service: str) -> str:
        """Validates and sanitizes service identifier to prevent LogQL label injection."""
        sanitized = service.strip()
        if not SERVICE_IDENTIFIER_PATTERN.match(sanitized):
            raise ValueError(
                f"Invalid service identifier '{sanitized}'. Only alphanumeric, hyphen, dot, and underscore characters are allowed."
            )
        return sanitized

    def redact_secrets(self, text: str) -> str:
        """Applies regex scrubbers to redact sensitive tokens, keys, and PII."""
        redacted = text
        for pattern, replacement in self.REDACTION_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def _truncate_line(self, line: str) -> str:
        """Truncates long log messages to fit within token budgets and avoid ReDoS."""
        if len(line) > self.max_line_length:
            return line[: self.max_line_length] + " ... [TRUNCATED]"
        return line

    def _detect_log_level(self, line: str) -> str:
        upper = line.upper()
        if "FATAL" in upper or "PANIC" in upper or "CRITICAL" in upper:
            return "FATAL"
        if "ERROR" in upper or "EXCEPTION" in upper or "TRACEBACK" in upper:
            return "ERROR"
        if "WARN" in upper:
            return "WARN"
        return "INFO"

    def deduplicate_logs(self, entries: list[LogEntry]) -> list[LogEntry]:
        """
        Deduplicates high-frequency recurring error logs into single entries with a count.
        Normalizes memory addresses, timestamps, and numbers for fingerprinting.
        """
        clustered: dict[str, LogEntry] = {}

        for entry in entries:
            # Create a signature by stripping numbers and hex addresses
            signature = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", entry.line)
            signature = re.sub(
                r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*", "TIMESTAMP", signature
            )
            signature = re.sub(r"\b\d+\b", "NUM", signature)
            # Grouping key only, not a security measure.
            fingerprint = hashlib.md5(signature.encode("utf-8"), usedforsecurity=False).hexdigest()

            if fingerprint in clustered:
                clustered[fingerprint].dedup_count += 1
                # Keep latest timestamp
                if entry.timestamp > clustered[fingerprint].timestamp:
                    clustered[fingerprint].timestamp = entry.timestamp
            else:
                clustered[fingerprint] = entry

        # Return sorted by latest timestamp descending
        return sorted(clustered.values(), key=lambda e: e.timestamp, reverse=True)

    async def _execute_with_retry(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._get_client()
        url = f"{self.base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.get(url, params=params, timeout=self.timeout)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        res_data = data.get("data", {})
                        return res_data if isinstance(res_data, dict) else {}
                    raise ExternalServiceException(
                        service_name="Grafana Loki",
                        message=f"Loki query error: {data.get('error', 'unknown')}",
                    )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                raise ExternalServiceException(
                    service_name="Grafana Loki",
                    message=f"HTTP {response.status_code}: {response.text[:200]}",
                )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 0.3 * (2 ** (attempt - 1))
                    logger.warning(
                        "Loki query '%s' failed (attempt %d/%d). Retrying in %.2fs: %s",
                        params.get("query"),
                        attempt,
                        self.max_retries,
                        backoff,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error("Loki query exhausted retries: %s", exc)

        raise ExternalServiceException(
            service_name="Grafana Loki",
            message=f"Failed to query Loki after {self.max_retries} attempts: {last_error}",
        )

    async def query_range(
        self,
        logql: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
        deduplicate: bool = True,
    ) -> LogQueryResult:
        """Executes a LogQL range query with automatic secret redaction and log deduplication."""
        params: dict[str, Any] = {
            "query": logql,
            "start": int(start.timestamp() * 1e9),  # Loki expects nanoseconds
            "end": int(end.timestamp() * 1e9),
            "limit": limit,
            "direction": "BACKWARD",
        }

        data = await self._execute_with_retry("/loki/api/v1/query_range", params)
        raw_streams = data.get("result", [])
        total_lines = 0
        streams: list[LogStream] = []

        for stream in raw_streams:
            stream_labels = stream.get("stream", {})
            values = stream.get("values", [])
            total_lines += len(values)
            entries: list[LogEntry] = []

            for val in values:
                try:
                    nano_ts = int(val[0])
                    ts = datetime.fromtimestamp(nano_ts / 1e9, tz=UTC)
                    raw_line = val[1]
                except (ValueError, IndexError):
                    continue

                # 1. Truncate FIRST to bound memory and prevent ReDoS on massive log payloads
                bounded_line = self._truncate_line(raw_line)

                # 2. Redact Secrets & PII on the bounded slice
                safe_line = self.redact_secrets(bounded_line)

                # 3. Detect Log Level
                level = self._detect_log_level(safe_line)

                entries.append(
                    LogEntry(
                        timestamp=ts,
                        line=safe_line,
                        level=level,
                        labels=stream_labels,
                    )
                )

            # 4. Deduplicate & cluster identical lines
            final_entries = self.deduplicate_logs(entries) if deduplicate else entries

            streams.append(
                LogStream(
                    labels=stream_labels,
                    entries=final_entries,
                )
            )

        returned_count = sum(len(s.entries) for s in streams)
        return LogQueryResult(
            query=logql,
            total_lines_scanned=total_lines,
            returned_lines=returned_count,
            streams=streams,
        )

    async def get_service_errors(
        self,
        service: str,
        window_minutes: int = 15,
        max_entries: int = 50,
    ) -> list[LogEntry]:
        """Fetches and deduplicates critical application error logs for a service."""
        safe_service = self._validate_service(service)
        end = datetime.now(UTC)
        start = datetime.fromtimestamp(end.timestamp() - (window_minutes * 60), tz=UTC)

        logql = (
            f'{{service="{safe_service}"}} |= "error" or |= "exception" or |= "fatal" or |= "panic"'
        )
        try:
            result = await self.query_range(
                logql=logql, start=start, end=end, limit=max_entries * 2
            )
            all_entries: list[LogEntry] = []
            for stream in result.streams:
                all_entries.extend(stream.entries)
            return self.deduplicate_logs(all_entries)[:max_entries]
        except Exception as ex:
            logger.debug("Loki log retrieval encountered an error or returned no logs: %s", ex)
            return []

    async def health_check(self) -> bool:
        """Returns True if the Loki server is reachable and ready."""
        try:
            client = self._get_client()
            res = await client.get(f"{self.base_url}/ready", timeout=3.0)
            return res.status_code == 200
        except httpx.HTTPError as exc:
            logger.debug("Loki health check failed: %s", exc)
            return False
