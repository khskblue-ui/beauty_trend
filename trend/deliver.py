"""deliver: SMTP mail. Until a recipient is confirmed, everything goes to the maintainer.

Env: SMTP_HOST, SMTP_PORT (465 SSL / 587 STARTTLS), SMTP_USER, SMTP_PASSWORD,
MAIL_FROM, MAINTAINER_EMAIL, RECIPIENT_EMAIL (optional; unset = maintainer only).
Missing SMTP settings → skip with a log line (artifacts are still uploaded).
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


def configured() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAINTAINER_EMAIL"))


def _send(to: list[str], subject: str, body: str, attachments: list[Path]) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    for p in attachments:
        if p and Path(p).exists():
            sub = "pdf" if str(p).endswith(".pdf") else "html"
            msg.add_attachment(Path(p).read_bytes(), maintype="application" if sub == "pdf" else "text",
                               subtype=sub, filename=Path(p).name)
    port = int(os.getenv("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, context=ctx, timeout=60) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)


def send(status: str, ym: str, paths: dict, summary: list, gate: dict) -> None:
    if not configured():
        log.warning("SMTP not configured; skipping mail (status=%s)", status)
        return
    maint = os.environ["MAINTAINER_EMAIL"]
    recipient = os.getenv("RECIPIENT_EMAIL")
    body = Path(paths["mail"]).read_text("utf-8")
    if status == "dry_run":
        _send([maint], f"[드라이런] {ym} 리포트", body, [paths.get("pdf"), paths.get("html")])
    elif status == "publish":
        to = [recipient] if recipient else [maint]
        _send(to, f"[월간 뷰티와 향료 트렌드] {ym}", body, [paths.get("pdf")])
    elif status == "hold":
        _send([maint], f"[경보] {ym} 리포트 발행 보류", body, [paths.get("pdf"), paths.get("html")])
        if recipient:
            _send([recipient], f"[월간 뷰티와 향료 트렌드] {ym} 발행 지연 안내",
                  "이번 달 리포트는 데이터 품질 확인으로 발행이 지연되고 있습니다. "
                  "확인 후 다시 보내드리겠습니다. (자동 발송)", [])
