"""Owner decisions waiting on MARVIN (marvin#607): tests try to break it."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import owner_decisions as od

REPO = "G-Eskayo/marvin"
T0 = datetime(2026, 10, 22, 5, 4, 28, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def decisions(answers=None, raw_json=None, cid=1001, at=T0, author="G-Eskayo"):
    block = raw_json if raw_json is not None else json.dumps({"answers": answers or {"overview": {"choices": ["c"], "note": ""}}})
    body = (f"{od.HEADING}\n\n- **Which overview?** c\n\n<details><summary>machine-readable</summary>\n\n"
            f"```marvin-decisions\n{block}\n```\n</details>")
    return {"databaseId": cid, "url": f"https://github.com/{REPO}/pull/577#issuecomment-{cid}", "createdAt": iso(at),
            "body": body, "author": {"login": author}}


def comment(body, at, author="G-Eskayo", cid=2002):
    return {"databaseId": cid, "url": "u", "createdAt": iso(at), "body": body, "author": {"login": author}}


def pr(comments, last_commit=T0 - timedelta(minutes=10), number=577, repo=REPO):
    return {"repo": repo, "number": number, "title": "Vitals design v3", "url": f"https://github.com/{repo}/pull/{number}",
            "headRefName": "design/vitals", "last_commit_at": iso(last_commit) if last_commit else None,
            "comments": comments}


QUESTION = {"notes": {"text": "Do you think this is a good way to visualize this system? Is there better ways"}}


# ── status ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_commit_alone_is_not_an_answer_the_owner_can_see():
    # marvin #733: on clarity-captions #155 a fix landed as a commit and the owner couldn't tell whether the screenshots
    # were redone. Only a reply saying what changed counts; the commit is recorded so the follow-up can say so.
    s = od.pr_status(pr([decisions()], last_commit=T0 + timedelta(hours=1)), T0 + timedelta(hours=10), 4)
    assert s["addressed_by"] is None and s["overdue"] and s["committed_since"]
    marked = comment(f"Done.\n{od.ADDRESSED_MARKER}", T0 + timedelta(hours=2))
    s = od.pr_status(pr([decisions(), marked], last_commit=T0 + timedelta(hours=1)), T0 + timedelta(hours=10), 4)
    assert s["addressed_by"] == "reply" and not s["overdue"]


def test_decisions_then_nothing_is_flagged_only_after_n_hours():
    p = pr([decisions()])
    assert not od.pr_status(p, T0 + timedelta(hours=3, minutes=59), 4)["overdue"]
    assert od.pr_status(p, T0 + timedelta(hours=4), 4)["overdue"]  # exactly N hours counts


def test_a_commit_dated_before_the_comment_does_not_count():
    s = od.pr_status(pr([decisions()], last_commit=T0 - timedelta(seconds=1)), T0 + timedelta(hours=5), 4)
    assert s["overdue"] and s["addressed_by"] is None


def test_a_plain_later_owner_comment_is_not_an_answer_but_a_marked_reply_is():
    plain = comment("## Owner idea: bring Activity into Vitals", T0 + timedelta(hours=1))
    assert od.pr_status(pr([decisions(), plain]), T0 + timedelta(hours=5), 4)["overdue"]
    marked = comment(f"Answers below.\n{od.ADDRESSED_MARKER}", T0 + timedelta(hours=1))
    assert od.pr_status(pr([decisions(), marked]), T0 + timedelta(hours=5), 4)["addressed_by"] == "reply"


def test_a_non_owner_cannot_post_decisions_or_silence_them():
    assert od.pr_status(pr([decisions(author="drive-by")]), T0 + timedelta(hours=9), 4) is None
    fake_ack = comment(od.ADDRESSED_MARKER, T0 + timedelta(hours=1), author="drive-by")
    assert od.pr_status(pr([decisions(), fake_ack]), T0 + timedelta(hours=9), 4)["overdue"]


def test_owner_login_case_does_not_matter():
    assert od.pr_status(pr([decisions(author="g-eskayo")]), T0 + timedelta(hours=9), 4)["overdue"]


def test_newer_decisions_after_a_commit_start_the_clock_again():
    later = T0 + timedelta(hours=6)
    p = pr([decisions(), decisions(cid=1002, at=later)], last_commit=T0 + timedelta(hours=1))
    s = od.pr_status(p, later + timedelta(hours=5), 4)
    assert s["comment_id"] == 1002 and s["overdue"]


def test_a_completed_follow_up_for_that_comment_counts_as_acted_on():
    s = od.pr_status(pr([decisions()]), T0 + timedelta(hours=9), 4, completed_comments={1001})
    assert s["addressed_by"] == "follow-up" and not s["overdue"]


def test_garbage_comments_never_crash():
    junk = [None, {}, {"createdAt": "not a date", "body": od.HEADING}, {"createdAt": iso(T0), "body": None,
            "author": None}, decisions()]
    assert od.pr_status(pr(junk), T0 + timedelta(hours=9), 4)["overdue"]
    assert od.pr_status({"comments": None}, T0, 4) is None


# ── parsing and question detection ─────────────────────────────────────────────────────────────────────────────

def test_question_is_detected_in_notes_and_text_answers():
    assert od.parse_decisions_comment(decisions(QUESTION)["body"])["question"]
    assert od.parse_decisions_comment(decisions({"a": {"choices": ["x"], "note": "why not both?"}})["body"])["question"]


def test_a_question_without_a_question_mark_still_counts():
    assert od.has_question(["I like it. Is there a better way to show this in 3D"])


def test_no_question_in_plain_answers_urls_or_code():
    assert not od.parse_decisions_comment(decisions({"a": {"choices": ["Medium"], "note": "Go with medium."}})["body"])["question"]
    assert not od.has_question(["See https://example.com/x?y=1 and `a ? b : c`", "It is there.", "", None, 5])


def test_malformed_json_still_counts_and_reads_the_prose():
    p = od.parse_decisions_comment(decisions(raw_json="{not json")["body"])
    assert p["malformed"] and not p["question"]
    asked = od.HEADING + "\n\n- **Anything else?** Should we add a brain view\n\n```marvin-decisions\n[1,2\n```"
    assert od.parse_decisions_comment(asked)["question"]
    assert od.parse_decisions_comment(od.HEADING + "\n- answers, no block")["malformed"]
    assert od.parse_decisions_comment(decisions(raw_json='{"answers": "x"}')["body"])["malformed"]


def test_only_a_decisions_record_is_parsed():
    assert od.parse_decisions_comment("Decisions from the owner were great") is None
    assert od.parse_decisions_comment(None) is None


def test_grace_hours_is_configurable_and_rejects_nonsense():
    assert od.grace_hours({}) == od.DEFAULT_GRACE_HOURS
    assert od.grace_hours({"MARVIN_DECISIONS_GRACE_HOURS": "12"}) == 12
    for bad in ("0", "-3", "abc", "1e9", "nan"):
        assert od.grace_hours({"MARVIN_DECISIONS_GRACE_HOURS": bad}) == od.DEFAULT_GRACE_HOURS


# ── GitHub: a fake gh that behaves like the real one (shared state across "Macs") ──────────────────────────────

class FakeGitHub:
    def __init__(self, prs, issues=None, fail=()):
        self.prs, self.issues, self.fail, self.calls = prs, issues or [], set(fail), []
        self.next_number = 900

    def node(self, p):
        return {"number": p["number"], "title": p["title"], "url": p["url"], "headRefName": p["headRefName"],
                "repository": {"nameWithOwner": p["repo"]},
                "commits": {"nodes": [{"commit": {"committedDate": p["last_commit_at"]}}] if p["last_commit_at"] else []},
                "comments": {"nodes": p["comments"]}}

    def __call__(self, cmd, **kw):
        args = cmd[1:]
        self.calls.append(args[:2])
        kind = " ".join(args[:2])
        if kind in self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        if kind == "api graphql":
            fu = [{"number": i["number"], "title": i["title"], "url": "", "state": i["state"],
                   "stateReason": i.get("stateReason"), "body": i["body"], "repository": {"nameWithOwner": i["repo"]}}
                  for i in self.issues]
            data = {"prs": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [self.node(p) for p in self.prs]},
                    "followups": {"nodes": fu}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": data}), "")
        if kind == "issue list":
            repo = args[args.index("--repo") + 1]
            rows = [{"number": i["number"], "state": i["state"], "body": i["body"]} for i in self.issues if i["repo"] == repo]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")
        if kind == "issue create":
            repo = args[args.index("--repo") + 1]
            body = open(args[args.index("--body-file") + 1]).read()
            self.next_number += 1
            labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            self.issues.append({"repo": repo, "number": self.next_number, "title": args[args.index("--title") + 1],
                                "state": "OPEN", "body": body, "labels": labels})
            return subprocess.CompletedProcess(cmd, 0, f"https://github.com/{repo}/issues/{self.next_number}\n", "")
        if kind == "issue close":
            n = int(args[2])
            for i in self.issues:
                if i["number"] == n:
                    i["state"] = "CLOSED"
                    i["stateReason"] = "NOT_PLANNED" if "not planned" in args else "COMPLETED"
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def open_followups(self):
        return [i for i in self.issues if i["state"] == "OPEN"]


LATE = T0 + timedelta(hours=5)


def test_overdue_decisions_file_one_ready_for_agent_follow_up_linked_to_the_pr():
    gh = FakeGitHub([pr([decisions(QUESTION)])])
    r = od.sync([REPO], now=LATE, run=gh, grace=4)
    [fu] = gh.open_followups()
    assert fu["title"] == "Act on owner decisions on PR #577"
    assert {"ready-for-agent", od.FOLLOWUP_LABEL}.issubset(fu["labels"])
    assert "https://github.com/G-Eskayo/marvin/pull/577" in fu["body"] and "issuecomment-1001" in fu["body"]
    assert "owner asked a question" in fu["body"] and od.followup_marker(fu["body"])["question"]
    assert "## What to build" in fu["body"] and "- [ ]" in fu["body"] and "## How we'll try to break it" in fu["body"]
    assert r["filed"][0]["result"].startswith("filed")


def test_a_commit_without_a_reply_files_a_follow_up_that_asks_for_the_reply():
    gh = FakeGitHub([pr([decisions()], last_commit=T0 + timedelta(minutes=30))])
    od.sync([REPO], now=LATE, run=gh, grace=4)
    body = gh.issues[0]["body"]
    assert "already has commits" in body and "what changed" in body.lower() and "screenshots" in body.lower()


def test_the_follow_up_asks_whether_screenshots_were_retaken_and_pinned():
    gh = FakeGitHub([pr([decisions()])])
    od.sync([REPO], now=LATE, run=gh, grace=4)
    body = gh.issues[0]["body"].lower()
    assert "screenshots" in body and "pinned" in body and "why not" in body


def test_not_yet_overdue_files_nothing():
    gh = FakeGitHub([pr([decisions()])])
    od.sync([REPO], now=T0 + timedelta(hours=1), run=gh, grace=4)
    assert gh.issues == []


def test_repeated_scans_file_once():
    gh = FakeGitHub([pr([decisions()])])
    for _ in range(3):
        od.sync([REPO], now=LATE, run=gh, grace=4)
    assert len(gh.issues) == 1


def test_two_macs_racing_end_with_exactly_one_open_follow_up():
    gh = FakeGitHub([pr([decisions()])])
    # Both Macs read GitHub before either files: simulate by filing twice from the same stale view.
    sts = od.statuses(od.fetch([REPO], gh), LATE, 4)
    od._file(sts[0], gh, False)
    gh.issues.append({**gh.issues[0], "number": 950})   # the other Mac's create landed too
    od._dedupe(REPO, 1001, gh)
    assert [i["number"] for i in gh.open_followups()] == [901]


def test_a_follow_up_closed_as_done_is_never_refiled_for_the_same_comment():
    gh = FakeGitHub([pr([decisions()])])
    od.sync([REPO], now=LATE, run=gh, grace=4)
    gh.issues[0].update(state="CLOSED", stateReason="NOT_PLANNED")
    od.sync([REPO], now=LATE + timedelta(hours=3), run=gh, grace=4)
    assert len(gh.issues) == 1


def test_follow_up_closes_itself_when_the_reply_lands_not_on_a_bare_commit():
    p = pr([decisions()])
    gh = FakeGitHub([p])
    od.sync([REPO], now=LATE, run=gh, grace=4)
    p["last_commit_at"] = iso(LATE + timedelta(minutes=5))
    od.sync([REPO], now=LATE + timedelta(hours=1), run=gh, grace=4)
    assert len(gh.open_followups()) == 1
    p["comments"].append(comment(f"Changed X; screenshots retaken.\n{od.ADDRESSED_MARKER}", LATE + timedelta(minutes=10)))
    r = od.sync([REPO], now=LATE + timedelta(hours=2), run=gh, grace=4)
    assert gh.open_followups() == [] and "addressed" in r["closed"][0]["why"]


def test_follow_up_closes_when_the_pr_closes_but_not_when_the_list_was_cut_short():
    gh = FakeGitHub([pr([decisions()])])
    od.sync([REPO], now=LATE, run=gh, grace=4)
    gh.prs = []
    orig = gh.__call__
    # A truncated PR list must not close anything.
    def truncated(cmd, **kw):
        out = orig(cmd, **kw)
        if cmd[1:3] == ["api", "graphql"]:
            d = json.loads(out.stdout)
            d["data"]["prs"]["pageInfo"] = {"hasNextPage": True, "endCursor": "x"}
            out = subprocess.CompletedProcess(cmd, 0, json.dumps(d), "")
        return out
    od.sync([REPO], now=LATE, run=truncated, grace=4)
    assert len(gh.open_followups()) == 1
    od.sync([REPO], now=LATE, run=gh, grace=4)
    assert gh.open_followups() == []


def test_github_failing_files_and_closes_nothing():
    gh = FakeGitHub([pr([decisions()])], fail={"api graphql"})
    r = od.sync([REPO], now=LATE, run=gh, grace=4)
    assert not r["ok"] and gh.issues == []
    gh = FakeGitHub([pr([decisions()])], fail={"issue list"})
    r = od.sync([REPO], now=LATE, run=gh, grace=4)
    assert gh.issues == [] and "could not list" in r["filed"][0]["result"]


def test_dry_run_writes_nothing():
    gh = FakeGitHub([pr([decisions()])])
    r = od.sync([REPO], now=LATE, run=gh, grace=4, dry_run=True)
    assert gh.issues == [] and r["filed"][0]["result"] == "would file"


def test_unregistered_repos_are_ignored_and_one_call_reads_everything():
    gh = FakeGitHub([pr([decisions()], repo="someone/else"), pr([decisions()], number=12)])
    r = od.sync([REPO], now=T0 + timedelta(hours=1), run=gh, grace=4)
    assert [s["number"] for s in r["waiting"]] == [12]
    assert gh.calls == [["api", "graphql"]]


def test_waiting_lists_decided_prs_of_any_age():
    gh = FakeGitHub([pr([decisions()]), pr([], number=12)])
    rows = od.waiting([REPO], now=T0 + timedelta(minutes=5), run=gh)
    assert [r["number"] for r in rows] == [577]


def test_the_scan_step_never_breaks_dispatch(monkeypatch):
    import ticket_pipeline
    monkeypatch.setattr(od, "_registered_repos", lambda: [REPO])
    monkeypatch.setattr(od, "sync", lambda repos: (_ for _ in ()).throw(RuntimeError("kaboom")))
    assert ticket_pipeline._owner_decisions().startswith("skipped (kaboom")
    monkeypatch.setattr(od, "sync", lambda repos: {"ok": True, "filed": [{"repo": REPO, "pr": 577, "result": "filed x"}],
                                                   "closed": [], "waiting": [1]})
    assert ticket_pipeline._owner_decisions() == "1 PR(s) waiting on MARVIN; marvin PR #577: filed x"


# ── the real gh, outside any git repo (launchd runs the hourly scan from /) ──────────────────────────────────────

def test_the_search_reaches_github_from_outside_a_git_repo(tmp_path):
    """-F treats "q=…label:owner-decisions sort:updated-desc…" as a magic value and runs git to resolve it; from /
    (where launchd starts the scan) that fails in 36 ms before any request, so every hourly scan read nothing.
    The real gh, pointed at a closed port with a throwaway HOME, must get as far as the network."""
    import shutil
    import pytest
    gh = shutil.which("gh", path="/opt/homebrew/bin:/usr/local/bin")  # past conftest's stub; never reaches GitHub
    if not gh:
        pytest.skip("gh not installed")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "GH_HOST": "127.0.0.1:1", "GH_ENTERPRISE_TOKEN": "x",
           "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)}
    seen = []

    def real(cmd, **kw):
        r = subprocess.run([gh, *cmd[1:]], capture_output=True, text=True, timeout=30, cwd=tmp_path, env=env)
        seen.append(r.stdout + r.stderr)
        return r

    od.fetch([REPO, "G-Eskayo/clarity-captions"], real)
    assert seen and "error parsing" not in seen[0] and "not a git repository" not in seen[0], seen[0]
    assert "127.0.0.1:1" in seen[0], seen[0]
