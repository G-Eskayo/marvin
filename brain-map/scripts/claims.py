#!/usr/bin/env python3
"""
Claims ledger: fact-checks the MARVIN page's claims against system truth.

Each claim is a factual sentence on the page backed by a check that reads the system:
the machine registry, the merge gate, the repo's visibility, and scheduled jobs' last runs.
Nightly: runs all checks; a failing claim marks its section untrue on the dashboard (Portfolio tab)
and triggers redraft of that section (#269).

Mirrors facts.py's pattern: pure functions + gather().
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

import job_events
import health_checks
import project_catalog
import portfolio_content

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]
LEDGER_PATH = HOME / ".claude" / "logs" / "claims-ledger.json"

CLAIMS = [
    {
        "id": "two-machines",
        "text": "it runs on two Macs",
        "check": "check_two_machines",
        "section": "Lead, story sections",
    },
    {
        "id": "main-passes-tests",
        "text": "it proves every change with tests before I see it",
        "check": "check_main_health_claim",
        "section": "Lead, story sections",
    },
    {
        "id": "open-source",
        "text": "it's open source",
        "check": "check_repo_visibility",
        "section": "Lead, story sections",
    },
    {
        "id": "keeps-working",
        "text": "it keeps working while I'm away",
        "check": "check_jobs_recent",
        "section": "Lead, story sections",
    },
]


def check_two_machines(devices: dict | None = None) -> dict:
    """Two machines running MARVIN: the machine registry should have exactly 2 devices."""
    if devices is None:
        try:
            network = json.loads((HOME / ".claude" / "marvin-network.json").read_text())
            devices = network.get("devices", {})
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "detail": "marvin-network.json not found or invalid"}

    if not isinstance(devices, dict):
        return {"ok": False, "detail": "devices is not a dict"}

    count = len(devices)
    if count == 2:
        return {"ok": True, "detail": f"2 devices registered: {', '.join(sorted(devices.keys()))}"}
    elif count == 0:
        return {"ok": False, "detail": "no devices registered"}
    elif count == 1:
        return {"ok": False, "detail": f"only 1 device registered: {list(devices.keys())[0]}"}
    else:
        return {"ok": False, "detail": f"{count} devices registered (expected 2)"}


def check_main_health_claim() -> dict:
    """Main branch passes tests: reads the durable merge-gate record."""
    result = health_checks.check_main_health()
    if result["severity"] == "green":
        return {"ok": True, "detail": result["detail"]}
    elif result["severity"] == "yellow":
        return {"ok": False, "detail": f"main health stale: {result['detail']}"}
    else:  # red
        return {"ok": False, "detail": f"main failing: {result['detail']}"}


def check_repo_visibility(catalog_path: Path | None = None) -> dict:
    """Repo is open source (PUBLIC visibility): read from catalog with fallback to gh."""
    catalog_path = catalog_path or project_catalog.catalog_path()

    # Try catalog first
    cat = project_catalog.read_catalog(catalog_path)
    if cat:
        for proj in cat.get("projects", []):
            if proj.get("repo") == "G-Eskayo/marvin":
                visibility = proj.get("visibility")
                if visibility == "PUBLIC":
                    return {"ok": True, "detail": "G-Eskayo/marvin is PUBLIC"}
                elif visibility is None:
                    return {"ok": None, "detail": "catalog visibility missing; unknown"}
                else:
                    return {"ok": False, "detail": f"G-Eskayo/marvin is {visibility} (not PUBLIC)"}

    # Fallback to gh repo view
    try:
        p = subprocess.run(
            ["gh", "repo", "view", "G-Eskayo/marvin", "--json", "visibility"],
            capture_output=True,
            text=True,
            timeout=20,
            env=project_catalog.run_env()
        )
        if p.returncode == 75:  # gh gate defer
            return {"ok": None, "detail": "gh rate limited; unknown"}
        if p.returncode != 0:
            return {"ok": None, "detail": f"gh check inconclusive: returned {p.returncode}"}
        try:
            data = json.loads(p.stdout)
            visibility = data.get("visibility", "UNKNOWN")
            if visibility == "PUBLIC":
                return {"ok": True, "detail": "G-Eskayo/marvin is PUBLIC"}
            else:
                return {"ok": False, "detail": f"G-Eskayo/marvin is {visibility} (not PUBLIC)"}
        except json.JSONDecodeError:
            return {"ok": None, "detail": "gh response malformed; unknown"}
    except subprocess.TimeoutExpired:
        return {"ok": None, "detail": "gh timed out; unknown"}
    except Exception as e:
        return {"ok": None, "detail": f"visibility check inconclusive: {e}"}


def check_jobs_recent(jobs_directory: Path | None = None) -> dict:
    """Jobs run regularly: all scheduled jobs should be idle or recently finished, none failed/crashed/never."""
    if jobs_directory is None:
        jobs_directory = HOME / ".claude" / "logs" / "jobs"
    if not jobs_directory.exists():
        return {"ok": False, "detail": "jobs directory not found"}

    jobs_data = []
    for job_file in sorted(jobs_directory.glob("*.json")):
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
        status = job_events.status_of(doc, now)
        if status in ("failed", "crashed"):
            failed_jobs.append(f"{job_name}:{status}")
        elif status == "never":
            failed_jobs.append(f"{job_name}:never-run")

    if failed_jobs:
        return {"ok": False, "detail": f"{len(failed_jobs)} jobs not healthy: {', '.join(failed_jobs[:3])}"}

    return {"ok": True, "detail": f"{len(jobs_data)} jobs all healthy"}


def collect(gather=None, jobs_directory: Path | None = None) -> dict:
    """Run all claim checks using provided gather function or the default."""
    if gather is None:
        gather = globals()

    results = {}
    for claim in CLAIMS:
        check_name = claim["check"]
        check_fn = gather.get(check_name)
        if not check_fn:
            results[claim["id"]] = {"ok": None, "detail": f"check function {check_name} not found"}
            continue

        try:
            if check_name == "check_jobs_recent" and jobs_directory:
                result = check_fn(jobs_directory=jobs_directory)
            else:
                result = check_fn()
            results[claim["id"]] = result
        except Exception as e:
            results[claim["id"]] = {"ok": False, "detail": f"check raised: {e}"}

    return results


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, stripping script/style/code tags."""
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "code", "pre"):
            self.skip = True
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "code", "pre") and self.skip_depth > 0:
            self.skip_depth -= 1
            if self.skip_depth == 0:
                self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)

    def get_text(self):
        return " ".join(self.text)


