"""Probe Gemini API: list models, then one short JSON-mode generation.

Auth: if GEMINI_API_KEY is set, it is sent as x-goog-api-key; otherwise no
key is sent (e.g. a proxy injects it).

Usage: python scripts/probe/gemini_probe.py [model_id]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _http import request, save  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"


def auth_headers() -> dict:
    key = os.getenv("GEMINI_API_KEY")
    return {"x-goog-api-key": key} if key else {}


def list_models() -> list[dict]:
    models, token = [], None
    while True:
        url = f"{BASE}/models?pageSize=100" + (f"&pageToken={token}" if token else "")
        r = request(url, headers=auth_headers())
        if r.status != 200:
            print("list models failed:", r.status, r.text[:300])
            return models
        d = r.json()
        models += d.get("models", [])
        token = d.get("nextPageToken")
        if not token:
            return models


def generate_json(model: str) -> dict:
    body = {
        "contents": [{"parts": [{"text":
            "다음 문장에서 브랜드와 향 노트를 추출하라: "
            "'딥티크가 무화과와 시더우드 노트의 신규 오 드 퍼퓸을 출시했다.'"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "properties": {
                "brand": {"type": "STRING"},
                "notes": {"type": "ARRAY", "items": {"type": "STRING"}}},
                "required": ["brand", "notes"]},
        },
    }
    r = request(f"{BASE}/models/{model}:generateContent", "POST",
                {**auth_headers(), "Content-Type": "application/json"},
                json.dumps(body).encode(), timeout=60)
    out = {"model": model, "status": r.status, "error": r.error}
    try:
        d = r.json()
        out["text"] = d["candidates"][0]["content"]["parts"][0]["text"]
        out["parsed"] = json.loads(out["text"])
        out["usage"] = d.get("usageMetadata")
        out["modelVersion"] = d.get("modelVersion")
    except Exception as e:  # noqa: BLE001
        out["body_head"] = r.text[:500]
        out["parse_error"] = str(e)
    return out


def main():
    models = list_models()
    gen = [m for m in models
           if "generateContent" in m.get("supportedGenerationMethods", [])]
    rows = [{"name": m["name"], "displayName": m.get("displayName"),
             "inputTokenLimit": m.get("inputTokenLimit"),
             "outputTokenLimit": m.get("outputTokenLimit")} for m in gen]
    for row in rows:
        print(row["name"], "|", row["displayName"])
    model = sys.argv[1] if len(sys.argv) > 1 else None
    result = generate_json(model) if model else None
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    save("gemini_probe.json", {"generate_content_models": rows, "json_test": result})


if __name__ == "__main__":
    main()
