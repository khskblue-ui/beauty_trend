"""Shared helpers: dates (KST), ids, text cleanup."""
from __future__ import annotations

import email.utils
import hashlib
import html
import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
_MONTHS = ("January February March April May June July August September "
           "October November December").split()


def now_kst() -> datetime:
    return datetime.now(KST)


def clean_text(s: str | None) -> str:
    """Strip tags/entities and collapse whitespace."""
    s = TAG_RE.sub(" ", html.unescape(s or ""))
    return WS_RE.sub(" ", html.unescape(s)).strip()


def parse_date(s: str | None, naive_tz: str = "UTC") -> datetime | None:
    """Parse the date formats seen in phase 0 into an aware datetime.

    RFC 822 ('Wed, 14 Oct 2026 21:14:24 +0900'), ISO 8601, 'YYYY-MM-DD HH:MM:SS'
    without zone (naive_tz applied), '21 September 2026', 'October 13, 2026'.
    """
    if not s:
        return None
    s = s.strip()
    tz = ZoneInfo(naive_tz)
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d is not None:
            return d if d.tzinfo else d.replace(tzinfo=tz)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=tz)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M",
                "%Y.%m.%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def to_kst_iso(d: datetime | None) -> str | None:
    return d.astimezone(KST).isoformat(timespec="seconds") if d else None


def kst_date(iso: str | None) -> date | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso).astimezone(KST).date()


def month_bounds(ym: str) -> tuple[date, date]:
    """'2026-09' → (2026-09-01, 2026-09-30)."""
    y, m = map(int, ym.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def prev_month(ym: str) -> str:
    first, _ = month_bounds(ym)
    p = first - timedelta(days=1)
    return f"{p.year:04d}-{p.month:02d}"


def canonical_url(url: str) -> str:
    """Drop fragments and tracking params so the same article maps to one id."""
    p = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path,
                                    urllib.parse.urlencode(q), ""))


def url_key(url: str) -> str:
    """Scheme- and www-insensitive form of a URL. A feed may link http:// while the
    site's archive links https:// (cosinkorea): doc_id differs, url_key does not."""
    c = canonical_url(url)
    c = c.split("://", 1)[-1]
    return (c[4:] if c.startswith("www.") else c).rstrip("/")


def doc_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
