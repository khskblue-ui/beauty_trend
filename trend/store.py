"""File layout under DATA_DIR (default ./data, a separate `data` branch in CI).

raw/<YYYY-MM-DD>/<source>.jsonl     collected docs (no full body when public)
private/body/<doc_id>.txt           article bodies (never committed while public)
enriched/<YYYY-MM>/<doc_id>.json    LLM-extracted fields + evidence spans
state/<name>.json                   collector state (page-diff link sets, etc.)
health/<YYYY-MM-DD>.json            per-source success/failure counts
reports/<YYYY-MM>/                  report run artifacts (prompts, logs, outputs)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), "utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(rel: str | Path, obj) -> Path:
    p = data_dir() / rel
    _write_json(p, obj)
    return p


def append_docs(day: str, source: str, docs: Iterable[dict]) -> int:
    """Append docs to raw/<day>/<source>.jsonl, skipping ids already in that file."""
    path = data_dir() / "raw" / day / f"{source}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {d["doc_id"] for d in iter_jsonl(path)}
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for d in docs:
            if d["doc_id"] in seen:
                continue
            seen.add(d["doc_id"])
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    return n


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_raw(days: Iterable[str] | None = None) -> Iterator[dict]:
    root = data_dir() / "raw"
    if not root.exists():
        return
    wanted = set(days) if days is not None else None
    for day_dir in sorted(root.iterdir()):
        if wanted is not None and day_dir.name not in wanted:
            continue
        for f in sorted(day_dir.glob("*.jsonl")):
            yield from iter_jsonl(f)


def known_ids() -> set[str]:
    return {d["doc_id"] for d in iter_raw()}


def save_body(doc_id: str, text: str) -> None:
    p = data_dir() / "private" / "body" / f"{doc_id}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


def load_body(doc_id: str) -> str | None:
    p = data_dir() / "private" / "body" / f"{doc_id}.txt"
    return p.read_text("utf-8") if p.exists() else None
