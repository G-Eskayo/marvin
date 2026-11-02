"""Public profile parity (lib/profile_parity.py, marvin#1038): one facts file, every surface checked against it.

These tests try to break the check: stale counts, the senior title beside the current employer, a banned name inside a
real PDF, a surface that can't be reached, a private value that must never be printed. The people and companies here are
made up; the owner's real facts live only in the private instance repo.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import profile_parity as pp  # noqa: E402

FACTS = {
    "schema": 1,
    "facts": {
        "current_title": {"value": "Jr Data Engineer", "source": "owner", "decided": "2026-11-02"},
        "merit_badges": {"value": 27, "source": "court of honor record", "decided": "2026-11-02"},
        "palms": {"value": 2, "source": "court of honor record", "decided": "2026-11-02"},
        "phone": {"value": None, "visibility": "private-never-public", "source": "owner", "decided": "2026-11-02"},
    },
    "rules": [
        {"id": "employer-title", "field": "current title at Acme", "kind": "title_near", "near": "Acme",
         "title": r"(?:Jr\.? |Junior |Senior )?Data Engineer", "allowed": ["Jr Data Engineer"], "window": 60},
        {"id": "no-globex", "field": "former contract (Globex)", "kind": "forbid", "pattern": "Globex", "public_only": True},
        {"id": "no-phone", "field": "phone number", "kind": "forbid", "private": True, "public_only": True,
         "pattern": r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"},
        {"id": "palms", "field": "Eagle Palms", "kind": "count", "fact": "palms",
         "pattern": r"\b(\w+) Eagle Palms?\b"},
        {"id": "badges", "field": "merit badges", "kind": "count", "fact": "merit_badges",
         "pattern": r"\b(\w+) merit badges\b"},
        {"id": "decisions", "field": "decision records", "kind": "count", "op": "min", "expected": 80,
         "pattern": r"\b(\d+)\+? decision records\b"},
        {"id": "clearance", "field": "security clearance", "kind": "forbid", "status": "unconfirmed", "public_only": True,
         "pattern": r"(?i)\b(?:active|secret)\b[^.\n]{0,30}\bclearance\b"},
        {"id": "bio-headline", "field": "headline", "kind": "require", "surfaces": ["gh"], "fields": ["bio"],
         "patterns": ["Data Engineer", "Widget"]},
    ],
}


def _surface(id_="site", public=True, **kw):
    return {"id": id_, "label": id_, "kind": "text", "public": public, **kw}


def _fields(rows):
    return {(r["surface"], r["field"]) for r in rows}


# ── rules on text ───────────────────────────────────────────────────────────────────────────────────────────────

def test_clean_text_has_no_findings():
    text = "Jr Data Engineer at Acme. Eagle Scout: 27 merit badges and two Eagle Palms. 82 decision records."
    assert pp.evaluate(FACTS, _surface(), {"page": text}) == []


def test_a_stale_count_names_the_field_and_both_values():
    rows = pp.evaluate(FACTS, _surface(), {"page": "Eagle Scout with 22 merit badges and 3 Eagle Palms."})
    by = {r["field"]: r for r in rows}
    assert by["merit badges"]["was"] == "22" and by["merit badges"]["want"] == "27"
    assert by["Eagle Palms"]["was"] == "3" and by["Eagle Palms"]["want"] == "2"


def test_count_words_are_read_as_numbers():
    assert pp.evaluate(FACTS, _surface(), {"page": "two Eagle Palms"}) == []
    assert pp.evaluate(FACTS, _surface(), {"page": "Three Eagle Palms"})[0]["was"] == "3"


def test_a_count_that_is_not_a_number_is_not_silently_passed():
    # "several Eagle Palms" can't be compared: it is reported, not skipped
    rows = pp.evaluate(FACTS, _surface(), {"page": "several Eagle Palms"})
    assert rows and rows[0]["field"] == "Eagle Palms" and rows[0]["was"] == "several"


def test_a_minimum_count_accepts_more_and_refuses_fewer():
    assert pp.evaluate(FACTS, _surface(), {"p": "80+ decision records"}) == []
    assert pp.evaluate(FACTS, _surface(), {"p": "91 decision records"}) == []
    assert pp.evaluate(FACTS, _surface(), {"p": "60 decision records"})[0]["want"] == "80 or more"


@pytest.mark.parametrize("text", [
    "Data Engineer at Acme Corp since April",
    "### Acme Corp | Data Engineer | April 2026",
    "Acme (Data Engineer)",
    "Senior Data Engineer, Acme",
])
def test_the_senior_title_beside_the_current_employer_is_a_mismatch(text):
    rows = pp.evaluate(FACTS, _surface(), {"page": text})
    assert [r["field"] for r in rows] == ["current title at Acme"]
    assert rows[0]["want"] == "Jr Data Engineer"


@pytest.mark.parametrize("text", [
    "Jr Data Engineer at Acme Corp",
    "Acme Corp | Jr. Data Engineer",
    "Junior data engineer? No: Jr Data Engineer, Acme",
])
def test_the_real_title_beside_the_employer_passes(text):
    assert pp.evaluate(FACTS, _surface(), {"page": text}) == []


def test_a_headline_title_right_before_the_real_one_is_not_paired_with_the_employer():
    # what PDF text extraction gives for a resume header: the headline, then the summary line
    assert pp.evaluate(FACTS, _surface(), {"pdf": "U.S. veteran DATA ENGINEER Jr Data Engineer at Acme Corp: pipelines"}) == []


def test_the_title_on_the_far_side_of_the_employer_still_counts():
    rows = pp.evaluate(FACTS, _surface(), {"p": "Jr Data Engineer, Acme | Data Engineer since 2026"})
    assert [r["was"] for r in rows] == ["Data Engineer"]


def test_a_case_sensitive_rule_ignores_a_heading_number():
    facts = {"facts": {"n": {"value": 33}}, "rules": [
        {"id": "s", "field": "skills", "kind": "count", "fact": "n", "case_sensitive": True, "pattern": r"\b(\d+) skills\b"}]}
    assert pp.evaluate(facts, _surface(), {"p": "03 Skills, loaded on demand. 33 skills in the repo."}) == []
    assert pp.evaluate(facts, _surface(), {"p": "32 skills"})[0]["was"] == "32"


def test_except_lets_a_dated_history_line_through():
    facts = {"facts": {"n": {"value": 33}}, "rules": [
        {"id": "s", "field": "skills", "kind": "count", "fact": "n", "pattern": r"\b(\d+) skills\b", "except": r"it said \d+ skills"}]}
    assert pp.evaluate(facts, _surface(), {"p": "on 2026-11-02 it said 32 skills and the index check failed"}) == []
    assert pp.evaluate(facts, _surface(), {"p": "MARVIN has 32 skills"})


def test_the_same_banned_word_in_two_cases_is_one_finding():
    rows = pp.evaluate(FACTS, _surface(), {"p": "globex and Globex and GLOBEX"})
    assert len(rows) == 1


def test_the_aspirational_title_far_from_the_employer_is_fine():
    text = "Data Engineer | pipelines and evaluation" + " filler" * 30 + " Day job: Jr Data Engineer, Acme."
    assert pp.evaluate(FACTS, _surface(), {"page": text}) == []


def test_a_banned_name_is_found_in_any_case_of_spacing_inside_its_field():
    rows = pp.evaluate(FACTS, _surface(), {"about": "I used to contract for Globex on evals."})
    assert rows[0]["field"] == "former contract (Globex)" and "Globex" in rows[0]["was"]
    assert rows[0]["where"] == "about"


def test_public_only_rules_skip_a_private_surface():
    text = "Globex contract. Call (555) 010-4477."
    assert pp.evaluate(FACTS, _surface(public=False), {"master": text}) == []
    assert len(pp.evaluate(FACTS, _surface(public=True), {"page": text})) == 2


def test_a_private_value_is_never_printed():
    rows = pp.evaluate(FACTS, _surface(), {"page": "Reach me at 555-010-4477 or (555) 010 4477 anytime."})
    assert rows and rows[0]["field"] == "phone number"
    dumped = json.dumps(rows)
    assert "4477" not in dumped and "010" not in dumped
    assert "redacted" in rows[0]["was"]


def test_snippets_around_other_findings_redact_a_nearby_private_value():
    rows = pp.evaluate(FACTS, _surface(), {"page": "Globex 555-010-4477"})
    assert "4477" not in json.dumps(rows)


def test_an_unconfirmed_fact_is_a_question_not_a_plain_mismatch():
    rows = pp.evaluate(FACTS, _surface(), {"page": "Veteran with an Active Security Clearance."})
    assert rows[0]["kind"] == "question" and rows[0]["field"] == "security clearance"


def test_a_required_phrase_only_applies_to_its_surface_and_field():
    gh = _surface("gh")
    rows = pp.evaluate(FACTS, gh, {"bio": "Student | Eagle Scout", "repo:x": "no headline here"})
    assert len(rows) == 2 and all(r["where"] == "bio" and r["was"] == "missing" for r in rows)
    assert {r["want"] for r in rows} == {"Data Engineer", "Widget"}
    assert pp.evaluate(FACTS, _surface("site"), {"bio": "Student"}) == []
    assert pp.evaluate(FACTS, gh, {"bio": "Data Engineer | Widget maker"}) == []


def test_html_is_read_as_the_text_a_visitor_sees():
    html = ("<html><head><style>.x{content:'Globex'}</style><script>var s='Globex'</script></head>"
            "<body><p>27 merit&nbsp;badges</p><p>and <b>two</b> Eagle\nPalms</p></body></html>")
    text = pp.html_text(html)
    assert "Globex" not in text and "27 merit badges" in text and "two Eagle Palms" in text


def test_a_rule_with_a_bad_pattern_is_reported_not_crashed():
    facts = {"facts": {}, "rules": [{"id": "bad", "field": "broken rule", "kind": "forbid", "pattern": "("}]}
    rows = pp.evaluate(facts, _surface(), {"page": "anything"})
    assert rows[0]["kind"] == "rule-error" and rows[0]["field"] == "broken rule"


def test_a_count_rule_pointing_at_a_missing_fact_is_a_rule_error():
    facts = {"facts": {}, "rules": [{"id": "c", "field": "things", "kind": "count", "fact": "nope", "pattern": r"(\d+) things"}]}
    assert pp.evaluate(facts, _surface(), {"p": "3 things"})[0]["kind"] == "rule-error"


# ── surfaces: unreachable is "couldn't check", never a pass ─────────────────────────────────────────────────────

def test_an_unreachable_site_is_couldnt_check_not_pass():
    facts = dict(FACTS, surfaces=[{"id": "site", "label": "Site", "kind": "url", "public": True,
                                   "urls": ["http://127.0.0.1:9/about/"]}])
    report = pp.run(facts, timeout=2)
    s = report["surfaces"][0]
    assert s["status"] == "couldnt_check" and "127.0.0.1" in s["why"]
    assert report["unchecked"] == 1 and report["mismatches"] == 0
    row = pp.health_row(report)
    assert row["severity"] != "green" and "couldn't check" in row["detail"]


def test_one_page_down_out_of_several_still_says_couldnt_check(tmp_path):
    good = tmp_path / "ok.html"
    good.write_text("<p>27 merit badges</p>")
    facts = dict(FACTS, surfaces=[{"id": "site", "label": "Site", "kind": "url", "public": True,
                                   "urls": [good.as_uri(), "http://127.0.0.1:9/gone/"]}])
    s = pp.run(facts, timeout=2)["surfaces"][0]
    assert s["status"] == "couldnt_check"


def test_a_missing_file_is_couldnt_check(tmp_path):
    facts = dict(FACTS, surfaces=[{"id": "m", "label": "Master", "kind": "file", "public": False,
                                   "path": str(tmp_path / "nope.md")}])
    assert pp.run(facts)["surfaces"][0]["status"] == "couldnt_check"


def test_an_unknown_surface_kind_is_couldnt_check():
    facts = dict(FACTS, surfaces=[{"id": "x", "label": "X", "kind": "carrier-pigeon"}])
    s = pp.run(facts)["surfaces"][0]
    assert s["status"] == "couldnt_check" and "carrier-pigeon" in s["why"]


def test_a_file_surface_expands_home_and_is_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "master.md").write_text("### Acme | Data Engineer | 2026\nGlobex (suppressed)\n")
    facts = dict(FACTS, surfaces=[{"id": "m", "label": "Master", "kind": "file", "public": False, "path": "~/master.md"}])
    report = pp.run(facts)
    assert report["surfaces"][0]["status"] == "checked"
    assert _fields(report["findings"]) == {("m", "current title at Acme")}


def _minimal_pdf(text: str) -> bytes:
    """A real one-page PDF whose only text is `text` (uncompressed, Helvetica), with a correct xref table."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


