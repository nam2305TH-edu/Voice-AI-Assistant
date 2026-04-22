import time
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Histogram

REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency",
    ["method", "path"]
)

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        REQUEST_LATENCY.labels(
            request.method,
            request.url.path
        ).observe(duration)

        return response
