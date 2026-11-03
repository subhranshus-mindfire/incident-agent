from app.schemas.service import ServiceDependencyMap

SERVICE_DEPENDENCIES: dict[str, ServiceDependencyMap] = {
    "payment-api": ServiceDependencyMap(
        service="payment-api",
        upstream_services=["order-service", "checkout-web"],
        downstream_services=["postgres", "auth-service", "redis"],
        tier="tier-1",
        criticality="critical",
    ),
    "order-service": ServiceDependencyMap(
        service="order-service",
        upstream_services=["api-gateway", "mobile-app"],
        downstream_services=["payment-api", "postgres", "inventory-service"],
        tier="tier-1",
        criticality="critical",
    ),
    "auth-service": ServiceDependencyMap(
        service="auth-service",
        upstream_services=["api-gateway", "payment-api", "order-service"],
        downstream_services=["postgres", "redis"],
        tier="tier-0",
        criticality="mission-critical",
    ),
    "postgres": ServiceDependencyMap(
        service="postgres",
        upstream_services=["payment-api", "order-service", "auth-service"],
        downstream_services=[],
        tier="infrastructure",
        criticality="mission-critical",
    ),
    "redis": ServiceDependencyMap(
        service="redis",
        upstream_services=["payment-api", "auth-service"],
        downstream_services=[],
        tier="infrastructure",
        criticality="high",
    ),
}