@pytest.mark.skipif(not pp.pdf_extractor(), reason="no PDF text extractor on this machine")
def test_a_banned_name_inside_a_real_pdf_is_found(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(_minimal_pdf("Contract work at Globex on model evals"))
    facts = dict(FACTS, surfaces=[{"id": "pdf", "label": "Resume PDF", "kind": "pdf", "public": True, "url": pdf.as_uri()}])
    report = pp.run(facts)
    assert report["surfaces"][0]["status"] == "checked"
    assert _fields(report["findings"]) == {("pdf", "former contract (Globex)")}


def test_a_file_that_is_not_a_pdf_is_couldnt_check(tmp_path):
    bad = tmp_path / "resume.pdf"
    bad.write_text("<html>404 Not Found</html>")
    facts = dict(FACTS, surfaces=[{"id": "pdf", "label": "Resume PDF", "kind": "pdf", "public": True, "url": bad.as_uri()}])
    assert pp.run(facts)["surfaces"][0]["status"] == "couldnt_check"


def test_git_surface_reads_the_first_ref_that_exists(tmp_path):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "site").mkdir()
    (repo / "site" / "about.html").write_text("<p>3 Eagle Palms</p>")
    (repo / "site" / "app.js").write_text("// 9 Eagle Palms in code is not copy")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
    facts = dict(FACTS, surfaces=[{"id": "g", "label": "Site source", "kind": "git", "public": True, "repo": str(repo),
                                   "refs": ["origin/gone-branch", "main"], "paths": ["site/*.html"]}])
    report = pp.run(facts)
    s = report["surfaces"][0]
    assert s["status"] == "checked" and s["ref"] == "main"
    assert [(f["where"], f["was"]) for f in report["findings"]] == [("site/about.html", "3")]


