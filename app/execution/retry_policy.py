"""HTTP retry policy with exponential backoff.

Respects Retry-After on 429/418 (Binance rate-limit/ban codes) and retries
transient 5xx and network errors. Never retries 4xx client errors other than
the rate-limit codes — a rejected order must not be silently re-sent.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from app.core.exceptions import BrokerError
from app.core.logging import get_logger

log = get_logger(__name__)

RETRY_STATUSES = {418, 429, 500, 502, 503, 504}


def request_with_retries(
    call: Callable[[], httpx.Response],
    retries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = call()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            delay = min(base_delay * (2**attempt), max_delay)
            log.warning("network error (%s); retry %d/%d in %.1fs", exc, attempt + 1, retries, delay)
            time.sleep(delay)
            continue

        if response.status_code in RETRY_STATUSES and attempt < retries:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(base_delay * (2**attempt), max_delay)
            log.warning(
                "HTTP %d from %s; retry %d/%d in %.1fs",
                response.status_code, response.request.url.path, attempt + 1, retries, delay,
            )
            time.sleep(delay)
            continue
        return response

    raise BrokerError(f"request failed after {retries} retries: {last_error}")
