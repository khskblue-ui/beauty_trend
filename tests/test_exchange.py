"""Session backend: model work through request/answer files, with the verifier rule."""
import json

import pytest

from trend import exchange
from trend.llm import PendingLLM, generate_json

SCHEMA = {"type": "OBJECT", "properties": {"x": {"type": "STRING"}}, "required": ["x"]}


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    exchange.reset()
    return tmp_path


def _answer(tmp_path, role, data, by):
    reqs = exchange.open_requests(role)
    f = tmp_path / "answers.json"
    f.write_text(json.dumps([{"id": r["id"], "data": data} for r in reqs]), "utf-8")
    return exchange.import_answers(f, by)


def test_request_is_written_then_answer_is_used(data_dir):
    cfg = {"backend": "session", "role": "write"}
    with pytest.raises(PendingLLM):
        generate_json(cfg, "prompt", SCHEMA, "system")
    assert len(exchange.open_requests("write")) == 1 and exchange.pending_ids()
    assert _answer(data_dir, "write", {"x": "ok"}, "writer-1")["imported"] == 1
    call = generate_json(cfg, "prompt", SCHEMA, "system")
    assert call.data == {"x": "ok"} and call.model == "claude-session:writer-1"
    assert exchange.open_requests() == []


def test_invalid_answers_are_refused(data_dir):
    with pytest.raises(PendingLLM):
        generate_json({"backend": "session", "role": "enrich"}, "p", SCHEMA, None)
    out = _answer(data_dir, "enrich", {"y": 1}, "worker-1")
    assert out["imported"] == 0 and "missing" in str(out["rejected"])


def test_verify_requests_only_from_an_independent_verifier(data_dir):
    cfg = {"backend": "session", "role": "verify"}
    with pytest.raises(PendingLLM):
        generate_json(cfg, "claim", SCHEMA, None)
    assert _answer(data_dir, "verify", {"x": "s"}, "writer-1")["imported"] == 0      # the writer may not judge
    assert _answer(data_dir, "verify", {"x": "s"}, "verifier-1")["imported"] == 1
    assert generate_json(cfg, "claim", SCHEMA, None).data == {"x": "s"}
    with pytest.raises(PendingLLM):
        generate_json({"backend": "session", "role": "write"}, "other", SCHEMA, None)
    assert _answer(data_dir, "write", {"x": "w"}, "verifier-1")["imported"] == 0     # and the verifier may not write


def test_export_bundles_shared_rules_once(data_dir):
    for i in range(3):
        with pytest.raises(PendingLLM):
            generate_json({"backend": "session", "role": "enrich"}, f"article {i}", SCHEMA, "long rules")
    out = data_dir / "batch.json"
    assert exchange.export("enrich", out) == 3
    b = json.loads(out.read_text("utf-8"))
    assert len(b["systems"]) == 1 and len(b["items"]) == 3 and "never invent" in b["how_to_answer"]


def test_entailment_pending_is_not_a_verdict(data_dir):
    from trend.verify import entailment, verify_sentences
    assert entailment([("a", "b")], None) == ["pending"]
    kept, rows = verify_sentences([{"text": "가나다", "doc_ids": ["d"], "quote": "가나다"}], {"d"},
                                  {"d": {"title": "가나다", "extraction": {}}}, set(), None)
    assert kept == [] and rows[0]["reason"] == "entailment:pending"