def test_git_surface_with_no_ref_is_couldnt_check(tmp_path):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    facts = dict(FACTS, surfaces=[{"id": "g", "label": "Site source", "kind": "git", "public": True, "repo": str(repo),
                                   "refs": ["origin/nope"], "paths": ["*.html"]}])
    assert pp.run(facts)["surfaces"][0]["status"] == "couldnt_check"


def test_github_surface_turns_profile_pins_and_descriptions_into_fields():
    calls = []

    def fake_gh(args):
        calls.append(args)
        if args[:2] == ["api", "users/alex"]:
            return {"bio": "Student with an Active Security Clearance"}
        if args[0] == "api" and args[1] == "graphql":
            return {"data": {"user": {"pinnedItems": {"nodes": [{"name": "widget"}]}}}}
        return [{"name": "widget", "description": "27 merit badges, 3 Eagle Palms"}]

    facts = dict(FACTS, surfaces=[{"id": "gh", "label": "GitHub", "kind": "github", "public": True, "user": "alex"}])
    report = pp.run(facts, gh=fake_gh)
    assert report["surfaces"][0]["status"] == "checked"
    got = {(f["where"], f["field"]) for f in report["findings"]}
    assert ("bio", "security clearance") in got and ("repo widget", "Eagle Palms") in got
    assert ("bio", "headline") in got


