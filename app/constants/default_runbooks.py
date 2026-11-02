from datetime import UTC, datetime

from app.constants.enums import IncidentSeverity
from app.schemas.runbook import Runbook, RunbookSection

DEFAULT_PRODUCTION_RUNBOOKS: list[Runbook] = [
    Runbook(
        id="a1b2c3d4-e5f6-4a1b-8c2d-111111111111",
        title="High CPU Saturation and Latency Spike Remediation",
        description=(
            "Standard operating procedure for investigating and mitigating severe CPU saturation "
            "(>85%) causing p99 latency degradation, request timeouts, and thread pool starvation."
        ),
        service="generic",
        incident_types=["HIGH_CPU", "CPU_SPIKE", "LATENCY_SPIKE", "THREAD_STARVATION"],
        severity_levels=[IncidentSeverity.HIGH, IncidentSeverity.CRITICAL],
        prerequisites=[
            "Verify the service has autoscaling or spare cluster node capacity",
            "Ensure traffic is legitimate and not a DDoS attack requiring edge WAF filtering",
        ],
        diagnostic_steps=[
            "Execute PromQL query 'sum(rate(container_cpu_usage_seconds_total[5m])) by (container)' to identify saturated containers",
            "Inspect container throttling via 'container_cpu_cfs_throttled_periods_total'",
            "Check Loki logs for regular expressions indicating infinite loops, heavy regex processing, or cryptographic operations",
            "Collect a continuous profiling trace or thread dump if profiling agent is active",
        ],
        remediation_steps=[
            "Scale target deployment replicas up by 100% (e.g. kubectl scale deployment --replicas=N)",
            "Perform a progressive rolling restart of pods with highest CPU burn to shed leaked resources",
            "If CPU is caused by a poison pill query, throttle the offending API route or client tenant",
        ],
        rollback_steps=[
            "Scale deployment replicas back to baseline if CPU spike was traffic burst that subsided",
            "Roll back deployment if saturation was introduced by recent commit/image release",
        ],
        verification_steps=[
            "Verify container CPU usage falls below 65% across all running replicas",
            "Verify HTTP p99 request latency recovers to normal baseline (<200ms)",
            "Ensure zero pods are entering CrashLoopBackOff",
        ],
        sections=[
            RunbookSection(
                title="Kubernetes Scale & Restart Commands",
                content="Execute kubectl scaling and rollout restart commands safely in target namespace.",
                commands=[
                    "kubectl scale deployment/${SERVICE_NAME} -n prod --replicas=${NEW_REPLICAS}",
                    "kubectl rollout restart deployment/${SERVICE_NAME} -n prod",
                    "kubectl rollout status deployment/${SERVICE_NAME} -n prod --timeout=120s",
                ],
            )
        ],
        metadata={"category": "compute", "auto_remediable": True, "target_tier": "tier-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
    Runbook(
        id="a1b2c3d4-e5f6-4a1b-8c2d-222222222222",
        title="OOMKill and Memory Leak Remediation",
        description=(
            "Playbook to handle pods being terminated by Linux kernel OOM killer (Exit Code 137), "
            "steady linear heap climbs, and unbounded memory consumption."
        ),
        service="generic",
        incident_types=["OOM_KILL", "MEMORY_LEAK", "CONTAINER_CRASH", "POD_RESTART"],
        severity_levels=[IncidentSeverity.HIGH, IncidentSeverity.CRITICAL],
        prerequisites=[
            "Verify cluster worker nodes have available allocatable RAM",
            "Check pod memory limits defined in deployment manifest",
        ],
        diagnostic_steps=[
            "Verify termination exit code 137 in Kubernetes pod termination reasons via 'kubectl describe pod'",
            "Query PromQL 'container_memory_working_set_bytes' over the last 6 hours to differentiate gradual memory leak from instant spike",
            "Search Loki logs for 'java.lang.OutOfMemoryError', 'fatal error: runtime: out of memory', or heap dump generation",
        ],
        remediation_steps=[
            "Temporarily patch pod memory limit to 2x baseline to prevent immediate crash loops",
            "Restart the affected deployment to release leaked heap allocations and clear GC pressure",
            "If the leak correlates with recent code release, initiate immediate rollback to prior stable image tag",
        ],
        rollback_steps=[
            "Revert memory resource limit patches once permanent fix is deployed",
        ],
        verification_steps=[
            "Verify container memory working set remains steady without steep linear growth over 15 minutes",
            "Verify restart counter remains 0 for all pods over at least 5 minutes",
        ],
        sections=[
            RunbookSection(
                title="Memory Resource Patch",
                content="Apply Kubernetes resource limit patch to allow headroom while investigating root cause.",
                commands=[
                    "kubectl set resources deployment/${SERVICE_NAME} -n prod --limits=memory=2Gi --requests=memory=1Gi",
                    "kubectl rollout status deployment/${SERVICE_NAME} -n prod",
                ],
            )
        ],
        metadata={"category": "memory", "auto_remediable": True, "target_tier": "tier-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
    Runbook(
        id="a1b2c3d4-e5f6-4a1b-8c2d-333333333333",
        title="Database Connection Pool Exhaustion & Deadlock Triage",
        description=(
            "Investigation and resolution of database connection pool exhaustion, transaction lock contention, "
            "and query timeouts causing HTTP 500 error cascades."
        ),
        service="postgres",
        incident_types=[
            "DATABASE_DEADLOCK",
            "DB_POOL_EXHAUSTION",
            "QUERY_TIMEOUT",
            "DB_CONNECTION_LIMIT",
        ],
        severity_levels=[IncidentSeverity.CRITICAL],
        prerequisites=[
            "Verify access to primary database administrative credentials or connection pooler (PgBouncer)",
            "Do NOT terminate replication or backup worker processes",
        ],
        diagnostic_steps=[
            "Query pg_stat_activity to identify queries in 'idle in transaction' or executing > 30s",
            "Inspect pg_locks for lock trees and blocking queries",
            "Check application metrics for connection pool wait queue depth and checkout timeout rates",
            "Check Loki logs for 'remaining connection slots are reserved for non-replication superuser connections' or 'PoolTimeout'",
        ],
        remediation_steps=[
            "Terminate long-running blocking backend connections using 'SELECT pg_terminate_backend(pid)'",
            "Temporarily increase application pool size or PgBouncer client pool limits",
            "Trigger rolling restart of application instances holding stale disconnected sockets",
        ],
        rollback_steps=[
            "Restore standard connection pool limits once transaction backlog clears",
        ],
        verification_steps=[
            "Verify active database connection count drops below 75% of max_connections",
            "Verify application connection acquisition latency drops to < 10ms",
            "Verify HTTP 500 database-related error rates return to 0",
        ],
        sections=[
            RunbookSection(
                title="PostgreSQL Lock Clearance Query",
                content="Identify and terminate transactions blocking other clients for more than 60 seconds.",
                commands=[
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state in ('idle in transaction') AND state_change < now() - INTERVAL '60 seconds';",
                ],
            )
        ],
        metadata={"category": "database", "auto_remediable": True, "target_tier": "data-layer"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
    Runbook(
        id="a1b2c3d4-e5f6-4a1b-8c2d-444444444444",
        title="Upstream HTTP 5xx Error Rate Spike & Circuit Breaker Mitigation",
        description=(
            "Remediation procedures for high HTTP 5xx error rate spikes (>5%) caused by faulty upstream "
            "dependencies, network partitions, or bad canary releases."
        ),
        service="generic",
        incident_types=["HIGH_ERROR_RATE", "HTTP_5XX_SPIKE", "UPSTREAM_FAILURE", "CANARY_FAILURE"],
        severity_levels=[IncidentSeverity.HIGH, IncidentSeverity.CRITICAL],
        prerequisites=[
            "Verify current canary/deployment revision against previous known good release",
        ],
        diagnostic_steps=[
            "Query PromQL 'sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m])) * 100' to measure failure percentage",
            'Extract top error stack traces from Loki with \'{service="..."} |= "error"\' to identify failing upstream endpoint',
            "Verify whether error spike coincides with a recent deployment timestamp",
        ],
        remediation_steps=[
            "If errors correlate with recent deployment, trigger an immediate deployment rollback via 'kubectl rollout undo'",
            "Enable upstream circuit breaker or activate graceful fallback mode via feature flag toggle",
            "Route traffic away from failing availability zone or unhealthy upstream endpoint",
        ],
        rollback_steps=[
            "Re-enable upstream calls once upstream status page or health probe verifies restoration",
        ],
        verification_steps=[
            "Verify overall HTTP 5xx error rate drops below 0.1% for at least 3 minutes",
            "Verify consumer request throughput and success rate returns to nominal levels",
        ],
        sections=[
            RunbookSection(
                title="Rollback Deployment",
                content="Undo recent revision in Kubernetes.",
                commands=[
                    "kubectl rollout undo deployment/${SERVICE_NAME} -n prod",
                    "kubectl rollout status deployment/${SERVICE_NAME} -n prod",
                ],
            )
        ],
        metadata={"category": "network", "auto_remediable": True, "target_tier": "tier-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
    Runbook(
        id="a1b2c3d4-e5f6-4a1b-8c2d-555555555555",
        title="Redis Cache Eviction Storm & Cold Start Mitigation",
        description=(
            "Resolution steps for Redis cache memory saturation, elevated eviction rates, cache penetration, "
            "and stampedes overloading the primary persistent database."
        ),
        service="redis",
        incident_types=[
            "REDIS_CACHE_STORM",
            "CACHE_EVICTION",
            "MEMORY_SATURATION",
            "DB_LOAD_SPIKE",
        ],
        severity_levels=[IncidentSeverity.MEDIUM, IncidentSeverity.HIGH],
        prerequisites=[
            "Verify Redis maxmemory policy setting in redis.conf or INFO MEMORY",
        ],
        diagnostic_steps=[
            "Inspect Redis INFO stats for 'evicted_keys' and 'used_memory_percentage'",
            "Check for cache stampede (hot key expiration) hitting primary DB simultaneously",
            "Query Loki logs for 'OOM command not allowed when used memory > maxmemory' or timeout errors",
        ],
        remediation_steps=[
            "Temporarily increase Redis maxmemory limit if host memory permits",
            "Switch maxmemory-policy to 'volatile-lru' or 'allkeys-lru' to shed stale items without crashing",
            "Pre-warm top 100 hot cache keys to shield downstream database from stampede",
        ],
        rollback_steps=[
            "Revert maxmemory adjustments once traffic surge normalizes",
        ],
        verification_steps=[
            "Verify cache hit ratio returns to >85%",
            "Verify primary database read latency and connection load falls back to normal",
        ],
        sections=[
            RunbookSection(
                title="Redis Configuration Tuning",
                content="Adjust memory policy dynamically via Redis CLI.",
                commands=[
                    "redis-cli config set maxmemory-policy allkeys-lru",
                    "redis-cli info memory",
                ],
            )
        ],
        metadata={"category": "cache", "auto_remediable": True, "target_tier": "cache-tier"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
]
