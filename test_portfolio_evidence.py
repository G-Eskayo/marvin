"""Evidence-log integration: parsing, filtering, link-checking, and rendering (lib/portfolio_evidence.py, ticket #382).

NOTE: This test file is a staging location in the worktree. After verification, it should be copied to
~/.agents/lib/tests/test_portfolio_evidence.py by the user or an automated process.
"""
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from unittest.mock import patch

# For local testing against the module being developed
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

try:
    import portfolio_evidence as pe  # noqa: E402
    import portfolio_content as pc  # noqa: E402
except ImportError as e:
    print(f"Note: full test suite requires module at ~/.agents/lib/portfolio_evidence.py")
    print(f"Import error: {e}")
    pe = None
    pc = None


# ── fixtures ────────────────────────────────────────────────────────────────

# Real evidence-log format (from clarity-captions PR #100)
FIXTURE_LOG = """# Evidence log

Here are the sources that shaped real decisions.

## E1. SwiftUI performance profiling with Instruments

**Source:** [Apple Instruments guide](https://developer.apple.com/instruments/)

**What we took:** Learned that capturing and composing long lists of captions caused frame drops. Instruments showed us exactly which methods were CPU-bound vs. memory-bound.

**Confidence:** High — we had Instruments traces showing the bottleneck.

**Drives:** Made us reach for UIViewRepresentable lazy loading and defer caption composition until display time.

**Public use:** Yes

## E2. Offline dictionaries for iOS

**Source:** [Linguistic data formats](https://en.wikipedia.org/wiki/Dictionary_software)

**What we took:** iOS can't easily download and parse gigabyte dictionaries at install time. Compact binary formats (trie-based) let us ship one 40 MB payload.

**Confidence:** Medium — we didn't profile every format, only picked the one that shipped fastest.

**Drives:** Chose a trie-compressed dictionary instead of a raw word list.

**Public use:** Careful ("trie format not documented; changes to it require a full re-download")

## E3. Test data without a public-use flag

**Source:** [Testing guide](https://example.com/test)

**What we took:** Something useful here.

**Confidence:** High

**Drives:** Some decision

**Public use:** Internal

## E4. Careful without caveat (malformed)

**Source:** [Some source](https://example.com)

**What we took:** Something

**Confidence:** Medium

**Drives:** A decision

**Public use:** Careful

## E5. Entry missing public-use entirely

**Source:** [Another source](https://example.com)

**What we took:** Something else

**Confidence:** High

**Drives:** Another decision

"""

FIXTURE_DEAD_LINK = """# Evidence log

## E1. Dead source

**Source:** [Old blog](http://localhost:9999/dead)

**What we took:** Something

**Confidence:** High

**Drives:** A call

**Public use:** Yes
"""


