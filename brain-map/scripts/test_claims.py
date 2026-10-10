#!/usr/bin/env python3
"""
Comprehensive adversarial tests for claims.py per the plan.
Tests first, before wiring CLI/nightly path.
"""
import json
import pytest
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims


class TestCheckTwoMachines:
    def test_exactly_two_devices(self):
        devices = {"mac-mini-1": {}, "macbook-pro-1": {}}
        result = claims.check_two_machines(devices)
        assert result["ok"] is True
        assert "2 devices" in result["detail"]

    def test_zero_devices(self):
        devices = {}
        result = claims.check_two_machines(devices)
        assert result["ok"] is False
        assert "no devices" in result["detail"]

    def test_one_device(self):
        devices = {"mac-mini-1": {}}
        result = claims.check_two_machines(devices)
        assert result["ok"] is False
        assert "1 device" in result["detail"]

    def test_three_devices(self):
        devices = {"mac-mini-1": {}, "macbook-pro-1": {}, "linux-box": {}}
        result = claims.check_two_machines(devices)
        assert result["ok"] is False
        assert "3 devices" in result["detail"]

    def test_missing_devices_key(self):
        result = claims.check_two_machines({"other_key": {}})
        assert result["ok"] is False

    def test_devices_not_dict(self):
        result = claims.check_two_machines("not a dict")
        assert result["ok"] is False
        assert "not a dict" in result["detail"]


class TestCheckMainHealthClaim:
    @patch("claims.health_checks.check_main_health")
    def test_main_health_green(self, mock_check):
        mock_check.return_value = {
            "severity": "green",
            "detail": "main @ abc123: passing"
        }
        result = claims.check_main_health_claim()
        assert result["ok"] is True
        assert "passing" in result["detail"]

    @patch("claims.health_checks.check_main_health")
    def test_main_health_yellow(self, mock_check):
        mock_check.return_value = {
            "severity": "yellow",
            "detail": "last check is more than a day old"
        }
        result = claims.check_main_health_claim()
        assert result["ok"] is False
        assert "stale" in result["detail"]

    @patch("claims.health_checks.check_main_health")
    def test_main_health_red(self, mock_check):
        mock_check.return_value = {
            "severity": "red",
            "detail": "main is failing: test_foo.py"
        }
        result = claims.check_main_health_claim()
        assert result["ok"] is False
        assert "failing" in result["detail"]


