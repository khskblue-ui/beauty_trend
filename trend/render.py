"""render: static HTML (print CSS) → PDF via Playwright, plus a plain mail summary."""
from __future__ import annotations

import html
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .config import ROOT

log = logging.getLogger(__name__)


SOURCE_KICKER = {"accord": "부록", "signal": "부록", "chromatogram": "부록"}


class Citations:
    """Assigns footnote numbers to documents in order of first citation."""

    def __init__(self, by_id: dict, extra: dict | None = None):
        self.by_id = dict(by_id)
        self.order: list[str] = []
        self.seen: dict[int, int] = {}   # citation number → how many times cited so far
        if extra:
            self.by_id.update(extra)

    def __call__(self, doc_ids) -> Markup:
        nums = []
        for d in doc_ids if isinstance(doc_ids, (list, tuple)) else [doc_ids]:
            if d not in self.order:
                self.order.append(d)
            nums.append(self.order.index(d) + 1)
        out = []
        for n in sorted(set(nums)):
            k = self.seen[n] = self.seen.get(n, 0) + 1
            # id lets the source list link back to where it was cited (first: cite-n-1)
            out.append(f'<sup class="cite"><a id="cite-{n}-{k}" href="#src-{n}">[{n}]</a></sup>')
        return Markup("".join(out))

    def entries(self, links: dict) -> list[dict]:
        out = []
        for i, d in enumerate(self.order, 1):
            r = self.by_id.get(d, {})
            out.append({"n": i, "title": r.get("title"), "url": r.get("url"),
                        "source": r.get("source_name"), "date": (r.get("published_at") or "")[:10],
                        "link": links.get(r.get("url"), "unchecked")})
        return out


def line_chart(series: dict, anchor: str, width: int = 640, height: int = 220) -> Markup:
    """Static SVG: each term's search index relative to the anchor term (anchor = 1.0)."""
    terms = [t for t in series if t != anchor]
    pts = {t: [(p["period"][:7], p["vs_anchor"]) for p in series[t]] for t in terms}
    vals = [v for t in terms for _, v in pts[t] if v is not None]
    if not vals:
        return Markup("")
    periods = [p for p, _ in pts[terms[0]]]
    vmax = max(vals) * 1.15 or 1
    pad_l, pad_b, pad_t, pad_r = 44, 28, 12, 120
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    x = lambda i: pad_l + (w * i / max(1, len(periods) - 1))
    y = lambda v: pad_t + h - h * v / vmax
    colors = ["#2a6f97", "#c0587e", "#e09f3e", "#4f772d"]
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="검색 지수 상대값 추이(기준: {html.escape(anchor)})">']
    for k in range(4):
        v = vmax * k / 3
        parts.append(f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v:.2f}</text>')
    for i, p in enumerate(periods):
        parts.append(f'<text x="{x(i):.1f}" y="{height - 8}" class="tick" text-anchor="middle">{p[2:]}</text>')
    # End labels: spread vertically so they never overlap (min 14px apart).
    ends = sorted(((y(pts[t][-1][1]) if pts[t][-1][1] is not None else pad_t + h, t)
                   for t in terms))
    label_y, last_y = {}, -1e9
    for yy, t in ends:
        yy = max(yy, last_y + 14)
        label_y[t], last_y = yy, yy
    for ci, t in enumerate(terms):
        c = colors[ci % len(colors)]
        xy = [(x(i), y(v)) for i, (_, v) in enumerate(pts[t]) if v is not None]
        if len(xy) > 1:
            d = " ".join(f"{'M' if j == 0 else 'L'}{a:.1f},{b:.1f}" for j, (a, b) in enumerate(xy))
            parts.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2"/>')
        for a, b in xy:
            parts.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.5" fill="{c}"/>')
        if xy:
            parts.append(f'<text x="{xy[-1][0] + 8:.1f}" y="{label_y[t] + 4:.1f}" class="label" '
                         f'fill="{c}">{html.escape(t)}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def bar_chart(rows: list[tuple[str, float]], width: int = 640, unit: str = "") -> Markup:
    if not rows:
        return Markup("")
    vmax = max(v for _, v in rows) or 1
    bh, gap, pad_l = 18, 6, 140
    height = len(rows) * (bh + gap) + 8
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for i, (label, v) in enumerate(rows):
        yy = 4 + i * (bh + gap)
        bw = (width - pad_l - 60) * v / vmax
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 13}" class="label" text-anchor="end">{html.escape(label)}</text>'
                     f'<rect x="{pad_l}" y="{yy}" width="{bw:.1f}" height="{bh}" rx="2" class="bar"/>'
                     f'<text x="{pad_l + bw + 6:.1f}" y="{yy + 13}" class="tick">{v:g}{unit}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def line_paths(series: dict, anchor: str | None, width: int, height: int,
               pad=(40, 16, 28, 110), gap: float = 15) -> dict:
    """SVG geometry for multi-line charts (vs-anchor ratios). pad = left, top, bottom, right."""
    terms = [t for t in series if t != anchor]
    if not terms:
        return {"lines": [], "ticks": [], "periods": []}
    pl, pt, pb, pr = pad
    w, h = width - pl - pr, height - pt - pb
    periods = [p for p, _ in series[terms[0]]]
    vals = [v for t in terms for _, v in series[t] if v is not None]
    vmax = (max(vals) if vals else 1) * 1.12 or 1
    X = lambda i: pl + w * i / max(1, len(periods) - 1)
    Y = lambda v: pt + h - h * v / vmax
    lines, last = [], -1e9
    for t in terms:
        pts = [(X(i), Y(v)) for i, (_, v) in enumerate(series[t]) if v is not None]
        d = " ".join(f"{'M' if j == 0 else 'L'}{a:.1f},{b:.1f}" for j, (a, b) in enumerate(pts))
        lines.append({"term": t, "d": d, "pts": pts, "end": pts[-1] if pts else (pl, pt + h),
                      "last": series[t][-1][1]})
    # End labels: keep ≥gap px apart (≈1.3× label font size); if they run past the plot bottom, shift up.
    order = sorted(lines, key=lambda x: x["end"][1])
    for ln in order:
        ly = max(ln["end"][1], last + gap)
        ln["label_y"], last = ly, ly
    bottom = pt + h
    for ln in reversed(order):
        if ln["label_y"] > bottom:
            ln["label_y"] = bottom
        bottom = ln["label_y"] - gap
    ticks = [{"y": Y(vmax * k / 3), "v": f"{vmax * k / 3:.2f}"} for k in range(4)]
    labels = [{"x": X(i), "p": p[2:]} for i, p in enumerate(periods)]
    return {"lines": lines, "ticks": ticks, "periods": labels, "x0": pl, "x1": pl + w,
            "y0": pt, "y1": pt + h, "width": width, "height": height}


