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


class Citations:
    """Assigns footnote numbers to documents in order of first citation."""

    def __init__(self, by_id: dict, extra: dict | None = None):
        self.by_id = dict(by_id)
        self.order: list[str] = []
        if extra:
            self.by_id.update(extra)

    def __call__(self, doc_ids) -> Markup:
        nums = []
        for d in doc_ids if isinstance(doc_ids, (list, tuple)) else [doc_ids]:
            if d not in self.order:
                self.order.append(d)
            nums.append(self.order.index(d) + 1)
        return Markup("".join(f'<sup class="cite"><a href="#src-{n}">[{n}]</a></sup>'
                              for n in sorted(set(nums))))

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
    for ci, t in enumerate(terms):
        c = colors[ci % len(colors)]
        xy = [(x(i), y(v)) for i, (_, v) in enumerate(pts[t]) if v is not None]
        if len(xy) > 1:
            d = " ".join(f"{'M' if j == 0 else 'L'}{a:.1f},{b:.1f}" for j, (a, b) in enumerate(xy))
            parts.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2"/>')
        for a, b in xy:
            parts.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.5" fill="{c}"/>')
        if xy:
            parts.append(f'<text x="{xy[-1][0] + 8:.1f}" y="{xy[-1][1] + 4:.1f}" class="label" '
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


def render_all(ctx: dict, out_dir: Path, pdf: bool = True) -> dict[str, Path]:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    cites = Citations(ctx["by_id"])
    env.globals.update(cite=cites, line_chart=line_chart, bar_chart=bar_chart)
    html_doc = env.get_template("report.html.j2").render(**ctx, cites=cites)
    # Source list is rendered last but must include all citations → second pass.
    html_doc = html_doc.replace("<!--SOURCES-->", env.get_template("_sources.html.j2").render(
        sources=cites.entries(ctx["links"])))
    paths = {"html": out_dir / f"report_{ctx['month']}.html"}
    paths["html"].write_text(html_doc, "utf-8")
    mail = env.get_template("mail.txt.j2").render(**ctx)
    paths["mail"] = out_dir / "mail.txt"
    paths["mail"].write_text(mail, "utf-8")
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
