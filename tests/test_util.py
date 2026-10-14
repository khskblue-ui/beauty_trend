from datetime import date

from trend.util import canonical_url, doc_id, month_bounds, parse_date, prev_month, to_kst_iso


def test_parse_date_formats_seen_in_phase0():
    # RFC 822 with offset (뷰티경제, WWD)
    assert to_kst_iso(parse_date("Wed, 14 Oct 2026 21:14:24 +0900")) == "2026-10-14T21:14:24+09:00"
    # naive 'YYYY-MM-DD HH:MM:SS' (장업신문, 코스모닝) is KST when told so
    assert to_kst_iso(parse_date("2026-10-14 10:55:00", "Asia/Seoul")) == "2026-10-14T10:55:00+09:00"
    # ISO with Z (Premium Beauty News)
    assert to_kst_iso(parse_date("2026-10-14T06:27:08Z")) == "2026-10-14T15:27:08+09:00"
    # Givaudan / IFRA day-month-year
    assert parse_date("21 September 2026").date() == date(2026, 9, 21)
    assert parse_date("October 13, 2026").date() == date(2026, 10, 13)
    assert parse_date("garbage") is None and parse_date(None) is None


def test_utc_late_evening_lands_on_next_kst_day():
    assert to_kst_iso(parse_date("Wed, 30 Sep 2026 22:00:00 GMT")).startswith("2026-10-01")


def test_month_helpers():
    assert month_bounds("2026-09") == (date(2026, 9, 1), date(2026, 9, 30))
    assert month_bounds("2026-12")[1] == date(2026, 12, 31)
    assert prev_month("2026-01") == "2025-12"


def test_canonical_url_drops_tracking_and_fragment():
    a = "https://Example.com/a?id=1&utm_source=x#top"
    assert canonical_url(a) == "https://example.com/a?id=1"
    assert doc_id(a) == doc_id("https://example.com/a?id=1")
