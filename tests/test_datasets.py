import csv
import json

from app.seed.datasets import SAMPLE_DIR, load_historical_incidents


def test_historical_incidents_load_from_the_sample_file() -> None:
    incidents = load_historical_incidents()
    assert len(incidents) >= 4
    assert all(inc.root_cause and inc.remediation for inc in incidents)


def test_sample_logs_and_deployments_match_the_spec_examples() -> None:
    logs = json.loads((SAMPLE_DIR / "application_logs.json").read_text(encoding="utf-8"))
    assert any("Database connection timeout" in row["message"] for row in logs)
    assert any("Connection pool exhausted" in row["message"] for row in logs)
    deployments = json.loads((SAMPLE_DIR / "deployments.json").read_text(encoding="utf-8"))
    assert any(d["deployment_id"] == "DEP-101" and d["version"] == "v2.3.1" for d in deployments)


def test_sample_metrics_csv_has_the_expected_columns() -> None:
    with (SAMPLE_DIR / "system_metrics.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and set(rows[0]) == {
        "timestamp",
        "service",
        "error_rate",
        "latency_ms",
        "cpu_pct",
        "memory_pct",
    }


def test_sample_dependencies_cover_the_three_services() -> None:
    deps = json.loads((SAMPLE_DIR / "service_dependencies.json").read_text(encoding="utf-8"))
    assert {"payment-api", "order-service", "auth-service"} <= set(deps)
