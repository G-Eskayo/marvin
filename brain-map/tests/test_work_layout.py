#!/usr/bin/env python3
"""The Body and Work layout (#854, mock-up behind ?layout=work): today's branches regrouped into the Vitals regions
(Body), and one node per project with its workers (Work). Nothing on today's map may vanish in the regrouping, the
default tree must come out unchanged, and the scheduled jobs move from Autonomous Agents to the projects they serve.
Run: python -m pytest brain-map/tests/test_work_layout.py -v"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate as g  # noqa: E402
import work_view as wv  # noqa: E402

VITALS_REGIONS = ["Pipeline", "GitHub", "Code & tests", "Skills & tools", "Code sync", "Producers", "Energy", "Body"]
ENRICHMENT = json.loads(g.ENRICHMENT_PATH.read_text(encoding="utf-8"))


def leaf(i, cat, **kw):
    return {"id": i, "cat": cat, "desc": "", "children": [], "expandable": False, "expanded": True, **kw}


def today():
    """A small tree shaped like generate.build_tree's: the same trunk ids, a few nodes under each."""
    return {"id": "MARVIN", "cat": "root", "desc": "", "expandable": False, "expanded": True, "children": [
        {**leaf("Memory", "memory"), "children": [leaf("lexicon.md", "memory")]},
        {**leaf("Skills", "skills-trunk"), "children": [
            {**leaf("Quality", "quality"), "children": [leaf("tdd", "quality", path="skills/tdd", openable=True,
                                                             code={"files": [{"id": "f1", "source_file": "skills/tdd/x.py"}]})]}]},
        {**leaf("Infrastructure", "infra"), "children": [leaf("skill_activity.py", "infra")]},
        {**leaf("Autonomous Agents", "agents"), "children": [leaf("usage-scan", "agents", path="lib/usage_report.py",
                                                                    openable=True)]},
        {**leaf("Cross-Machine Network", "cross-machine"), "children": [leaf("laptop-1", "cross-machine"),
                                                                       leaf("task-dispatch", "cross-machine")]},
        {**leaf("Dashboard", "dashboard"), "children": [leaf("Vitals tab", "dashboard")]},
        {**leaf("Projects", "projects"), "children": [leaf("seal", "projects"), leaf("project:tdd", "projects", name="tdd")]},
    ]}


def work_doc(workers=(), projects=None):
    projects = projects if projects is not None else [
        {"id": "marvin", "name": "marvin", "repo": "o/marvin", "paths": [], "desc": ""},
        {"id": "seal", "name": "seal", "repo": "o/seal", "paths": [], "desc": ""},
        {"id": "tdd", "name": "tdd", "repo": "o/tdd", "paths": [], "desc": ""}]
    return {"projects": projects, "workers": list(workers)}


JOB = {"id": "job:usage-scan", "name": "usage-scan", "kind": "job", "state": "idle", "project": "marvin", "desc": "",
       "path": "lib/usage_report.py"}


def ids(node, out=None):
    out = [] if out is None else out
    out.append(node["id"])
    for c in node.get("children", []):
        ids(c, out)
    return out


def find(node, nid):
    if node["id"] == nid:
        return node
    for c in node.get("children", []):
        hit = find(c, nid)
        if hit:
            return hit
    return None


def body_and_work(tree=None, doc=None):
    root, _syn = g.build_work_tree(tree or today(), ENRICHMENT, doc or work_doc([JOB]), [])
    body, work = root["children"]
    return root, body, work


def test_the_two_halves_are_body_then_work():
    root, body, work = body_and_work()
    assert root["id"] == "MARVIN"
    assert (body["name"], work["name"]) == ("Body", "Work")


def test_body_is_grouped_by_the_vitals_regions_with_their_names():
    _root, body, _work = body_and_work()
    assert [r["name"] for r in body["children"]] == VITALS_REGIONS


def test_every_region_colour_is_an_existing_palette_colour():
    template = g.TEMPLATE_PATH.read_text(encoding="utf-8")
    root, _b, _w = body_and_work()
    for key, spec in root["catColors"].items():
        assert f'\n    {spec["colorFrom"]}:' in template or f'"{spec["colorFrom"]}":' in template, (key, spec)


def test_nothing_on_todays_map_vanishes_except_the_trunks_work_replaces():
    tree = today()
    root, body, work = body_and_work(tree)
    gone = {"Projects", "Autonomous Agents"}
    before = [i for i in ids(tree) if i not in gone and i != "MARVIN"]
    in_body = ids(body)
    for i in before:
        if find(tree, "Projects") and find(find(tree, "Projects"), i):
            continue  # projects reappear in Work
        if find(find(tree, "Autonomous Agents"), i):
            continue  # jobs reappear in Work as workers
        assert in_body.count(i) == 1, i