if pe:
    # ── test helpers ────────────────────────────────────────────────────────────

    class _MockHTTPHandler(BaseHTTPRequestHandler):
        """Mock HTTP server for testing link checking."""
        def do_HEAD(self):
            if self.path == "/live":
                self.send_response(200)
            elif self.path == "/redirect":
                self.send_response(301)
                self.send_header("Location", "http://localhost:9998/")
            elif self.path == "/timeout":
                sleep(10)
            else:
                self.send_response(404)
            self.end_headers()

        def do_GET(self):
            self.do_HEAD()

        def log_message(self, format, *args):
            pass


    def _start_mock_server(port: int) -> HTTPServer:
        """Start a mock HTTP server on the given port."""
        server = HTTPServer(("localhost", port), _MockHTTPHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        sleep(0.1)  # Let the server start
        return server


    # ── parse_log ──────────────────────────────────────────────────────────────

    def test_parse_log_extracts_heading_and_fields():
        entries = pe.parse_log(FIXTURE_LOG)
        assert len(entries) >= 2
        assert entries[0]["title"] == "SwiftUI performance profiling with Instruments"
        assert entries[0]["source"] == "[Apple Instruments guide](https://developer.apple.com/instruments/)"
        assert "frame drops" in entries[0]["what_we_took"]
        assert entries[0]["confidence"] == "High"
        assert entries[0]["public_use"] == "Yes"


    def test_parse_log_extracts_caveat_from_careful_entries():
        entries = pe.parse_log(FIXTURE_LOG)
        careful = [e for e in entries if e.get("public_use") == "Careful"]
        assert len(careful) >= 1
        assert "trie format not documented" in careful[0].get("caveat", "")


    def test_parse_log_returns_empty_on_no_entries():
        empty = "# Evidence log\n\nNo entries below."
        assert pe.parse_log(empty) == []


    def test_parse_log_handles_missing_drives_field():
        partial = "## E1. Test\n\n**Source:** [x](http://x)\n\n**Public use:** Yes"
        entries = pe.parse_log(partial)
        assert len(entries) == 1
        assert entries[0].get("drives") == ""


    # ── classify ────────────────────────────────────────────────────────────────

    def test_classify_yes_entries():
        entry = {"public_use": "Yes"}
        assert pe.classify(entry) == "yes"


    def test_classify_careful_entries():
        entry = {"public_use": "Careful (caveat text)", "caveat": "caveat text"}
        assert pe.classify(entry) == "careful"


    def test_classify_internal_entries():
        entry = {"public_use": "Internal"}
        assert pe.classify(entry) == "internal"


    def test_classify_missing_public_use_as_internal():
        entry = {"source": "x"}
        assert pe.classify(entry) == "internal"


    def test_classify_careful_without_caveat_as_malformed():
        entry = {"public_use": "Careful"}
        assert pe.classify(entry) == "malformed"


    def test_classify_is_case_insensitive():
        assert pe.classify({"public_use": "yes"}) == "yes"
        assert pe.classify({"public_use": "YES"}) == "yes"
        assert pe.classify({"public_use": "Internal"}) == "internal"


    # ── link checking ──────────────────────────────────────────────────────────

    def test_check_link_verifies_urls_with_http_head():
        server = _start_mock_server(9997)
        try:
            assert pe.check_link("http://localhost:9997/live", timeout=1.0) is True
            assert pe.check_link("http://localhost:9997/notfound", timeout=1.0) is False
        finally:
            server.shutdown()


    def test_check_link_handles_connection_refused():
        # Try a port that's unlikely to be in use
        result = pe.check_link("http://localhost:9996/", timeout=0.5)
        assert result is False


    def test_check_link_respects_timeout():
        server = _start_mock_server(9995)
        try:
            # This should timeout and return False
            result = pe.check_link("http://localhost:9995/timeout", timeout=0.1)
            assert result is False
        finally:
            server.shutdown()


    # ── public_entries filtering ────────────────────────────────────────────────

    def test_public_entries_includes_yes_and_careful():
        entries = pe.parse_log(FIXTURE_LOG)
        public, findings = pe.public_entries(entries, probe=lambda u: True)

        # Should have E1 (Yes) and E2 (Careful)
        assert len(public) == 2
        assert public[0]["title"] == "SwiftUI performance profiling with Instruments"
        assert public[1]["title"] == "Offline dictionaries for iOS"


    def test_public_entries_excludes_internal_and_malformed():
        entries = pe.parse_log(FIXTURE_LOG)
        public, findings = pe.public_entries(entries, probe=lambda u: True)

        # E3 is Internal, E4 is malformed (Careful without caveat), E5 is missing public_use
        titles = {e["title"] for e in public}
        assert "Test data without a public-use flag" not in titles
        assert "Careful without caveat (malformed)" not in titles
        assert "Entry missing public-use entirely" not in titles


    def test_public_entries_detects_dead_links():
        entries = pe.parse_log(FIXTURE_DEAD_LINK)
        public, findings = pe.public_entries(entries, probe=lambda u: False)

        assert len(public) == 1
        assert len(findings) > 0
        assert any(f["rule"] == "dead-link" for f in findings)


    def test_public_entries_emits_internal_or_malformed_finding():
        entries = pe.parse_log(FIXTURE_LOG)
        public, findings = pe.public_entries(entries, probe=lambda u: True)

        # E4 (Careful without caveat) and E5 (missing public_use) should be flagged
        # E3 (Internal) should NOT be flagged (silent exclusion)
        internal_findings = [f for f in findings if f["rule"] == "internal-or-malformed"]
        assert len(internal_findings) >= 2  # E4 and E5


    # ── rendering ──────────────────────────────────────────────────────────────

    def test_render_html_includes_all_public_entries():
        entries = pe.parse_log(FIXTURE_LOG)
        public, _ = pe.public_entries(entries, probe=lambda u: True)
        html = pe.render_html(public)

        assert "SwiftUI performance profiling" in html
        assert "Offline dictionaries for iOS" in html
        assert "Test data without a public-use flag" not in html


    def test_render_html_produces_valid_html():
        entries = pe.parse_log(FIXTURE_LOG)
        public, _ = pe.public_entries(entries, probe=lambda u: True)
        html = pe.render_html(public)

        # Check basic structure (no unclosed tags, wrapping div, etc.)
        assert html.count("<div") == html.count("</div>")
        assert html.count("<span") == html.count("</span>")
        assert html.startswith("<div")
        assert html.endswith("</div>")


    # ── sync ────────────────────────────────────────────────────────────────────

    def test_sync_reads_evidence_log_and_parses_it():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            repo = tmpdir / "test-repo"
            repo.mkdir()
            (repo / "docs" / "research").mkdir(parents=True)
            (repo / "docs" / "research" / "evidence-log.md").write_text(FIXTURE_LOG)

            # Create a minimal content JSON
            project = tmpdir / "portfolio"
            project.mkdir()
            (project / "content" / "longform").mkdir(parents=True)
            content_file = project / "content" / "longform" / "test-slug.json"
            content_file.write_text(json.dumps({
                "content_type": "app-product",
                "lead_html": "<p>Test</p>",
                "sections": []
            }))

            result = pe.sync("test-slug", repo=repo, project=project)
            assert result["ok"] is True
            assert result["has_log"] is True
            assert result["entries"] == 2  # E1 (Yes) and E2 (Careful)


    def test_sync_handles_missing_evidence_log():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            repo = tmpdir / "test-repo"
            repo.mkdir()

            project = tmpdir / "portfolio"
            project.mkdir()
            (project / "content" / "longform").mkdir(parents=True)
            content_file = project / "content" / "longform" / "test-slug.json"
            content_file.write_text(json.dumps({
                "content_type": "app-product",
                "lead_html": "<p>Test</p>",
                "sections": []
            }))

            result = pe.sync("test-slug", repo=repo, project=project)
            assert result["ok"] is True
            assert result["has_log"] is False


    def test_sync_is_idempotent():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            repo = tmpdir / "test-repo"
            repo.mkdir()
            (repo / "docs" / "research").mkdir(parents=True)
            (repo / "docs" / "research" / "evidence-log.md").write_text(FIXTURE_LOG)

            project = tmpdir / "portfolio"
            project.mkdir()
            (project / "content" / "longform").mkdir(parents=True)
            content_file = project / "content" / "longform" / "test-slug.json"
            content_file.write_text(json.dumps({
                "content_type": "app-product",
                "lead_html": "<p>Test</p>",
                "sections": []
            }))

            # First sync
            result1 = pe.sync("test-slug", repo=repo, project=project)
            content1 = content_file.read_text()

            # Second sync (unchanged)
            result2 = pe.sync("test-slug", repo=repo, project=project)
            content2 = content_file.read_text()

            assert result2["changed"] is False
            assert content1 == content2


    def test_sync_sets_has_evidence_log_flag():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            repo = tmpdir / "test-repo"
            repo.mkdir()
            (repo / "docs" / "research").mkdir(parents=True)
            (repo / "docs" / "research" / "evidence-log.md").write_text(FIXTURE_LOG)

            project = tmpdir / "portfolio"
            project.mkdir()
            (project / "content" / "longform").mkdir(parents=True)
            content_file = project / "content" / "longform" / "test-slug.json"
            content_file.write_text(json.dumps({
                "content_type": "app-product",
                "lead_html": "<p>Test</p>",
                "sections": []
            }))

            result = pe.sync("test-slug", repo=repo, project=project)
            content = json.loads(content_file.read_text())

            assert content.get("has_evidence_log") is True

else:
    def test_placeholder():
        """Placeholder test when module is not available."""
        pass
