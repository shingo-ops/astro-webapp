import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ("method", "handler", "status"),
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method", "handler", "status"),
)

IN_FLIGHT_REQUESTS = Gauge(
    "http_requests_in_flight",
    "Current in-flight HTTP requests handled by this backend process",
)

SSE_CONNECTIONS_ACTIVE = Gauge(
    "sse_connections_active",
    "Current active SSE connections",
    ("stream",),
)


def _handler_name(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def register_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        IN_FLIGHT_REQUESTS.inc()
        started = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - started
            labels = (request.method, _handler_name(request), status)
            REQUEST_COUNT.labels(*labels).inc()
            REQUEST_DURATION.labels(*labels).observe(elapsed)
            IN_FLIGHT_REQUESTS.dec()

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
