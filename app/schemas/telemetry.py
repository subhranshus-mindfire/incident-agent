from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.constants.live import MIN_REQUESTS_FOR_RATE


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    metric_name: str = Field(default="", description="Name of the metric")
    labels: dict[str, str] = Field(default_factory=dict, description="Metric label key-value pairs")
    points: list[MetricPoint] = Field(default_factory=list, description="Time-series data points")


class MetricQueryResult(BaseModel):
    query: str
    result_type: str = Field(description="vector, matrix, or scalar")
    series: list[MetricSeries] = Field(default_factory=list)
    status: str = "success"


class GoldenSignalMetrics(BaseModel):
    service: str
    error_rate_5xx_percent: float = Field(ge=0.0, le=100.0, description="HTTP 5xx error percentage")
    request_rate_per_sec: float = Field(ge=0.0, description="Total throughput in requests/second")
    p95_latency_ms: float = Field(
        ge=0.0, description="95th percentile request latency in milliseconds"
    )
    cpu_usage_percent: float = Field(ge=0.0, description="CPU utilization percentage")
    memory_usage_percent: float = Field(ge=0.0, description="Memory utilization percentage")
    missing_signals: list[str] = Field(
        default_factory=list,
        description="Signals with no data in the window. Their values are placeholders, not measurements.",
    )
    window_seconds: float | None = Field(
        default=None, description="Length of the window the rates were computed over"
    )
    collected_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rates_measured(self) -> bool:
        """True when the window had enough requests for the error rate and latency to mean something."""
        if "request_rate_per_sec" in self.missing_signals or self.request_rate_per_sec <= 0:
            return False
        if self.window_seconds is None:
            return True
        return self.request_rate_per_sec * self.window_seconds >= MIN_REQUESTS_FOR_RATE


class AnomalyAlert(BaseModel):
    metric_name: str
    current_value: float
    baseline_value: float
    threshold_value: float
    is_breached: bool
    severity: str = Field(description="critical, warning, or info")
    message: str


class LogEntry(BaseModel):
    timestamp: datetime
    line: str
    level: str = Field(default="INFO", description="Log level (INFO, WARN, ERROR, FATAL)")
    labels: dict[str, str] = Field(default_factory=dict)
    dedup_count: int = Field(default=1, ge=1, description="Number of duplicate lines aggregated")


class LogStream(BaseModel):
    labels: dict[str, str]
    entries: list[LogEntry]


class LogQueryResult(BaseModel):
    query: str
    total_lines_scanned: int
    returned_lines: int
    streams: list[LogStream]
    status: str = "success"


class TelemetryReport(BaseModel):
    service: str
    window_minutes: int
    signals: GoldenSignalMetrics
    anomalies: list[AnomalyAlert]
    error_logs: list[LogEntry]
    generated_at: datetime