def chromatogram(keywords: list[dict], width: int = 900, height: int = 260) -> dict:
    """Gaussian peaks along a 'retention' axis; peak height ∝ supporting event count."""
    if not keywords:
        return {"d": "", "peaks": [], "width": width, "height": height}
    base, top, left, right = height - 34, 64, 30, width - 30
    nmax = max(k["n"] for k in keywords) or 1
    span = right - left
    peaks = []
    for i, k in enumerate(keywords):
        cx = left + span * (i + 1) / (len(keywords) + 1)
        amp = (base - top) * (0.25 + 0.75 * k["n"] / nmax)
        peaks.append({"x": cx, "y": base - amp, "amp": amp, "term": k["term"], "n": k["n"],
                      "delay": round((cx - left) / span * 2.4, 2)})
    sigma = span / (len(keywords) + 1) / 6
    pts = []
    steps = 360
    import math
    for j in range(steps + 1):
        x = left + span * j / steps
        y = base - sum(p["amp"] * math.exp(-((x - p["x"]) ** 2) / (2 * sigma ** 2)) for p in peaks)
        y -= 2.2 * math.sin(j * 0.9) * 0.5  # detector noise, purely decorative
        pts.append(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}")
    return {"d": " ".join(pts), "peaks": peaks, "width": width, "height": height,
            "base": base, "left": left, "right": right}


def events(ctx: dict) -> list[dict]:
    """Dated items of the month for timeline views (all code-derived)."""
    agg = ctx["agg"]
    out = []
    for c in agg["market"]["kr"] + agg["market"]["global"]:
        out.append({"day": c["published"], "kind": "market", "title": c["title"], "doc_id": c["doc_id"]})
    for x in agg["launches"]:
        if len(x["launch_date"]) == 10:
            out.append({"day": x["launch_date"], "kind": "launch",
                        "title": f"{x['brand']} {x['name']}".strip(), "doc_id": x["doc_id"]})
    for c in agg["regulation"]["regulation"]:
        out.append({"day": c["published"], "kind": "regulation", "title": c["title"], "doc_id": c["doc_id"]})
    end = ctx["period"]["end"]
    return sorted((e for e in out if e["day"].startswith(agg["month"]) and e["day"] <= end),
                  key=lambda e: e["day"])


def viz_data(ctx: dict) -> dict:
    """Numbers for client-side charts. Everything here is computed in code."""
    agg = ctx["agg"]
    kws = [{"term": k["term"], "n": k["n_clusters"]} for k in ctx["keywords"]]
    search = agg.get("datalab", {}).get("search")
    shop = agg.get("datalab", {}).get("shopping")
    return {
        "month": agg["month"],
        "keywords": kws,
        "notes": [{"note": n, "count": c} for n, c in agg["notes"]["note_freq"]],
        "notes_n": agg["notes"]["n"],
        "search": ({"anchor": search["anchor"],
                    "series": {t: [[p["period"][:7], p["vs_anchor"]] for p in pts]
                               for t, pts in search["series"].items()}} if search else None),
        "shopping": [[p["period"][:7], p["ratio"]] for p in shop["series"]] if shop else [],
        "events": events(ctx),
        "counts": agg["counts"],
        "days": int(ctx["period"]["end"][8:]),
        "kinds": {k: sum(e["kind"] == k for e in events(ctx))
                  for k in ("market", "launch", "regulation")},
        "calendar": [_horizon(c, ctx["generated"][:10]) for c in agg.get("calendar", [])],
    }


