# Mocking Guidelines

**Mock at the true external boundary only** — network calls, real ML model inference, anything
that's slow, non-deterministic, or requires infrastructure you don't want tests depending on.
Never mock your own internal collaborators just to isolate a unit — that's how you end up testing
implementation instead of behavior (see [tests.md](tests.md)).

**Prefer dependency injection over patching** when the seam is one you control. A function that
takes its dependency as a parameter is easier to test *and* easier to read than one that reaches
for a global and gets monkeypatched in tests:

```python
# Injectable — tests supply a fake, no monkeypatching needed
def traverse(seed_doi, fetch_fn, max_depth, ...):
    ...
    neighbors = fetch_fn(doi)

# Test
def fake_fetch(doi):
    return {"references": [...], "citations": [...]}
result = traverse(seed_doi="seed", fetch_fn=fake_fetch, max_depth=1, ...)
```

**Reserve `monkeypatch`/`unittest.mock` for boundaries you don't own** — a third-party library's
HTTP client, for instance, where there's no injection seam available:

```python
def fake_get(url, params=None, timeout=None):
    return _FakeResponse(canned_payload)

monkeypatch.setattr("requests.get", fake_get)
```

**Prefer a real instance over a mock when the real thing is fast and reproducible.** A temporary,
isolated ChromaDB client (`chromadb.PersistentClient(path=str(tmp_path))`) is not meaningfully
slower than mocking ChromaDB's API, and it exercises real behavior instead of an assumption about
what that behavior is:

```python
def test_is_known_distinguishes_known_and_unknown_dois(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection("paper-knowledge")
    collection.add(ids=["10.1234/known"], documents=["..."], metadatas=[{"doi": "10.1234/known"}])
    assert is_known("10.1234/known", collection) is True
```

**Never let "the fast path" quietly trigger the real path.** If a function defaults to a real,
heavy backend when no fake is injected, make sure tests always inject the fake explicitly —
otherwise a "fast" unit test suite can silently start making real network/model calls the moment
someone forgets an argument.
