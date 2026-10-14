"""HTTP client: stdlib urllib, retries with backoff, per-host pacing, robots.txt.

Proxies and CA bundles come from the environment (HTTPS_PROXY, SSL_CERT_FILE).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

BOT_UA = "beauty-trend-bot/0.1 (+monthly industry digest; low volume)"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Response:
    url: str
    status: int | None
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body)


class Client:
    def __init__(self, min_interval: float = 1.0, timeout: int = 30,
                 retries: int = 2, ua: str = BROWSER_UA):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.ua = ua
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _pace(self, host: str) -> None:
        with self._lock:
            wait = self._last.get(host, 0) + self.min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.time()

    def request(self, url: str, method: str = "GET", headers: dict | None = None,
                data: bytes | None = None, timeout: int | None = None,
                retries: int | None = None) -> Response:
        host = urllib.parse.urlsplit(url).netloc
        h = {"User-Agent": self.ua, "Accept": "*/*"}
        h.update(headers or {})
        retries = self.retries if retries is None else retries
        resp = Response(url, None)
        for attempt in range(retries + 1):
            self._pace(host)
            resp = self._once(url, method, h, data, timeout or self.timeout)
            if resp.status is not None and resp.status not in RETRY_STATUS:
                return resp
            if attempt < retries:
                delay = 2 * 2 ** attempt
                log.info("retry %s in %ss (%s)", url, delay, resp.error or resp.status)
                time.sleep(delay)
        return resp

    @staticmethod
    def _once(url, method, headers, data, timeout) -> Response:
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Response(r.geturl(), r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return Response(url, e.code, dict(e.headers or {}), e.read() or b"",
                            error=f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001 - every failure is recorded, not raised
            return Response(url, None, error=f"{type(e).__name__}: {e}")

    def allowed(self, url: str) -> bool:
        """robots.txt check for '*' and our UA. Unreachable robots → disallow."""
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            r = self.request(base + "/robots.txt", retries=1)
            if r.status == 200 and "<html" not in r.text[:500].lower():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                self._robots[base] = rp
            elif r.status in (404, 410):
                self._robots[base] = None  # no robots file → allowed
            else:
                self._robots[base] = False  # type: ignore[assignment]
        rp = self._robots[base]
        if rp is None:
            return True
        if rp is False:
            return False
        return rp.can_fetch("*", url) and rp.can_fetch(BOT_UA, url)
