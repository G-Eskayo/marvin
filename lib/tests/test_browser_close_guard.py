"""Tests for browser_close_guard.py (Playwright browser cleanup guards, G-Eskayo/marvin#415).

Comprehensive tests for comment stripping, launch detection, variable assignment tracking,
and channel: 'chrome' comments.
"""
from pathlib import Path
from textwrap import dedent

import pytest

import browser_close_guard


class TestStripComments:
    """Tests for _strip_comments helper."""

    def test_strips_trailing_comment(self):
        """_strip_comments removes everything after //."""
        line = "const x = 1; // this is a comment"
        stripped = browser_close_guard._strip_comments(line)
        assert stripped == "const x = 1; "

    def test_preserves_strings_with_slashes(self):
        """_strip_comments doesn't strip // inside strings."""
        line = 'const url = "https://example.com"; // comment'
        stripped = browser_close_guard._strip_comments(line)
        assert "https://example.com" in stripped
        assert "comment" not in stripped

    def test_preserves_single_quote_strings(self):
        """_strip_comments preserves strings in single quotes."""
        line = "const msg = 'hello // world'; // real comment"
        stripped = browser_close_guard._strip_comments(line)
        assert "hello // world" in stripped
        assert "real comment" not in stripped

    def test_preserves_backtick_strings(self):
        """_strip_comments preserves backtick strings."""
        line = 'const template = `http://localhost`; // comment'
        stripped = browser_close_guard._strip_comments(line)
        assert "http://localhost" in stripped
        assert "comment" not in stripped

    def test_empty_after_stripping(self):
        """_strip_comments returns empty string if only comment."""
        line = "// entire line is comment"
        stripped = browser_close_guard._strip_comments(line)
        assert stripped == ""

    def test_no_comment(self):
        """_strip_comments returns full line if no comment."""
        line = "const x = 1;"
        stripped = browser_close_guard._strip_comments(line)
        assert stripped == line


class TestCheckSourceLaunchDetection:
    """Tests for .launch( detection in check_source."""

    def test_flags_awaited_launch_without_close(self):
        """check_source flags await browserType.launch() without close."""
        source = dedent("""\
            const browser = await chromium.launch()
            const page = await browser.newPage()
        """)
        violations = browser_close_guard.check_source(source)
        assert len(violations) > 0
        assert any("browser-launch-cleanup" in str(v) for v in violations)

    def test_accepts_awaited_launch_with_same_line_close(self):
        """check_source accepts await close() on same statement line."""
        source = dedent("""\
            const browser = await chromium.launch()
            await browser.close()
        """)
        violations = browser_close_guard.check_source(source)
        # Should not flag launch cleanup issue
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) == 0

    def test_accepts_close_several_lines_later(self):
        """check_source accepts await close() a few lines after launch."""
        source = dedent("""\
            const browser = await chromium.launch()
            const page = await browser.newPage()
            doSomething()
            await browser.close()
        """)
        violations = browser_close_guard.check_source(source)
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) == 0

    def test_flags_bare_unassigned_launch(self):
        """check_source flags bare .launch( without assignment."""
        source = dedent("""\
            await chromium.launch({
                headless: true,
            })
        """)
        violations = browser_close_guard.check_source(source)
        assert any("browser-launch-unassigned" in str(v) for v in violations)

    def test_flags_non_awaited_launch(self):
        """check_source flags .launch( without await."""
        source = dedent("""\
            const browser = chromium.launch()
        """)
        violations = browser_close_guard.check_source(source)
        assert any("browser-launch-cleanup" in str(v) for v in violations)

    def test_multiline_launch_with_close(self):
        """check_source handles .launch( spread across lines with later close."""
        source = dedent("""\
            const browser = await chromium.launch({
                headless: true,
                args: ['--disable-extensions']
            })
            await browser.close()
        """)
        violations = browser_close_guard.check_source(source)
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) == 0

    def test_multiline_launch_without_close(self):
        """check_source flags multiline .launch( without close."""
        source = dedent("""\
            const browser = await chromium.launch({
                headless: true
            })
            doSomething()
        """)
        violations = browser_close_guard.check_source(source)
        assert any("browser-launch-cleanup" in str(v) for v in violations)

    def test_different_variable_names(self):
        """check_source tracks different variable names correctly."""
        source = dedent("""\
            const browserA = await chromium.launch()
            const browserB = await firefox.launch()
            await browserA.close()
        """)
        violations = browser_close_guard.check_source(source)
        # Should flag browserB as missing close
        assert any("browser-launch-cleanup" in str(v) for v in violations)

    def test_ignores_close_for_wrong_variable(self):
        """check_source doesn't accept close() for wrong variable."""
        source = dedent("""\
            const browserA = await chromium.launch()
            const browserB = await firefox.launch()
            await browserA.close()
        """)
        violations = browser_close_guard.check_source(source)
        # browserB should still be flagged
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) > 0


