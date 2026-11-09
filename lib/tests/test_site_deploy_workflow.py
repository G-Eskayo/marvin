"""The site workflow publishes only from main (marvin#1007): a pull request builds a preview and can never deploy.

Reads .github/workflows/site.yml as data, so a later edit that lets a PR (or any branch) reach the Pages deploy, drops
the Pages permissions, or unpins an action fails here instead of on the live domain.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "site.yml"


@pytest.fixture(scope="module")
def wf():
    data = yaml.safe_load(WF.read_text())
    data["on"] = data.get("on", data.get(True))  # YAML 1.1 reads a bare `on:` key as True
    return data


def _deploy(wf):
    jobs = wf["jobs"]
    deploying = [j for j in jobs.values() if any("deploy-pages" in str(s.get("uses", "")) for s in j.get("steps", []))]
    assert len(deploying) == 1, "exactly one job deploys to Pages"
    return deploying[0]


def test_deploy_runs_only_on_a_push_to_main(wf):
    cond = _deploy(wf).get("if", "")
    assert "github.event_name == 'push'" in cond and "github.ref == 'refs/heads/main'" in cond
    assert wf["on"]["push"]["branches"] == ["main"]


def test_pull_requests_still_build_but_never_deploy(wf):
    assert "pull_request" in wf["on"]
    build = wf["jobs"]["build"]
    assert "if" not in build, "the build (and its checks) runs on every PR"
    assert not any("deploy-pages" in str(s.get("uses", "")) for s in build["steps"])


def test_only_the_deploy_job_can_write_pages(wf):
    assert wf.get("permissions") == {"contents": "read"}
    perms = _deploy(wf).get("permissions", {})
    assert perms.get("pages") == "write" and perms.get("id-token") == "write"
    assert _deploy(wf).get("environment", {}).get("name") == "github-pages"


def test_deploys_never_cancel_each_other_mid_publish(wf):
    c = _deploy(wf).get("concurrency", {})
    assert c.get("group") == "pages" and c.get("cancel-in-progress") is False


def test_every_action_is_pinned_to_a_version(wf):
    for job in wf["jobs"].values():
        for s in job.get("steps", []):
            if "uses" in s:
                assert "@v" in s["uses"] or "@" in s["uses"] and len(s["uses"].split("@")[1]) == 40, s["uses"]


def test_the_pages_artifact_is_the_built_site(wf):
    up = [s for s in wf["jobs"]["build"]["steps"] if "upload-pages-artifact" in str(s.get("uses", ""))]
    assert len(up) == 1 and up[0]["with"]["path"] == "site/dist"
    assert "push" in up[0].get("if", "") and "refs/heads/main" in up[0]["if"]
