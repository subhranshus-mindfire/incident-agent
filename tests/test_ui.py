import json
import urllib.error
from unittest.mock import MagicMock, patch

from ui.helpers import api_request, ping_endpoint


def test_ping_endpoint_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert ping_endpoint("http://localhost:8000/health") is True


def test_ping_endpoint_failure():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert ping_endpoint("http://localhost:9999/health") is False


def test_api_request_get_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        code, data = api_request("GET", "http://localhost:8000/health")
        assert code == 200
        assert data["status"] == "healthy"


def test_api_request_post_payload():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({"incident_id": "INC-123"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        code, data = api_request(
            "POST",
            "http://localhost:8000/api/v1/investigations/trigger",
            data={"service": "payment-api"},
        )
        assert code == 200
        assert data["incident_id"] == "INC-123"


def test_api_request_http_error_handled():
    mock_err = urllib.error.HTTPError(
        url="http://test",
        code=404,
        msg="Not Found",
        hdrs=MagicMock(),
        fp=MagicMock(read=lambda: json.dumps({"detail": "Incident not found"}).encode("utf-8")),
    )
    with patch("urllib.request.urlopen", side_effect=mock_err):
        code, data = api_request("GET", "http://localhost:8000/api/v1/investigations/nonexistent")
        assert code == 404
        assert data["detail"] == "Incident not found"