def test_projects_reappear_in_work_with_todays_ids_so_their_threads_still_land():
    _root, _body, work = body_and_work()
    names = {c["projectId"]: c["id"] for c in work["children"] if c["id"] != wv.UNASSIGNED}
    assert names["seal"] == "seal"
    assert names["tdd"] == "project:tdd"  # shares its name with a skill, the same rule as today's Projects trunk


def test_jobs_leave_autonomous_agents_and_go_under_the_project_they_serve():
    _root, body, work = body_and_work()
    assert find(body, "usage-scan") is None and find(body, "Autonomous Agents") is None
    marvin = next(c for c in work["children"] if c["projectId"] == "marvin")
    job = find(marvin, "job:usage-scan")
    assert job and job["codeFrom"] == "usage-scan" and job["path"] == "lib/usage_report.py"


def test_the_job_machinery_stays_in_the_body():
    _root, body, _work = body_and_work()
    producers = next(r for r in body["children"] if r["name"] == "Producers")
    assert find(producers, "task-dispatch")


def test_a_branch_no_region_claims_goes_to_the_default_region_never_dropped():
    tree = today()
    tree["children"].insert(0, {**leaf("Brand New Trunk", "other"), "children": [leaf("thing", "other")]})
    _root, body, _work = body_and_work(tree)
    default = next(r for r in body["children"] if r["name"] == ENRICHMENT["body_regions"]["default"])
    assert find(default, "Brand New Trunk") and find(default, "thing")


def test_body_nodes_take_their_regions_colour():
    _root, body, _work = body_and_work()
    region = next(r for r in body["children"] if find(r, "tdd"))
    assert find(region, "tdd")["cat"] == region["cat"]


def test_code_layers_are_not_copied_into_the_work_tree():
    _root, body, _work = body_and_work()
    assert "code" not in find(body, "tdd")


def test_the_default_tree_comes_out_unchanged():
    tree = today()
    before = copy.deepcopy(tree)
    body_and_work(tree)
    assert tree == before


def test_every_id_in_the_work_tree_is_unique():
    workers = [JOB] + [{"id": f"helper:a{i}", "name": "tdd", "kind": "helper", "state": "running", "project": "seal",
                        "desc": ""} for i in range(30)]
    root, _b, _w = body_and_work(doc=work_doc(workers))
    all_ids = ids(root)
    assert len(all_ids) == len(set(all_ids))


def test_zero_projects_leaves_work_with_only_unassigned():
    _root, _body, work = body_and_work(doc=work_doc([JOB], projects=[]))
    assert [c["id"] for c in work["children"]] == [wv.UNASSIGNED]
    assert find(work, "job:usage-scan")


def test_threads_follow_a_job_to_its_worker_and_drop_only_what_is_not_on_the_map():
    syn = [{"a": "usage-scan", "b": "laptop-1", "type": "runs-on"}, {"a": "tdd", "b": "project:tdd", "type": "skill-project"},
           {"a": "tdd", "b": "Projects", "type": "calls"}]
    _root, out = g.build_work_tree(today(), ENRICHMENT, work_doc([JOB]), syn)
    assert {"a": "job:usage-scan", "b": "laptop-1", "type": "runs-on"} in out
    assert {"a": "tdd", "b": "project:tdd", "type": "skill-project"} in out
    assert len(out) == 2


def test_every_node_gets_a_precomputed_position():
    root, _b, _w = body_and_work()

    def walk(n):
        assert len(n["pos"]) == 3, n["id"]
        for c in n["children"]:
            walk(c)
    walk(root)


@pytest.mark.parametrize("n", [0, 42])
def test_zero_and_forty_two_projects_lay_out(n):
    projects = [{"id": f"p{i}", "name": f"p{i}", "repo": "", "paths": [], "desc": ""} for i in range(n)]
    _root, _body, work = body_and_work(doc=work_doc([JOB], projects=projects))
    assert len(work["children"]) == n + 1


def test_body_sits_left_of_the_root_and_work_right():
    _root, body, work = body_and_work()
    assert body["pos"][0] < 0 < work["pos"][0]


def test_the_two_halves_extent_is_centred_on_the_view():
    root, _b, _w = body_and_work()
    xs = []

    def walk(n):
        if n is not root:
            xs.append(n["pos"][0])
        for c in n["children"]:
            walk(c)
    walk(root)
    assert abs((min(xs) + max(xs)) / 2) < 1
