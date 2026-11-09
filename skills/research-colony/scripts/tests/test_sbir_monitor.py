"""SBIR/STTR topic monitor (#1165): DSIP topics scored against a capability profile, new matches told once.

The fake DSIP below has the real API's shape (captured 2026-11-09): /topics/api/public/topics/search pages of
{"total", "data": [...]} and /topics/api/public/topics/{id}/details with objective, description and keywords.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import sbir_monitor as sm  # noqa: E402

DAY_MS = 86_400_000
T0 = 1_793_000_000_000  # 2026-10-26, a fixed clock for the fake topics


def topic(n, title, status="Pre-Release", component="ARMY", program="SBIR", start=T0, end=T0 + 30 * DAY_MS):
    return {"topicId": f"id{n}", "topicCode": f"A27-{n:03d}", "topicTitle": title, "topicStatus": status,
            "component": component, "program": program, "solicitationTitle": "DoW SBIR 2027 BAA",
            "cycleName": "DOD_SBIR_2027_P1_CBZ", "topicPreReleaseStartDate": start - 28 * DAY_MS,
            "topicPreReleaseEndDate": start, "topicStartDate": start, "topicEndDate": end,
            "topicQAEndDate": end - 14 * DAY_MS, "cmmcLevel": "Level 1 (Self)"}


def details(n, objective="", description="", keywords="", itar=False):
    return {"topicId": f"id{n}", "objective": objective, "description": f"<p>{description}</p>",
            "keywords": keywords, "itar": itar, "cmmcLevel": "Level 1 (Self)",
            "phase1Description": "", "phase2Description": "", "phase3Description": ""}


class FakeDSIP:
    def __init__(self, topics, detail_map, page_size=2, fail=None):
        self.topics, self.detail_map, self.page_size, self.fail = topics, detail_map, page_size, fail
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if self.fail and self.fail in url:
            raise sm.SourceError(f"boom: {url}")
        if "/details" in url:
            tid = url.split("/details")[0].rsplit("/", 1)[1]
            return self.detail_map[tid]
        page = int(url.rsplit("page=", 1)[1].split("&")[0])
        chunk = self.topics[page * self.page_size:(page + 1) * self.page_size]
        return {"total": len(self.topics), "data": chunk}


PROFILE = {
    "name": "Seal Speak",
    "threshold": 6,
    "terms": {"speech recognition": 4, "speech-to-text": 4, "translation": 4, "caption": 3, "offline": 2,
              "android": 2, "atak": 4, "hearing": 3, "low-power": 1},
    "exclude": ["hypersonic"],
    "require_any": ["speech recognition", "speech-to-text", "translation", "caption", "hearing"],
}

TOPICS = [
    topic(1, "Offline Speech Translation for Dismounted Soldiers"),
    topic(2, "Integrated Multi-Spectral Periscope", component="NAVY"),
    topic(3, "Captioning for Hearing-Impaired Operators", status="Open"),
    topic(4, "Hypersonic speech translation telemetry"),
]
DETAILS = {
    "id1": details(1, objective="On-device speech recognition and translation on Android (ATAK).",
                   keywords="Speech-to-Text; Translation; ATAK; Offline"),
    "id2": details(2, objective="A ruggedized multi-spectral camera.", keywords="EO/IR; Night Vision"),
    "id3": details(3, description="Live caption display for operators with hearing loss.", keywords="Caption"),
    "id4": details(4, objective="Translation of telemetry for hypersonic tests."),
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "STATE_DIR", tmp_path / "state")
    told = []
    monkeypatch.setattr(sm, "tell", lambda title, msg, target=None: told.append((title, msg)))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(PROFILE))
    return {"told": told, "profile": profile, "tmp": tmp_path}


def run(env, dsip):
    return sm.run(profile_path=env["profile"], get_json=dsip, today="2026-11-11")


# ── scoring ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_matching_topic_scores_above_threshold_with_its_reasons():
    rec = sm.normalise(TOPICS[0], DETAILS["id1"])
    score, reasons = sm.score(rec, PROFILE)
    assert score >= PROFILE["threshold"]
    assert "atak" in reasons and "translation" in reasons


def test_an_unrelated_topic_scores_zero():
    assert sm.score(sm.normalise(TOPICS[1], DETAILS["id2"]), PROFILE)[0] == 0


def test_an_excluded_word_vetoes_the_topic_whatever_else_matches():
    score, reasons = sm.score(sm.normalise(TOPICS[3], DETAILS["id4"]), PROFILE)
    assert score == 0 and reasons == ["excluded: hypersonic"]


def test_terms_match_whole_words_case_insensitively_and_through_html():
    rec = sm.normalise(topic(9, "x"), details(9, description="<b>OFFLINE</b> use; offlineness; Translations"))
    _, reasons = sm.score(rec, PROFILE)
    assert "offline" in reasons and "translation" in reasons       # plural still counts; html stripped
    rec2 = sm.normalise(topic(9, "x"), details(9, description="captionless"))
    assert sm.score(rec2, PROFILE)[0] == 0                           # 'caption' inside another word doesn't


def test_a_title_hit_counts_double():
    title_only = sm.normalise(topic(9, "Android tooling"), details(9))
    body_only = sm.normalise(topic(9, "x"), details(9, description="android tooling"))
    assert sm.score(title_only, PROFILE)[0] == 2 * sm.score(body_only, PROFILE)[0]


def test_each_term_counts_once_per_field_so_repetition_cant_inflate_it():
    rec = sm.normalise(topic(9, "x"), details(9, description="translation " * 50))
    assert sm.score(rec, PROFILE)[0] == PROFILE["terms"]["translation"]


def test_dates_are_iso_and_the_record_keeps_what_a_proposal_needs():
    rec = sm.normalise(TOPICS[0], DETAILS["id1"])
    assert rec["code"] == "A27-001" and rec["component"] == "ARMY" and rec["program"] == "SBIR"
    assert rec["dates"]["opens"] == "2026-10-26" and rec["dates"]["closes"] == "2026-11-25"
    assert rec["cmmc"] == "Level 1 (Self)" and rec["itar"] is False
    assert "<p>" not in rec["text"]["description"]


# ── a run ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_run_pages_through_every_topic_and_tells_the_owner_once_about_new_matches(env):
    dsip = FakeDSIP(TOPICS, DETAILS)
    out = run(env, dsip)
    assert out["fetched"] == 4 and sorted(out["new_matches"]) == ["A27-001", "A27-003"]
    assert len(env["told"]) == 1                                     # one alert for the run, not one per topic
    title, msg = env["told"][0]
    assert "2 new" in title and "A27-001" in msg and "A27-003" in msg


def test_a_second_run_with_nothing_new_is_silent_and_fetches_no_details_again(env):
    run(env, FakeDSIP(TOPICS, DETAILS))
    dsip = FakeDSIP(TOPICS, DETAILS)
    out = run(env, dsip)
    assert out["new_matches"] == [] and len(env["told"]) == 1
    assert not any("/details" in c for c in dsip.calls)            # details are cached per topic


def test_a_matched_topic_opening_is_told_once_more(env):
    run(env, FakeDSIP(TOPICS, DETAILS))
    opened = [dict(t, topicStatus="Open") if t["topicId"] == "id1" else t for t in TOPICS]
    out = run(env, FakeDSIP(opened, DETAILS))
    assert out["now_open"] == ["A27-001"] and len(env["told"]) == 2
    out = run(env, FakeDSIP(opened, DETAILS))
    assert out["now_open"] == [] and len(env["told"]) == 2


def test_the_source_failing_is_reported_and_nothing_is_lost(env):
    run(env, FakeDSIP(TOPICS, DETAILS))
    before = (env["tmp"] / "state" / "topics.json").read_text()
    out = run(env, FakeDSIP(TOPICS, DETAILS, fail="search"))
    assert out["error"] and "boom" in out["error"]
    assert (env["tmp"] / "state" / "topics.json").read_text() == before   # state untouched
    assert "couldn't reach" in env["told"][-1][0].lower()


def test_one_topics_details_failing_skips_only_that_topic(env):
    dsip = FakeDSIP(TOPICS, DETAILS, fail="id3/details")
    out = run(env, dsip)
    assert out["new_matches"] == ["A27-001"] and out["skipped"] == ["A27-003"]
    out = run(env, FakeDSIP(TOPICS, DETAILS))                       # next run picks it up
    assert out["new_matches"] == ["A27-003"]


def test_an_empty_or_missing_profile_is_refused_before_any_fetch(env):
    dsip = FakeDSIP(TOPICS, DETAILS)
    for bad in ("", "{}", '{"terms": {}}', '{"terms": {"x": "high"}}', "not json"):
        env["profile"].write_text(bad)
        with pytest.raises(sm.ProfileError):
            run(env, dsip)
    with pytest.raises(sm.ProfileError):
        sm.run(profile_path=env["tmp"] / "missing.json", get_json=dsip, today="2026-11-11")
    assert dsip.calls == []


def test_a_garbled_page_is_a_source_error_not_a_crash(env):
    out = run(env, lambda url: {"unexpected": True})
    assert out["error"] and out["new_matches"] == []


def test_a_topic_without_dates_is_kept_with_dates_unknown(env):
    t = {k: v for k, v in TOPICS[0].items() if not k.endswith("Date")}
    rec = sm.normalise(t, DETAILS["id1"])
    assert rec["dates"]["closes"] is None


def test_the_raw_responses_are_cached_by_day(env):
    run(env, FakeDSIP(TOPICS, DETAILS))
    cached = json.loads((env["tmp"] / "state" / "raw" / "2026-11-11.json").read_text())
    assert len(cached["topics"]) == 4


def test_show_lists_matches_best_first_with_their_dates(env):
    run(env, FakeDSIP(TOPICS, DETAILS))
    table = sm.show()
    assert table.index("A27-001") < table.index("A27-003")         # the stronger match first
    assert "2026-11-25" in table and "A27-002" not in table


def test_supporting_words_alone_never_make_a_match():
    # Live run 2026-11-09: generic words (edge, offline, acoustic, noise) put 9 unrelated topics over the threshold,
    # a B-52 charts topic among them. A match needs at least one core capability term.
    rec = sm.normalise(topic(9, "Offline Android Low-Power ATAK Tool"),
                       details(9, objective="offline android atak low-power", keywords="Offline; Android; ATAK"))
    score, reasons = sm.score(rec, PROFILE)
    assert score >= PROFILE["threshold"]                           # high on supporting words...
    assert not sm.is_match(score, reasons, sm.load_profile_dict(PROFILE))   # ...but not a match


def test_one_core_term_plus_enough_score_is_a_match():
    rec = sm.normalise(topic(9, "Offline caption tool"), details(9, objective="android"))
    score, reasons = sm.score(rec, PROFILE)
    assert sm.is_match(score, reasons, sm.load_profile_dict(PROFILE))


def test_a_profile_without_require_any_matches_on_score_alone():
    prof = sm.load_profile_dict({k: v for k, v in PROFILE.items() if k != "require_any"})
    assert sm.is_match(PROFILE["threshold"], ["android"], prof)


def test_require_any_must_name_terms_the_profile_scores():
    with pytest.raises(sm.ProfileError):
        sm.load_profile_dict(dict(PROFILE, require_any=["sonar"]))
    with pytest.raises(sm.ProfileError):
        sm.load_profile_dict(dict(PROFILE, require_any="caption"))
