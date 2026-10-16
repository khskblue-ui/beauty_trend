"""Model work done by Claude in a work session instead of an API (backend: session).

The pipeline code does not call a model. Each model step writes a request file;
the session's Claude (or its subagents) answers it; the next run of the same
command picks the answer up, validates it against the same JSON schema the API
used, and goes on. Code checks (verbatim quotes, no digits, entity names,
date-in-quote) are unchanged, so an answer that invents a quote is still dropped.

Files live under DATA_DIR/private/llm_exchange/ (never committed: prompts carry
article text):
  <id>.req.json  {id, role, created, system, prompt, schema}
  <id>.res.json  {id, answered_by, answered, data}

Roles and independence:
  enrich, write  answered by the session or worker subagents
  verify         answered ONLY by an agent whose name starts with "verifier",
                 and no "verifier" agent may answer enrich/write requests.
                 The verifier is a fresh subagent that sees only verify requests,
                 so the sentences it judges were written by someone else.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from . import store
from .util import utcnow_iso

log = logging.getLogger(__name__)
VERIFIER_PREFIX = "verifier"
_lock = threading.Lock()
_pending: set[str] = set()


class Pending(RuntimeError):
    """The answer for a request is not in yet (raised as an LLMError subclass by llm.py)."""


def root() -> Path:
    return store.data_dir() / "private" / "llm_exchange"


def request_id(role: str, system: str | None, prompt: str, schema: dict) -> str:
    h = hashlib.sha1()
    for part in (role, system or "", prompt, json.dumps(schema, sort_keys=True, ensure_ascii=False)):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:20]


def role_ok(role: str, answered_by: str) -> bool:
    is_verifier = answered_by.lower().startswith(VERIFIER_PREFIX)
    return is_verifier if role == "verify" else not is_verifier


def ask(role: str, prompt: str, schema: dict, system: str | None) -> tuple[dict | list | None, str]:
    """Return (answer data, answered_by) if answered; else record the request and return (None, "")."""
    rid = request_id(role, system, prompt, schema)
    d = root()
    res = d / f"{rid}.res.json"
    if res.exists():
        r = store.read_json(res, {}) or {}
        by = r.get("answered_by") or ""
        if role_ok(role, by):
            return r.get("data"), by
        log.warning("answer %s by %r rejected for role %s (independence rule)", rid, by, role)
        res.rename(res.with_suffix(".rejected.json"))
    req = d / f"{rid}.req.json"
    if not req.exists():
        store._write_json(req, {"id": rid, "role": role, "created": utcnow_iso(),
                                "system": system, "prompt": prompt, "schema": schema})
    with _lock:
        _pending.add(rid)
    return None, ""


def reject(rid: str, reason: str) -> None:
    """An answer failed schema validation: move it aside so the request is pending again."""
    res = root() / f"{rid}.res.json"
    if res.exists():
        res.rename(res.with_suffix(f".invalid.json"))
        log.warning("answer %s invalid: %s", rid, reason)
    with _lock:
        _pending.add(rid)


def pending_ids() -> set[str]:
    with _lock:
        return set(_pending)


def reset() -> None:
    with _lock:
        _pending.clear()


# ---- session side: list, export to a worker, import its answers ----------------

def open_requests(role: str | None = None) -> list[dict]:
    d = root()
    out = []
    for p in sorted(d.glob("*.req.json")) if d.exists() else []:
        if (d / p.name.replace(".req.", ".res.")).exists():
            continue
        r = store.read_json(p, {}) or {}
        if role is None or r.get("role") == role:
            out.append(r)
    return out


def export(role: str, out: Path, limit: int | None = None) -> int:
    """Bundle open requests of one role for a worker. Shared system prompts and schemas
    are written once, so a batch of 40 articles does not repeat 40 copies of the rules."""
    reqs = open_requests(role)[:limit]
    systems: dict[str, str] = {}
    schemas: dict[str, dict] = {}
    items = []
    for r in reqs:
        sk = hashlib.sha1((r.get("system") or "").encode()).hexdigest()[:8]
        ck = hashlib.sha1(json.dumps(r["schema"], sort_keys=True).encode()).hexdigest()[:8]
        systems[sk] = r.get("system") or ""
        schemas[ck] = r["schema"]
        items.append({"id": r["id"], "system": sk, "schema": ck, "prompt": r["prompt"]})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "role": role,
        "how_to_answer": ("For each item, follow systems[item.system] and answer item.prompt with ONE JSON "
                          "value that matches schemas[item.schema]. Write a JSON list "
                          "[{\"id\": item.id, \"data\": <answer>}] to the answers file. Copy quotes "
                          "character for character from the prompt text; never invent them."),
        "systems": systems, "schemas": schemas, "items": items}, ensure_ascii=False, indent=1), "utf-8")
    return len(items)


def import_answers(path: Path, answered_by: str) -> dict:
    """Store a worker's answers; each is checked against its request's schema and the role rule."""
    from .llm import validate
    d = root()
    answers = json.loads(Path(path).read_text("utf-8"))
    ok, bad = 0, []
    for a in answers:
        req = store.read_json(d / f"{a.get('id')}.req.json")
        if not req:
            bad.append({"id": a.get("id"), "error": "no such request"})
            continue
        if not role_ok(req["role"], answered_by):
            bad.append({"id": a["id"], "error": f"{answered_by} may not answer role {req['role']}"})
            continue
        errs = validate(a.get("data"), req["schema"])
        if errs:
            bad.append({"id": a["id"], "error": errs[:3]})
            continue
        store._write_json(d / f"{a['id']}.res.json", {"id": a["id"], "answered_by": answered_by,
                                                       "answered": utcnow_iso(), "data": a["data"]})
        ok += 1
    return {"imported": ok, "rejected": bad}
