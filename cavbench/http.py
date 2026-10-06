"""Stdlib HTTP client with retries, exponential backoff, and Retry-After support."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class HTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def post_json(
    url: str,
    payload: dict,
    headers: dict,
    timeout: float = 120.0,
    max_retries: int = 6,
    base_delay: float = 2.0,
    max_delay: float = 90.0,
    sleep=time.sleep,
) -> tuple[dict, dict]:
    """POST JSON; return (response_json, meta). Retries on 429/5xx/network errors."""
    data = json.dumps(payload).encode()
    attempt = 0
    while True:
        attempt += 1
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("content-type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode()
                return json.loads(body), {"attempts": attempt, "latency_s": round(time.time() - t0, 3), "status": resp.status}
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code not in RETRYABLE or attempt > max_retries:
                raise HTTPError(e.code, body) from e
            retry_after = e.headers.get("retry-after") if e.headers else None
            delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt > max_retries:
                raise
            delay = None
        if delay is None:
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
        sleep(delay)
