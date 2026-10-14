"""Small stdlib-only HTTP helpers shared by the phase-0 probes.

No API keys live here. Proxies/CA bundles are taken from the environment
(HTTPS_PROXY, SSL_CERT_FILE) by urllib itself.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

UA = "beauty-trend-probe/0.1 (+phase0 source audit; low-volume)"
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


@dataclass
class Resp:
    url: str
    status: int | None
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    error: str | None = None
    elapsed: float = 0.0
    attempts: int = 1

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body)


def request(url: str, method: str = "GET", headers: dict | None = None,
            data: bytes | None = None, timeout: int = 20, retries: int = 2) -> Resp:
    """One HTTP request; connection-level failures are retried with backoff."""
    for attempt in range(retries + 1):
        r = _request_once(url, method, headers, data, timeout)
        if r.status is not None or attempt == retries:
            r.attempts = attempt + 1
            return r
        time.sleep(2 * 2 ** attempt)
    return r


def _request_once(url, method, headers, data, timeout) -> Resp:
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.geturl(), r.status, dict(r.headers), r.read(),
                        elapsed=time.time() - t0)
    except urllib.error.HTTPError as e:
        return Resp(url, e.code, dict(e.headers or {}), e.read() or b"",
                    error=f"HTTPError {e.code}", elapsed=time.time() - t0)
    except Exception as e:  # noqa: BLE001 - probe wants every failure recorded
        return Resp(url, None, error=f"{type(e).__name__}: {e}",
                    elapsed=time.time() - t0)


def save(name: str, obj) -> str:
    path = os.path.join(OUT_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    return path
