"""Gemini REST client with JSON-schema output, validation, retries and a usage ledger.

Key: GEMINI_API_KEY (sent as x-goog-api-key) when set; otherwise none (proxy env).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

from .http import Client
from .util import utcnow_iso

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_client = Client(min_interval=0.2, timeout=180, retries=3)


class LLMError(RuntimeError):
    pass


@dataclass
class Call:
    model: str
    data: object
    usage: dict
    attempts: int


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if os.getenv("GEMINI_API_KEY"):
        h["x-goog-api-key"] = os.environ["GEMINI_API_KEY"]
    return h


def validate(obj, schema: dict, path: str = "$") -> list[str]:
    """Minimal validator for the Gemini responseSchema subset we use."""
    t = schema.get("type")
    errs: list[str] = []
    if obj is None:
        return [] if schema.get("nullable") else [f"{path}: null"]
    if t == "OBJECT":
        if not isinstance(obj, dict):
            return [f"{path}: not object"]
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{path}.{k}: missing")
        for k, sub in schema.get("properties", {}).items():
            if k in obj:
                errs += validate(obj[k], sub, f"{path}.{k}")
    elif t == "ARRAY":
        if not isinstance(obj, list):
            return [f"{path}: not array"]
        for i, x in enumerate(obj):
            errs += validate(x, schema["items"], f"{path}[{i}]")
    elif t == "STRING":
        if not isinstance(obj, str):
            errs.append(f"{path}: not string")
        elif "enum" in schema and obj not in schema["enum"]:
            errs.append(f"{path}: {obj!r} not in enum")
    elif t == "BOOLEAN" and not isinstance(obj, bool):
        errs.append(f"{path}: not boolean")
    elif t in ("INTEGER", "NUMBER") and not isinstance(obj, (int, float)):
        errs.append(f"{path}: not number")
    return errs


def generate_json(stage_cfg: dict, prompt: str, schema: dict, system: str | None = None,
                  ledger: str | None = None) -> Call:
    """Call stage model (fallback on 404/5xx exhaustion); retry on schema violations."""
    last = None
    for model in (stage_cfg["model"], stage_cfg.get("fallback")):
        if not model:
            continue
        for attempt in range(stage_cfg.get("max_retries", 2) + 1):
            try:
                call = _call(model, prompt, schema, system, stage_cfg.get("thinking_budget"))
            except LLMError as e:
                last = e
                if "HTTP 404" in str(e) or "HTTP 5" in str(e) or "HTTP 429" in str(e):
                    break  # try fallback model
                continue
            errs = validate(call.data, schema)
            _log(ledger, model, call.usage, ok=not errs, errors=errs[:5])
            if not errs:
                call.attempts = attempt + 1
                return call
            last = LLMError(f"schema: {errs[:3]}")
            log.warning("%s schema violation (attempt %d): %s", model, attempt + 1, errs[:3])
    raise LLMError(str(last))


def _call(model, prompt, schema, system, thinking_budget) -> Call:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": schema},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if thinking_budget is not None:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    r = _client.request(f"{BASE}/{model}:generateContent", "POST", _headers(),
                        json.dumps(body).encode())
    if not r.ok:
        raise LLMError(f"{model} HTTP {r.status}: {r.text[:300]}")
    d = r.json()
    try:
        parts = d["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        data = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMError(f"{model} bad response: {e}: {str(d)[:300]}") from e
    return Call(model, data, d.get("usageMetadata", {}), 1)


_ledger_lock = threading.Lock()


def _log(ledger, model, usage, **kw) -> None:
    if not ledger:
        return
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    with _ledger_lock, open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": utcnow_iso(), "model": model,
                            "in": usage.get("promptTokenCount", 0),
                            "out": usage.get("candidatesTokenCount", 0),
                            "think": usage.get("thoughtsTokenCount", 0), **kw},
                           ensure_ascii=False) + "\n")
