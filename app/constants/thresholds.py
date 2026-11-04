"""Health thresholds shared by live status, golden-signal tables, RCA rules and remediation verification.

Change a value here, not in the module that uses it, so the whole system agrees on what "unhealthy" means.
"""

from typing import Final

# A 5xx error rate at or above this (percent) counts as a fault.
ERROR_RATE_FAULT_PCT: Final = 3.0
# A 5xx error rate at or above this (percent) is critical.
ERROR_RATE_CRITICAL_PCT: Final = 5.0
# A p95 latency at or above this (milliseconds) counts as a fault.
LATENCY_FAULT_MS: Final = 1000.0
# A p95 latency at or above this (milliseconds) is a warning in tables.
LATENCY_WARN_MS: Final = 500.0
CPU_WARN_PCT: Final = 60.0
CPU_CRITICAL_PCT: Final = 80.0
# Sustained CPU at or above this raises an anomaly alert (separate from the RCA's critical level).
CPU_ALERT_PCT: Final = 85.0
MEMORY_CRITICAL_PCT: Final = 85.0