def test_github_surface_that_fails_is_couldnt_check():
    def broken(args):
        raise RuntimeError("gh: rate limited")
    facts = dict(FACTS, surfaces=[{"id": "gh", "label": "GitHub", "kind": "github", "public": True, "user": "alex"}])
    s = pp.run(facts, gh=broken)["surfaces"][0]
    assert s["status"] == "couldnt_check" and "rate limited" in s["why"]


# ── facts file and the Health row ───────────────────────────────────────────────────────────────────────────────

def test_no_facts_file_means_not_configured(tmp_path):
    assert pp.load_facts(tmp_path / "missing.json") is None


def test_a_corrupt_facts_file_raises_so_the_row_says_why(tmp_path):
    bad = tmp_path / "public-profile.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError):
        pp.load_facts(bad)


def test_health_row_is_green_only_when_every_surface_was_checked_and_matched():
    ok = {"surfaces": [{"id": "a", "label": "A", "status": "checked"}], "findings": [], "mismatches": 0, "unchecked": 0}
    assert pp.health_row(ok)["severity"] == "green"


def test_health_row_names_surface_and_field_on_drift():
    rep = {"surfaces": [{"id": "site", "label": "Live site", "status": "checked"}],
           "findings": [{"surface": "site", "label": "Live site", "field": "Eagle Palms", "where": "/about-me/",
                         "was": "3", "want": "2", "kind": "mismatch"}], "mismatches": 1, "unchecked": 0}
    row = pp.health_row(rep)
    assert row["severity"] == "yellow" and "Live site" in row["detail"] and "Eagle Palms" in row["detail"]
    assert row["id"] == "profile:parity"


