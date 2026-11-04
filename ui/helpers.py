import json
import os
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("incident_agent.ui.helpers")


def _require_http_url(url: str) -> str:
    """Only http and https URLs are allowed, so a configured value cannot open local files or other schemes."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Refusing non-HTTP URL: {url}")
    return url


def api_request(
    method: str, url: str, data: dict[str, Any] | None = None, timeout: float = 8.0
) -> tuple[int, Any]:
    """Universal HTTP requester with robust JSON and error handling."""
    req = urllib.request.Request(_require_http_url(url), method=method)
    req.add_header("User-Agent", "IncidentAgent-StreamlitUI/1.0")
    agent_key = os.getenv("AGENT_API_KEY")
    if agent_key and url.startswith(os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")):
        req.add_header("X-API-Key", agent_key)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as response:
            status_code = response.getcode()
            content = response.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return status_code, parsed
    except urllib.error.HTTPError as err:
        content = err.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"error": content}
        return err.code, parsed
    except Exception as exc:
        return 500, {"error": str(exc)}


def ping_endpoint(url: str, timeout: float = 2.0) -> bool:
    """Checks if a target URL responds with 2xx/3xx."""
    try:
        req = urllib.request.Request(_require_http_url(url), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.getcode() in (200, 204, 301, 302)
    except Exception:
        return False