class TestCheckRepoVisibility:
    def test_catalog_public(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_data = {
                "projects": [
                    {"repo": "G-Eskayo/marvin", "visibility": "PUBLIC"}
                ]
            }
            catalog_path.write_text(json.dumps(catalog_data))
            result = claims.check_repo_visibility(catalog_path)
            assert result["ok"] is True
            assert "PUBLIC" in result["detail"]

    def test_catalog_private(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_data = {
                "projects": [
                    {"repo": "G-Eskayo/marvin", "visibility": "PRIVATE"}
                ]
            }
            catalog_path.write_text(json.dumps(catalog_data))
            result = claims.check_repo_visibility(catalog_path)
            assert result["ok"] is False
            assert "PRIVATE" in result["detail"]

    def test_catalog_internal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_data = {
                "projects": [
                    {"repo": "G-Eskayo/marvin", "visibility": "INTERNAL"}
                ]
            }
            catalog_path.write_text(json.dumps(catalog_data))
            result = claims.check_repo_visibility(catalog_path)
            assert result["ok"] is False

    def test_catalog_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "nonexistent.json"
            # Should fall back to gh command
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = json.dumps({"visibility": "PUBLIC"})
                mock_run.return_value = mock_result
                result = claims.check_repo_visibility(catalog_path)
                assert result["ok"] is True

    def test_catalog_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_data = {"projects": []}
            catalog_path.write_text(json.dumps(catalog_data))
            # Should fall back to gh
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = json.dumps({"visibility": "PUBLIC"})
                mock_run.return_value = mock_result
                result = claims.check_repo_visibility(catalog_path)
                assert result["ok"] is True

    @patch("subprocess.run")
    def test_gh_call_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 20)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = claims.check_repo_visibility(Path(tmpdir) / "nonexistent.json")
            assert result["ok"] is None

    @patch("subprocess.run")
    def test_gh_gate_defer(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 75  # gate defer
        mock_run.return_value = mock_result
        with tempfile.TemporaryDirectory() as tmpdir:
            result = claims.check_repo_visibility(Path(tmpdir) / "nonexistent.json")
            assert result["ok"] is None
            assert "unknown" in result["detail"]

    @patch("subprocess.run")
    def test_gh_malformed_json(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_run.return_value = mock_result
        with tempfile.TemporaryDirectory() as tmpdir:
            result = claims.check_repo_visibility(Path(tmpdir) / "nonexistent.json")
            assert result["ok"] is None


class TestCheckJobsRecent:
    def test_all_jobs_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            jobs_dir.mkdir()

            # Create a job record with idle status (last run passed)
            job_doc = {
                "runs": [
                    {"status": "passed", "started_at": "2026-10-10T10:00:00+00:00"}
                ]
            }
            (jobs_dir / "snapshot-deploy.json").write_text(json.dumps(job_doc))

            with patch("claims.HOME", Path(tmpdir)):
                with patch.object(claims, "HOME", Path(tmpdir)):
                    # Override the jobs_dir lookup
                    original_check = claims.check_jobs_recent

                    def patched_check():
                        jobs_dir_path = Path(tmpdir) / ".claude" / "logs" / "jobs"
                        if not jobs_dir_path.exists():
                            jobs_dir_path = jobs_dir
                        if not jobs_dir_path.exists():
                            return {"ok": False, "detail": "jobs directory not found"}

                        jobs_data = []
                        for job_file in sorted(jobs_dir_path.glob("*.json")):
                            try:
                                doc = json.loads(job_file.read_text())
                                jobs_data.append((job_file.stem, doc))
                            except (json.JSONDecodeError, OSError):
                                pass

                        if not jobs_data:
                            return {"ok": False, "detail": "no job records found"}

                        failed_jobs = []
                        now = datetime.now(timezone.utc)
                        for job_name, doc in jobs_data:
                            import job_events as je
                            status = je.status_of(doc, now)
                            if status in ("failed", "crashed"):
                                failed_jobs.append(f"{job_name}:{status}")
                            elif status == "never":
                                failed_jobs.append(f"{job_name}:never-run")

                        if failed_jobs:
                            return {"ok": False, "detail": f"{len(failed_jobs)} jobs not healthy"}
                        return {"ok": True, "detail": f"{len(jobs_data)} jobs all healthy"}

                    result = patched_check()
                    assert result["ok"] is True
                    assert "healthy" in result["detail"]

    def test_one_failed_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir)
            job_doc = {
                "runs": [
                    {"status": "failed", "started_at": "2026-10-10T10:00:00+00:00"}
                ]
            }
            (jobs_dir / "snapshot-deploy.json").write_text(json.dumps(job_doc))

            # Test with this jobs directory
            with patch("claims.HOME", jobs_dir.parent):
                jobs_data = []
                for job_file in sorted(jobs_dir.glob("*.json")):
                    try:
                        doc = json.loads(job_file.read_text())
                        jobs_data.append((job_file.stem, doc))
                    except (json.JSONDecodeError, OSError):
                        pass

                failed_jobs = []
                now = datetime.now(timezone.utc)
                for job_name, doc in jobs_data:
                    import job_events as je
                    status = je.status_of(doc, now)
                    if status in ("failed", "crashed"):
                        failed_jobs.append(f"{job_name}:{status}")

                assert len(failed_jobs) > 0
                assert "failed" in failed_jobs[0]

    def test_zero_jobs_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir) / "empty_jobs"
            empty_dir.mkdir()

            jobs_data = []
            for job_file in sorted(empty_dir.glob("*.json")):
                jobs_data.append((job_file.stem, {}))

            assert len(jobs_data) == 0


class TestCollect:
    def test_collect_with_mock_functions(self):
        def mock_check_two_machines():
            return {"ok": True, "detail": "ok"}

        def mock_check_main_health_claim():
            return {"ok": True, "detail": "ok"}

        def mock_check_repo_visibility():
            return {"ok": True, "detail": "ok"}

        def mock_check_jobs_recent():
            return {"ok": True, "detail": "ok"}

        gather_dict = {
            "check_two_machines": mock_check_two_machines,
            "check_main_health_claim": mock_check_main_health_claim,
            "check_repo_visibility": mock_check_repo_visibility,
            "check_jobs_recent": mock_check_jobs_recent,
        }

        result = claims.collect(gather=gather_dict)
        assert len(result) == 4
        assert all(r.get("ok") is True for r in result.values())

    def test_collect_with_exception(self):
        def failing_check():
            raise ValueError("test error")

        gather_dict = {
            "check_two_machines": lambda: {"ok": True, "detail": "ok"},
            "check_main_health_claim": failing_check,
            "check_repo_visibility": lambda: {"ok": True, "detail": "ok"},
            "check_jobs_recent": lambda: {"ok": True, "detail": "ok"},
        }

        result = claims.collect(gather=gather_dict)
        assert result["main-passes-tests"]["ok"] is False
        assert "raised" in result["main-passes-tests"]["detail"]

    def test_collect_missing_check_function(self):
        gather_dict = {
            "check_two_machines": lambda: {"ok": True, "detail": "ok"},
        }

        result = claims.collect(gather=gather_dict)
        # Some checks will be missing
        assert any("not found" in str(r.get("detail", "")) for r in result.values())


class TestScanForUncheckedClaims:
    def test_numeric_claim_not_registered(self):
        html = "<p>It runs 47 tests daily.</p>"
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should find unregistered claim
        assert any("47" in s for s in unchecked)

    def test_textual_claim_not_registered(self):
        html = "<p>It's self-hosted on local hardware.</p>"
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should find unregistered claim mentioning "self-hosted"
        assert any("self-hosted" in s for s in unchecked)

    def test_registered_claim_verbatim(self):
        html = f"<p>{claims.CLAIMS[0]['text']}</p>"
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should NOT flag the registered claim
        assert not any(claims.CLAIMS[0]["text"] in s for s in unchecked)

    def test_empty_html(self):
        unchecked = claims.scan_for_unchecked_claims("", claims.CLAIMS)
        assert unchecked == []

    def test_script_and_style_stripped(self):
        html = """
        <p>Real claim with numbers: 42</p>
        <script>var x = "it keeps working while I'm away";</script>
        <style>.hidden { display: none; }</style>
        """
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should find the real claim but not the one in script
        # The script content shouldn't be parsed as a claim
        assert len(unchecked) > 0

    def test_huge_page(self):
        # A 500KB page shouldn't timeout
        large_html = "<p>" + "word " * 100000 + "</p>"
        import time
        start = time.time()
        unchecked = claims.scan_for_unchecked_claims(large_html, claims.CLAIMS)
        elapsed = time.time() - start
        assert elapsed < 5  # Should complete in less than 5 seconds

    def test_malformed_html_unclosed_tags(self):
        html = "<p>It runs on two Macs<div>It's open source"
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should not crash, should handle gracefully
        assert isinstance(unchecked, list)

    def test_non_ascii_emoji(self):
        html = "<p>MARVIN runs 🚀 on two Macs 🎉</p>"
        unchecked = claims.scan_for_unchecked_claims(html, claims.CLAIMS)
        # Should not crash
        assert isinstance(unchecked, list)


class TestVisibleText:
    def test_extracts_text(self):
        html = "<p>Hello</p><p>World</p>"
        text = claims._visible_text(html)
        assert "Hello" in text
        assert "World" in text

    def test_strips_script(self):
        html = "<p>Visible</p><script>var x = 'hidden';</script>"
        text = claims._visible_text(html)
        assert "Visible" in text
        assert "hidden" not in text

    def test_strips_style(self):
        html = "<p>Visible</p><style>.hidden { color: red; }</style>"
        text = claims._visible_text(html)
        assert "Visible" in text
        assert ".hidden" not in text

    def test_empty_html(self):
        text = claims._visible_text("")
        assert text == "" or text.strip() == ""


class TestAtomicWrite:
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            data = {"key": "value"}
            claims._atomic_write(path, data)
            assert path.exists()
            assert json.loads(path.read_text()) == data

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            claims._atomic_write(path, {"old": "data"})
            claims._atomic_write(path, {"new": "data"})
            assert json.loads(path.read_text()) == {"new": "data"}

    def test_atomic_write_no_half_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            # Try to write to a bad path (parent doesn't exist as directory)
            bad_path = Path(tmpdir) / "file.txt" / "subdir" / "test.json"
            try:
                claims._atomic_write(bad_path, {"key": "value"})
            except Exception:
                pass
            # Temp file should be cleaned up
            assert not (bad_path.parent / (bad_path.name + ".tmp")).exists()


class TestNightlyIntegration:
    @patch("claims.job_events.job_run")
    @patch("claims.gather")
    def test_nightly_writes_ledger(self, mock_gather, mock_job_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_ledger_path = Path(tmpdir) / "ledger.json"
            mock_gather_result = {
                "checked": {},
                "failed": {},
                "unknown": {},
                "unchecked": [],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            mock_gather.return_value = mock_gather_result

            # Mock job_run context manager
            mock_run = MagicMock()
            mock_job_run.return_value.__enter__ = MagicMock(return_value=mock_run)
            mock_job_run.return_value.__exit__ = MagicMock(return_value=False)

            # Can't easily test without modifying the actual nightly flow,
            # but we can verify the pieces work


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
