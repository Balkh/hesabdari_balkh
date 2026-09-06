import logging
import time

logger = logging.getLogger("core.requests")


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("%s %s %s %.2fms", request.method, request.path, response.status_code, elapsed_ms)
        return response