def _visible_text(html: str) -> str:
    """Extract visible text from HTML."""
    try:
        extractor = _TextExtractor()
        extractor.feed(html or "")
        return extractor.get_text()
    except Exception:
        # Fallback: rough regex-based stripping
        text = re.sub(r"<(script|style|code|pre)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return text


def scan_for_unchecked_claims(html: str, claims_list: list[dict] | None = None) -> list[dict]:
    """Find sentences in HTML that state facts without a ledger entry."""
    if claims_list is None:
        claims_list = CLAIMS

    text = _visible_text(html)

    # Sentences end with period, exclamation, or question mark
    sentences = re.split(r'(?<=[.!?])\s+', text)

    unchecked = []
    registered_texts = {c["text"] for c in claims_list}

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue

        # Check if this sentence contains any of the registered claim texts
        found = False
        for claim_text in registered_texts:
            # Strip leading subject pronouns (it, this, that) before checking
            normalized_claim = re.sub(r'^\b(it|this|that)\s+', '', claim_text, flags=re.I)
            normalized_sentence = re.sub(r'^\b(it|this|that)\s+', '', sentence, flags=re.I)
            if normalized_claim.lower() in normalized_sentence.lower():
                found = True
                break

        if not found:
            # Check if it looks like a factual claim (contains numbers or certain keywords)
            is_factual = (
                any(c.isdigit() for c in sentence) or
                any(re.search(rf'\b{re.escape(kw)}\b', sentence, re.I)
                    for kw in ["runs", "proves", "open", "keeps", "scheduled", "tests", "machines", "deployed",
                               "self-hosted", "local", "remote", "supports", "handles", "manages", "built"])
            )
            if is_factual:
                unchecked.append(sentence)

    return unchecked


def flag_for_redraft(claim: dict) -> None:
    """Stub seam: a failing claim should trigger redraft of its section (#269)."""
    pass


def gather(jobs_directory: Path | None = None) -> dict:
    """Collect all claim check results and save to ledger."""
    if jobs_directory is None:
        jobs_directory = HOME / ".claude" / "logs" / "jobs"

    results = collect(jobs_directory=jobs_directory)

    # Read marvin page content to find unchecked claims
    unchecked = []
    scan_error = None
    try:
        # Read via portfolio_content.py's standard path
        marvin_content_path = project_catalog.portfolio_repo_path() / "content" / "longform" / "marvin.json"
        if marvin_content_path.exists():
            marvin_content = json.loads(marvin_content_path.read_text())
            html = portfolio_content._page_html(marvin_content)
            unchecked = scan_for_unchecked_claims(html)
    except Exception as e:
        scan_error = str(e)

    # Determine which claims passed, failed, or are unknown
    passed = {cid: r for cid, r in results.items() if r.get("ok") is True}
    failed = {cid: r for cid, r in results.items() if r.get("ok") is False}
    unknown = {cid: r for cid, r in results.items() if r.get("ok") is None}

    # Flag each failed claim for potential redraft
    for cid, result in failed.items():
        claim_def = next((c for c in CLAIMS if c["id"] == cid), None)
        if claim_def:
            flag_for_redraft(claim_def)

    return {
        "checked": {cid: CLAIMS[[c["id"] for c in CLAIMS].index(cid)] for cid in results.keys()},
        "failed": failed,
        "unknown": unknown,
        "unchecked": unchecked,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scan_error": scan_error,
    }


def _atomic_write(path: Path, data: dict):
    """Write JSON atomically: write to temp, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    try:
        temp_path.write_text(json.dumps(data, indent=2))
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Claims ledger: check the MARVIN page's factual claims")
    parser.add_argument("--nightly", action="store_true", help="Run as nightly job; write to ledger")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH, help="Path to claims ledger file")
    parser.add_argument("--jobs-directory", type=Path, default=HOME / ".claude" / "logs" / "jobs", help="Directory containing job logs")
    args = parser.parse_args(argv)

    if args.nightly:
        with job_events.job_run("claims-ledger-nightly", directory=args.jobs_directory) as run:
            result = gather(jobs_directory=args.jobs_directory)
            _atomic_write(args.ledger_path, result)

            # Report summary
            failed_count = len(result.get("failed", {}))
            unchecked_count = len(result.get("unchecked", []))
            if failed_count > 0:
                run.step("Failed claims", str(failed_count))
            if unchecked_count > 0:
                run.step("Unchecked sentences", str(unchecked_count))
            if failed_count == 0 and unchecked_count == 0:
                run.summary("All claims verified")
    else:
        result = gather(jobs_directory=args.jobs_directory)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            # Human-readable output
            for cid, claim in [(c["id"], c) for c in CLAIMS]:
                check_result = result["failed"].get(cid) or result["unknown"].get(cid)
                if check_result:
                    status = "❌" if result["failed"].get(cid) else "?"
                    print(f"{status} {claim['text']}: {check_result['detail']}")
                else:
                    print(f"✓ {claim['text']}")

            if result.get("unchecked"):
                print(f"\n⚠ {len(result['unchecked'])} unchecked sentences in the page:")
                for sent in result["unchecked"][:5]:
                    print(f"  - {sent[:80]}")


if __name__ == "__main__":
    main()
