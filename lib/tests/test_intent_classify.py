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
