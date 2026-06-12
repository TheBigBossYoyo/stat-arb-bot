"""Binance request signing (HMAC-SHA256).

RSA / Ed25519 key types are also accepted by Binance; HMAC is implemented
first as it is what standard API keys use. See
https://developers.binance.com/docs/binance-spot-api-docs/rest-api/endpoint-security-type
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode


def sign_query(params: dict, secret: str) -> str:
    """Return the hex HMAC-SHA256 signature of the urlencoded query string."""
    query = urlencode(params, doseq=True)
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_params(params: dict, secret: str, recv_window_ms: int = 5000) -> dict:
    """Attach timestamp, recvWindow and signature to request params."""
    out = dict(params)
    out["timestamp"] = int(time.time() * 1000)
    out["recvWindow"] = recv_window_ms
    out["signature"] = sign_query(out, secret)
    return out