def eul(word: str) -> str:
    """Quoted word + object particle by its final consonant: 화장품 → '화장품'을, 뷰티 → '뷰티'를."""
    last = word[-1] if word else ""
    has_final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return f"'{word}'{'을' if has_final else '를'}"


def with_period(ctx: dict) -> dict:
    """Fill display fields of the analysis window (runs saved before 2026-10-15 lack it)."""
    from .util import month_bounds
    first, last = month_bounds(ctx["month"])
    p = dict(ctx.get("period") or {"start": first.isoformat(), "end": last.isoformat(),
                                   "interim": False})
    end_day = int(p["end"][8:])
    p["span"] = f"{first.month}월 {first.day}~{end_day}일" if p["interim"] else f"{first.month}월"
    p["tag"] = f"{ctx['month']} 중간" if p["interim"] else ctx["month"]
    ctx["period"] = p
    return ctx


def _horizon(c: dict, today: str) -> dict:
    from datetime import date
    out = dict(c)
    if c.get("start"):
        s, e, t = (date.fromisoformat(x) for x in (c["start"], c["date"], today))
        total = (e - s).days or 1
        out["elapsed"] = round(min(1, max(0, (t - s).days / total)), 3)
        out["days_left"] = (e - t).days
    return out


def render_all(ctx: dict, out_dir: Path, pdf: bool = True) -> dict[str, Path]:
    ctx = with_period(dict(ctx))
    env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    cites = Citations(ctx["by_id"])
    from .aggregate import launch_groups
    env.filters["eul"] = eul
    env.globals.update(cite=cites, line_chart=line_chart, bar_chart=bar_chart,
                       line_paths=line_paths, chromatogram=chromatogram, launch_groups=launch_groups)
    html_doc = env.get_template("report.html.j2").render(**ctx, cites=cites)
    # Source list is rendered last but must include all citations → second pass.
    html_doc = html_doc.replace("<!--SOURCES-->", env.get_template("_sources.html.j2").render(
        sources=cites.entries(ctx["links"])))
    paths = {"html": out_dir / f"report_{ctx['month']}.html"}
    paths["html"].write_text(html_doc, "utf-8")
    mail = env.get_template("mail.txt.j2").render(**ctx)
    paths["mail"] = out_dir / "mail.txt"
    paths["mail"].write_text(mail, "utf-8")
    variants = ctx["cfg"].get("motion_variants", [])
    if os.getenv("MOTION_VARIANTS"):  # e.g. "accord" to render one variant while testing
        variants = [v for v in os.getenv("MOTION_VARIANTS").split(",") if v]
    # each variant as a slide deck, plus (motion_doc) the same sections as a scrolling document
    jobs = [(v, False) for v in variants] + [(v, True) for v in variants if ctx["cfg"].get("motion_doc")]
    for v, doc_mode in jobs:
        mc = Citations(ctx["by_id"])
        env.globals.update(cite=mc)
        doc = env.get_template(f"motion/{v}.html.j2").render(
            **ctx, cites=mc, events=events(ctx), viz=viz_data(ctx), doc_mode=doc_mode)
        # sources come last so every citation number is already assigned
        doc = doc.replace("<!--SOURCE_SLIDES-->", env.get_template("motion/_sources_slides.j2").render(
            sources=mc.entries(ctx["links"]), month=ctx["period"]["tag"], title=ctx["cfg"]["title"],
            kicker=SOURCE_KICKER.get(v, "")))
        key = f"motion_{v}_doc" if doc_mode else f"motion_{v}"
        paths[key] = out_dir / f"report_{ctx['month']}_{v}{'_doc' if doc_mode else ''}.html"
        paths[key].write_text(doc, "utf-8")
    env.globals.update(cite=cites)
    if pdf:
        try:
            paths["pdf"] = to_pdf(paths["html"], out_dir / f"report_{ctx['month']}.pdf")
        except Exception as e:  # noqa: BLE001 - PDF failure must not lose the HTML
            log.error("PDF render failed: %s", e)
    return paths


def to_pdf(html_path: Path, pdf_path: Path) -> Path:
    from playwright.sync_api import sync_playwright
    exe = os.getenv("PLAYWRIGHT_CHROMIUM_PATH")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.emulate_media(media="print")
        page.pdf(path=str(pdf_path), format="A4", print_background=True,
                 margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
                 display_header_footer=True, header_template="<span></span>",
                 footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
                                 '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        browser.close()
    return pdf_path