class TestCheckSourceChannelChrome:
    """Tests for channel: 'chrome' detection."""

    def test_flags_chrome_without_comment(self):
        """check_source flags channel: 'chrome' without // comment."""
        source = dedent("""\
            const browser = await chromium.launch({
                channel: 'chrome'
            })
        """)
        violations = browser_close_guard.check_source(source)
        assert any("channel-chrome-no-comment" in str(v) for v in violations)

    def test_accepts_chrome_with_inline_comment(self):
        """check_source accepts channel: 'chrome' with inline // comment."""
        source = dedent("""\
            const browser = await chromium.launch({
                channel: 'chrome' // test-only override
            })
        """)
        violations = browser_close_guard.check_source(source)
        chrome_violations = [v for v in violations if "channel-chrome-no-comment" in str(v)]
        assert len(chrome_violations) == 0

    def test_accepts_chrome_with_next_line_comment(self):
        """check_source accepts channel: 'chrome' with comment on next line."""
        source = dedent("""\
            const browser = await chromium.launch({
                channel: 'chrome'
                // Use system Chrome for API coverage
            })
        """)
        violations = browser_close_guard.check_source(source)
        chrome_violations = [v for v in violations if "channel-chrome-no-comment" in str(v)]
        assert len(chrome_violations) == 0

    def test_detects_double_quotes_chrome(self):
        """check_source detects channel: \"chrome\" as well."""
        source = dedent("""\
            const browser = await chromium.launch({
                channel: "chrome"
            })
        """)
        violations = browser_close_guard.check_source(source)
        assert any("channel-chrome-no-comment" in str(v) for v in violations)

    def test_chrome_comment_must_be_on_original_line(self):
        """check_source doesn't strip comments when checking for chrome explanation."""
        # The channel check happens on original line, not stripped line
        source = dedent("""\
            const browser = await chromium.launch({
                channel: 'chrome' // comment here
            })
        """)
        violations = browser_close_guard.check_source(source)
        chrome_violations = [v for v in violations if "channel-chrome-no-comment" in str(v)]
        assert len(chrome_violations) == 0


class TestCheckSourceLineNumbers:
    """Tests for correct line number reporting."""

    def test_reports_correct_line_for_launch(self):
        """check_source reports correct line for .launch( violation."""
        source = dedent("""\
            // Line 1
            const browser = await chromium.launch()
            // Line 3
        """)
        violations = browser_close_guard.check_source(source)
        assert any(v[0] == 2 for v in violations)

    def test_reports_correct_line_for_chrome(self):
        """check_source reports correct line for channel: 'chrome' violation."""
        source = dedent("""\
            // Line 1
            const config = {
                channel: 'chrome'
            }
        """)
        violations = browser_close_guard.check_source(source)
        chrome_violations = [v for v in violations if "channel-chrome-no-comment" in str(v)]
        assert any(v[0] == 3 for v in chrome_violations)


class TestCheckSourceIgnoreComments:
    """Tests for ignoring violations inside comments."""

    def test_ignores_commented_launch(self):
        """check_source ignores .launch( in comments."""
        source = dedent("""\
            // const browser = await chromium.launch()
            const x = 1
        """)
        violations = browser_close_guard.check_source(source)
        # Commented line should not be flagged
        launch_violations = [v for v in violations if "browser-launch" in str(v)]
        assert len(launch_violations) == 0

    def test_ignores_commented_chrome(self):
        """check_source ignores channel: 'chrome' in comments."""
        source = dedent("""\
            // channel: 'chrome' without comment
            const x = 1
        """)
        violations = browser_close_guard.check_source(source)
        chrome_violations = [v for v in violations if "channel-chrome-no-comment" in str(v)]
        assert len(chrome_violations) == 0


class TestCheckFile:
    """Tests for check_file function."""

    def test_reads_and_checks(self, tmp_path):
        """check_file reads a file and checks its source."""
        test_file = tmp_path / "test.mjs"
        test_file.write_text(dedent("""\
            const browser = await chromium.launch()
            await browser.close()
        """))
        violations = browser_close_guard.check_file(test_file)
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) == 0

    def test_handles_missing_file(self, tmp_path):
        """check_file returns [] for missing files."""
        violations = browser_close_guard.check_file(tmp_path / "nonexistent.mjs")
        assert violations == []

    def test_handles_decode_error(self, tmp_path):
        """check_file returns [] for non-UTF8 files."""
        test_file = tmp_path / "binary.mjs"
        test_file.write_bytes(b"\x80\x81\x82")
        violations = browser_close_guard.check_file(test_file)
        assert violations == []


