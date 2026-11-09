"""No test downloads an embedding model (#1156, conftest.py rule 4).

Chroma's default embedding downloads an ~80 MB ONNX model the first time a collection embeds anything. On a CI runner
with no copy, the parallel test workers all fetched it at once into the one shared ~/.cache and broke each other's
download, so a different handful of the 37 tests that embed failed each run (3 on 2026-11-06, 1 on 2026-11-09) and
main stayed red. No test is about embedding quality, so the root conftest.py gives every test a deterministic stand-in.
The fixture below recreates the runner's condition: no model cached, and any fetch fails loudly.
"""
from __future__ import annotations

import chromadb
import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2


@pytest.fixture
def no_download(monkeypatch, tmp_path):
    """CI's condition: no model cached anywhere, and any attempt to fetch one fails loudly."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to download Chroma's embedding model")

    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", tmp_path / "empty-model-cache")
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "_download", refuse)


def test_add_and_query_download_nothing(tmp_path, no_download):
    col = chromadb.PersistentClient(path=str(tmp_path)).get_or_create_collection("papers")
    col.add(ids=["a", "b"], documents=["scaling laws for language models", "protein folding"])
    hit = col.query(query_texts=["language model scaling"], n_results=1)
    assert hit["ids"] == [["a"]]  # the stand-in still ranks the closer text first


def test_the_stand_in_is_deterministic(tmp_path, no_download):
    ef = ONNXMiniLM_L6_V2()
    first, second = ef(["same text"]), ef(["same text"])
    assert len(first[0]) == 384  # same width as the real model, so collections never mismatch
    assert list(first[0]) == list(second[0])


def test_empty_and_odd_input(tmp_path, no_download):
    ef = ONNXMiniLM_L6_V2()
    vecs = ef(["", "   ", "ünïcödé ✓ " * 500])
    assert len(vecs) == 3 and all(len(v) == 384 for v in vecs)