def test_health_row_with_nothing_checkable_is_unknown_not_green():
    rep = {"surfaces": [{"id": "a", "label": "A", "status": "couldnt_check", "why": "offline"}], "findings": [],
           "mismatches": 0, "unchecked": 1}
    assert pp.health_row(rep)["severity"] == "unknown"


def test_cached_report_is_reused_until_it_is_stale(tmp_path):
    facts_path = tmp_path / "public-profile.json"
    facts_path.write_text(json.dumps(dict(FACTS, surfaces=[])))
    cache = tmp_path / "profile-parity.json"
    runs = []

    def runner(facts, **kw):
        runs.append(1)
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "surfaces": [], "findings": [], "mismatches": 0, "unchecked": 0}

    pp.check(facts_path=facts_path, cache_path=cache, runner=runner)
    pp.check(facts_path=facts_path, cache_path=cache, runner=runner)
    assert len(runs) == 1
    old = json.loads(cache.read_text())
    old["report"]["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=pp.REFRESH_HOURS + 1)).isoformat()
    cache.write_text(json.dumps(old))
    pp.check(facts_path=facts_path, cache_path=cache, runner=runner)
    assert len(runs) == 2


def test_check_is_quiet_when_the_owner_has_no_facts_file(tmp_path):
    assert pp.check(facts_path=tmp_path / "none.json", cache_path=tmp_path / "c.json") is None


def test_check_reports_a_corrupt_facts_file_by_name(tmp_path):
    bad = tmp_path / "public-profile.json"
    bad.write_text("[]")
    row = pp.check(facts_path=bad, cache_path=tmp_path / "c.json")
    assert row["severity"] == "yellow" and "public-profile.json" in row["detail"]


def test_a_cache_written_from_older_facts_is_not_reused(tmp_path):
    facts_path = tmp_path / "public-profile.json"
    facts_path.write_text(json.dumps(dict(FACTS, surfaces=[])))
    cache = tmp_path / "c.json"
    runs = []

    def runner(facts, **kw):
        runs.append(1)
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "surfaces": [], "findings": [], "mismatches": 0, "unchecked": 0}

    pp.check(facts_path=facts_path, cache_path=cache, runner=runner)
    facts_path.write_text(json.dumps(dict(FACTS, surfaces=[], updated="2026-11-03")))
    pp.check(facts_path=facts_path, cache_path=cache, runner=runner)
    assert len(runs) == 2


def test_the_cli_never_prints_a_private_value(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<p>Call 555-010-4477</p>")
    facts_path = tmp_path / "public-profile.json"
    facts_path.write_text(json.dumps(dict(FACTS, surfaces=[{"id": "s", "label": "S", "kind": "url", "public": True,
                                                             "urls": [page.as_uri()]}])))
    out = subprocess.run([sys.executable, str(Path(pp.__file__)), "--facts", str(facts_path), "--no-cache", "--json"],
                         capture_output=True, text=True, timeout=60)
    assert "4477" not in out.stdout + out.stderr
    assert json.loads(out.stdout)["mismatches"] == 1
