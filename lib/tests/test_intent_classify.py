"""Tests for intent_classify.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_intent_classify.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import intent_classify as ic  # noqa: E402


# ── embed_text: task-prefix convention ──────────────────────────────────────

def test_embed_text_uses_search_query_prefix_for_queries(monkeypatch):
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3]]}

    def fake_post(url, json, timeout):
        captured["input"] = json["input"]
        return _FakeResp()

    monkeypatch.setattr(ic.requests, "post", fake_post)
    ic.embed_text("fix the bug", task="query")
    assert captured["input"] == "search_query: fix the bug"


def test_embed_text_uses_search_document_prefix_for_documents(monkeypatch):
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3]]}

    def fake_post(url, json, timeout):
        captured["input"] = json["input"]
        return _FakeResp()

    monkeypatch.setattr(ic.requests, "post", fake_post)
    ic.embed_text("fix the date validator bug", task="document")
    assert captured["input"] == "search_document: fix the date validator bug"


def test_embed_text_returns_none_on_request_failure(monkeypatch):
    def fake_post(*a, **k):
        raise ConnectionError("ollama not running")

    monkeypatch.setattr(ic.requests, "post", fake_post)
    assert ic.embed_text("anything", task="query") is None


# ── classify: confident match, no-match, unavailable ────────────────────────

class _FakeCollection:
    def __init__(self, metadatas, distances):
        self._metadatas = metadatas
        self._distances = distances

    def query(self, query_embeddings, n_results, include):
        return {"metadatas": [self._metadatas], "distances": [self._distances]}


def test_classify_returns_best_matching_intent_when_confident(monkeypatch):
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query": [0.1, 0.2])
    monkeypatch.setattr(
        ic, "_get_collection",
        lambda: _FakeCollection(
            metadatas=[{"intent": "coding"}, {"intent": "research"}],
            distances=[0.1, 0.5],
        ),
    )
    result = ic.classify("fix the bug in utils.py")
    # ChromaDB cosine distance ranges 0-2 (0=identical, 2=opposite), not 0-1
    # -- score = 1 - dist/2, not 1 - dist. dist=0.1 -> score=0.95.
    assert result == {"status": "ok", "intent": "coding", "score": 0.95}


def test_classify_score_uses_correct_cosine_distance_conversion(monkeypatch):
    # dist=0 (identical) -> score=1.0; dist=2 (opposite) -> score=0.0.
    # 1.0 - dist would give -1.0 for the opposite case, which is not a valid
    # similarity score -- this locks in the correct 1 - dist/2 conversion.
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query": [0.1, 0.2])
    monkeypatch.setattr(
        ic, "_get_collection",
        lambda: _FakeCollection(metadatas=[{"intent": "coding"}], distances=[0.0]),
    )
    assert ic.classify("x")["score"] == 1.0


def test_classify_returns_no_match_when_below_threshold(monkeypatch):
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query": [0.1, 0.2])
    monkeypatch.setattr(
        ic, "_get_collection",
        lambda: _FakeCollection(
            metadatas=[{"intent": "coding"}, {"intent": "research"}],
            distances=[0.9, 0.95],
        ),
    )
    result = ic.classify("something ambiguous")
    assert result["status"] == "no_match"
    assert result["intent"] is None


def test_classify_returns_unavailable_when_embedding_fails(monkeypatch):
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query": None)
    result = ic.classify("fix the bug in utils.py")
    assert result == {"status": "unavailable", "intent": None, "score": None}


def test_classify_returns_unavailable_when_chromadb_query_raises(monkeypatch):
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query": [0.1, 0.2])

    def raise_query():
        raise RuntimeError("chromadb not reachable")

    monkeypatch.setattr(ic, "_get_collection", raise_query)
    result = ic.classify("fix the bug in utils.py")
    assert result == {"status": "unavailable", "intent": None, "score": None}


def test_classify_embeds_the_description_as_a_query_not_a_document(monkeypatch):
    seen_tasks = []
    monkeypatch.setattr(
        ic, "embed_text",
        lambda text, task="query": seen_tasks.append(task) or [0.1, 0.2],
    )
    monkeypatch.setattr(
        ic, "_get_collection",
        lambda: _FakeCollection(metadatas=[{"intent": "coding"}], distances=[0.1]),
    )
    ic.classify("fix the bug")
    assert seen_tasks == ["query"]


# ── build_collection: cosine space + full reference-set coverage ───────────

def test_build_collection_creates_with_cosine_hnsw_space(monkeypatch):
    captured = {}

    class _FakeClient:
        def get_or_create_collection(self, name, metadata=None):
            captured["name"] = name
            captured["metadata"] = metadata
            return _FakeAddCollection()

    class _FakeAddCollection:
        def upsert(self, ids, embeddings, documents, metadatas):
            captured.setdefault("added", []).extend(zip(ids, documents, metadatas))

    monkeypatch.setattr(ic.chromadb, "PersistentClient", lambda path: _FakeClient())
    monkeypatch.setattr(ic, "embed_text", lambda text, task="document": [0.1, 0.2])

    ic.build_collection()

    assert captured["name"] == ic.COLLECTION_NAME
    assert captured["metadata"] == {"hnsw:space": "cosine"}


def test_build_collection_embeds_every_reference_example_as_a_document(monkeypatch):
    captured = {}
    seen_tasks = []

    class _FakeClient:
        def get_or_create_collection(self, name, metadata=None):
            return _FakeAddCollection()

    class _FakeAddCollection:
        def upsert(self, ids, embeddings, documents, metadatas):
            captured.setdefault("added", []).extend(zip(ids, documents, metadatas))

    def fake_embed(text, task="document"):
        seen_tasks.append(task)
        return [0.1, 0.2]

    monkeypatch.setattr(ic.chromadb, "PersistentClient", lambda path: _FakeClient())
    monkeypatch.setattr(ic, "embed_text", fake_embed)

    ic.build_collection()

    expected_count = sum(len(v) for v in ic.REFERENCE_EXAMPLES.values())
    assert len(captured["added"]) == expected_count
    assert all(intent in ic.REFERENCE_EXAMPLES for _id, _doc, meta in captured["added"] for intent in [meta["intent"]])
    assert set(seen_tasks) == {"document"}


def test_reference_examples_cover_every_route_py_intent():
    # Keeps the reference set honest against route.py's actual INTENTS keys,
    # so a new intent added to route.py can't silently miss a reference set.
    sys.path.insert(0, str(LIB.parent / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    assert set(ic.REFERENCE_EXAMPLES) == set(route.INTENTS)
    assert all(len(examples) >= 5 for examples in ic.REFERENCE_EXAMPLES.values())


# ── PR #1118 latency decision: fast path without chromadb ───────────────────
# The owner answered "only if it can be made faster first". The 4 s was ~1.2 s
# importing chromadb plus the embed; the fast path compares the prompt against a
# JSON cache of the reference vectors in plain Python, never touching chromadb.

import json as _json  # noqa: E402
import math as _math  # noqa: E402
import subprocess as _sp  # noqa: E402


def _fake_refs():
    # three intents, unit-ish vectors so cosine is easy to reason about
    return [("recall", [1.0, 0.0, 0.0]), ("coding", [0.0, 1.0, 0.0]),
            ("research", [0.0, 0.0, 1.0])]


def _write_cache(path, refs, key=None, model=None):
    path.write_text(_json.dumps({
        "key": ic.reference_key() if key is None else key,
        "model": ic.EMBED_MODEL if model is None else model,
        "vectors": [{"intent": i, "vec": v} for i, v in refs],
    }))


def test_importing_intent_classify_does_not_import_chromadb():
    code = (f"import sys; sys.path.insert(0, {str(LIB)!r}); import intent_classify; "
            "print('chromadb' in sys.modules)")
    out = _sp.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_importing_route_does_not_import_chromadb():
    scripts = LIB.parent / "skills" / "route" / "scripts"
    code = (f"import sys; sys.path.insert(0, {str(scripts)!r}); import route; "
            "print('chromadb' in sys.modules)")
    out = _sp.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_chromadb_is_still_reachable_as_a_module_attribute():
    # existing tests (and callers) patch ic.chromadb.PersistentClient
    assert hasattr(ic.chromadb, "PersistentClient")


def test_reference_key_changes_when_the_examples_change(monkeypatch):
    before = ic.reference_key()
    changed = {k: list(v) for k, v in ic.REFERENCE_EXAMPLES.items()}
    changed["recall"] = changed["recall"] + ["a brand new example"]
    monkeypatch.setattr(ic, "REFERENCE_EXAMPLES", changed)
    assert ic.reference_key() != before


def test_reference_key_changes_when_the_model_changes(monkeypatch):
    before = ic.reference_key()
    monkeypatch.setattr(ic, "EMBED_MODEL", "some-other-embedder")
    assert ic.reference_key() != before


def test_build_vector_cache_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    seen = []
    monkeypatch.setattr(ic, "embed_text",
                        lambda text, task="query", **kw: seen.append(task) or [0.5, 0.5])
    n = ic.build_vector_cache(path)
    expected = sum(len(v) for v in ic.REFERENCE_EXAMPLES.values())
    assert n == expected
    assert set(seen) == {"document"}
    refs = ic.load_vector_cache(path)
    assert len(refs) == expected
    assert {i for i, _ in refs} == set(ic.REFERENCE_EXAMPLES)


def test_build_vector_cache_writes_nothing_if_any_embed_fails(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    _write_cache(path, _fake_refs())
    good = path.read_text()
    calls = []

    def flaky(text, task="query", **kw):
        calls.append(text)
        return None if len(calls) == 5 else [0.5, 0.5]

    monkeypatch.setattr(ic, "embed_text", flaky)
    assert ic.build_vector_cache(path) == 0
    assert path.read_text() == good           # the old cache is untouched
    assert not list(tmp_path.glob("*.tmp"))   # and no temp file is left behind


def test_build_vector_cache_rejects_mixed_dimensions(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    calls = []
    monkeypatch.setattr(ic, "embed_text",
                        lambda text, task="query", **kw: calls.append(1) or ([0.1] * (2 if len(calls) == 3 else 3)))
    assert ic.build_vector_cache(path) == 0
    assert not path.exists()


def test_load_vector_cache_rejects_every_kind_of_bad_file(tmp_path):
    path = tmp_path / "vectors.json"
    assert ic.load_vector_cache(path) is None                       # missing
    for raw in ("{not json", "[]", "null", '"x"', "{}", '{"key": 1}'):
        path.write_text(raw)
        assert ic.load_vector_cache(path) is None, raw
    _write_cache(path, _fake_refs(), key="stale-key")
    assert ic.load_vector_cache(path) is None                       # examples changed
    _write_cache(path, _fake_refs(), model="other-model")
    assert ic.load_vector_cache(path) is None                       # model changed
    _write_cache(path, [])
    assert ic.load_vector_cache(path) is None                       # empty
    _write_cache(path, [("recall", [1.0, 0.0]), ("coding", [1.0, 0.0, 0.0])])
    assert ic.load_vector_cache(path) is None                       # mixed dims
    _write_cache(path, [("recall", "not a list")])
    assert ic.load_vector_cache(path) is None
    _write_cache(path, [("recall", [1.0, "x"])])
    assert ic.load_vector_cache(path) is None
    _write_cache(path, [("recall", [True, False])])
    assert ic.load_vector_cache(path) is None                       # bools aren't numbers here
    _write_cache(path, [("not-an-intent", [1.0, 0.0])])
    assert ic.load_vector_cache(path) is None
    _write_cache(path, [("recall", [0.0, 0.0])])
    assert ic.load_vector_cache(path) is None                       # zero vector
    _write_cache(path, [("recall", [float("nan"), 1.0])])           # json writes NaN
    assert ic.load_vector_cache(path) is None
    path.write_text(_json.dumps({"key": ic.reference_key(), "model": ic.EMBED_MODEL,
                                 "vectors": [["recall", [1.0]]]}))
    assert ic.load_vector_cache(path) is None


def test_classify_fast_reports_no_cache_without_embedding(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not embed when there's nothing to compare against")
    monkeypatch.setattr(ic, "embed_text", boom)
    r = ic.classify_fast("fix the bug", path=tmp_path / "missing.json")
    assert r == {"status": "no_cache", "intent": None, "score": None}


def test_classify_fast_matches_chromadb_scoring(tmp_path, monkeypatch):
    """Same score as classify(): chroma cosine distance d = 1 - cos, score = 1 - d/2."""
    path = tmp_path / "vectors.json"
    _write_cache(path, _fake_refs())
    q = [0.2, 0.9, 0.1]
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query", **kw: q)
    r = ic.classify_fast("fix the bug", path=path)
    cos = 0.9 / _math.sqrt(sum(x * x for x in q))
    assert r["status"] == "ok" and r["intent"] == "coding"
    assert r["score"] == round(1 - (1 - cos) / 2, 4)


def test_classify_fast_below_threshold_is_no_match(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    _write_cache(path, _fake_refs())
    # equidistant from all three: cos = 1/sqrt(3), score ~0.789; raise the bar above it
    monkeypatch.setattr(ic, "THRESHOLD", 0.9)
    monkeypatch.setattr(ic, "embed_text", lambda text, task="query", **kw: [1.0, 1.0, 1.0])
    r = ic.classify_fast("hmm", path=path)
    assert r["status"] == "no_match" and r["intent"] is None


def test_classify_fast_embeds_as_a_query_with_the_given_timeout(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    _write_cache(path, _fake_refs())
    seen = {}
    monkeypatch.setattr(ic, "embed_text",
                        lambda text, task="query", timeout=None: seen.update(task=task, timeout=timeout) or [1.0, 0, 0])
    ic.classify_fast("x", path=path, timeout=0.7)
    assert seen == {"task": "query", "timeout": 0.7}


def test_classify_fast_is_unavailable_on_bad_query_vectors(tmp_path, monkeypatch):
    path = tmp_path / "vectors.json"
    _write_cache(path, _fake_refs())
    for bad in (None, [], [0.0, 0.0, 0.0], [1.0, 0.0], [float("nan"), 1.0, 0.0], "abc"):
        monkeypatch.setattr(ic, "embed_text", lambda text, task="query", _b=bad, **kw: _b)
        r = ic.classify_fast("x", path=path)
        assert r == {"status": "unavailable", "intent": None, "score": None}, bad


def test_embed_text_passes_its_timeout_to_ollama(monkeypatch):
    seen = {}

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[0.1]]}

    monkeypatch.setattr(ic.requests, "post", lambda url, json, timeout: seen.update(t=timeout) or _R())
    ic.embed_text("x", timeout=0.5)
    assert seen["t"] == 0.5
    ic.embed_text("x")
    assert seen["t"] == 10       # the default for every other caller is unchanged


def test_embed_text_returns_none_on_a_malformed_reply(monkeypatch):
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": []}

    monkeypatch.setattr(ic.requests, "post", lambda url, json, timeout: _R())
    assert ic.embed_text("x") is None


def test_seed_also_rebuilds_the_vector_cache(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ic, "build_collection", lambda: calls.append("chroma") or 3)
    monkeypatch.setattr(ic, "build_vector_cache", lambda path=None: calls.append("vectors") or 3)
    monkeypatch.setattr(sys, "argv", ["intent_classify.py", "--seed"])
    ic.main()
    assert calls == ["chroma", "vectors"]


def test_build_vectors_flag_builds_only_the_cache(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ic, "build_collection", lambda: calls.append("chroma") or 3)
    monkeypatch.setattr(ic, "build_vector_cache", lambda path=None: calls.append("vectors") or 3)
    monkeypatch.setattr(sys, "argv", ["intent_classify.py", "--build-vectors"])
    ic.main()
    assert calls == ["vectors"]


def test_build_vectors_flag_exits_nonzero_when_it_fails(monkeypatch):
    import pytest
    monkeypatch.setattr(ic, "build_vector_cache", lambda path=None: 0)
    monkeypatch.setattr(sys, "argv", ["intent_classify.py", "--build-vectors"])
    with pytest.raises(SystemExit) as e:
        ic.main()
    assert e.value.code == 1