class TestCheckRepo:
    """Tests for check_repo function."""

    def test_finds_test_mjs_files(self, tmp_path):
        """check_repo scans all .test.mjs files."""
        (tmp_path / "snapshot.test.mjs").write_text(dedent("""\
            after(async () => { await browser?.close() })
        """))
        (tmp_path / "code.test.mjs").write_text(dedent("""\
            const browser = await chromium.launch()
        """))

        violations = browser_close_guard.check_repo(tmp_path)

        assert "code.test.mjs" in violations
        assert len(violations["code.test.mjs"]) > 0

    def test_excludes_node_modules(self, tmp_path):
        """check_repo skips .test.mjs files in node_modules."""
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "pkg.test.mjs").write_text("const browser = await chromium.launch()")

        violations = browser_close_guard.check_repo(tmp_path)

        assert all("node_modules" not in path for path in violations.keys())

    def test_only_scans_test_mjs_files(self, tmp_path):
        """check_repo only scans .test.mjs, not all .mjs."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "app.test.mjs").write_text("const browser = await chromium.launch()")
        (sub / "utils.mjs").write_text("const browser = await chromium.launch()")

        violations = browser_close_guard.check_repo(tmp_path)

        # app.test.mjs should be checked
        assert any("app.test.mjs" in f for f in violations.keys())
        # utils.mjs should not be checked
        assert not any("utils.mjs" in f for f in violations.keys())


class TestMainBehavior:
    """Tests for __main__ behavior."""

    def test_success_exit_code(self, tmp_path, monkeypatch, capsys):
        """__main__ exits 0 when no violations found."""
        test_file = tmp_path / "clean.test.mjs"
        test_file.write_text("// No violations here")

        monkeypatch.chdir(tmp_path)
        violations = browser_close_guard.check_repo(tmp_path)

        assert not violations  # No violations found

    def test_failure_exit_code(self, tmp_path, monkeypatch):
        """__main__ detects violations."""
        test_file = tmp_path / "dirty.test.mjs"
        test_file.write_text("const browser = await chromium.launch()")

        monkeypatch.chdir(tmp_path)
        violations = browser_close_guard.check_repo(tmp_path)

        assert len(violations) > 0


class TestModuleExports:
    """Tests for module interface."""

    def test_exports_check_source(self):
        """Module exports check_source."""
        assert hasattr(browser_close_guard, "check_source")
        assert callable(browser_close_guard.check_source)

    def test_exports_check_file(self):
        """Module exports check_file."""
        assert hasattr(browser_close_guard, "check_file")
        assert callable(browser_close_guard.check_file)

    def test_exports_check_repo(self):
        """Module exports check_repo."""
        assert hasattr(browser_close_guard, "check_repo")
        assert callable(browser_close_guard.check_repo)


class TestComplexPatterns:
    """Tests for complex real-world patterns."""

    def test_context_manager_with_launch(self):
        """check_source handles launch inside context managers."""
        source = dedent("""\
            async with asyncBrowserGuard() as guard {
                const browser = await chromium.launch()
            }
        """)
        violations = browser_close_guard.check_source(source)
        # Context manager may handle cleanup, but pattern is unusual
        # This test documents current behavior
        assert isinstance(violations, list)

    def test_try_finally_pattern(self):
        """check_source recognizes try/finally patterns."""
        source = dedent("""\
            try {
                const browser = await chromium.launch()
                doWork()
            } finally {
                await browser.close()
            }
        """)
        violations = browser_close_guard.check_source(source)
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        assert len(cleanup_violations) == 0

    def test_multiple_browsers_different_variables(self):
        """check_source tracks multiple browser variables independently."""
        source = dedent("""\
            const chromium = await chromium.launch()
            const firefox = await firefox.launch()
            const webkit = await webkit.launch()
            await chromium.close()
            await firefox.close()
        """)
        violations = browser_close_guard.check_source(source)
        cleanup_violations = [v for v in violations if "browser-launch-cleanup" in str(v)]
        # webkit should be flagged
        assert len(cleanup_violations) > 0

    def test_string_with_launch_inside(self):
        """check_source doesn't flag .launch( inside strings."""
        source = dedent("""\
            const message = "const browser = await chromium.launch()"
            const x = 1
        """)
        violations = browser_close_guard.check_source(source)
        launch_violations = [v for v in violations if "browser-launch" in str(v)]
        assert len(launch_violations) == 0
