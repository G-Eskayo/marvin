"""The portfolio's site rules live in one module and everything reads it (lib/portfolio_rules.py)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_rules as pr  # noqa: E402
import portfolio_templates as pt  # noqa: E402
import portfolio_eval as ev  # noqa: E402


def test_overrides_merge_one_level_deep_over_the_defaults(tmp_path):
    f = tmp_path / "rules.json"
    f.write_text(json.dumps({"images": {"min_distance": 30}, "viewports": [1280]}))
    rules = pr.load_rules(f)
    assert rules["images"]["min_distance"] == 30 and rules["images"]["thumb_size"] == [800, 500]   # siblings kept
    assert rules["viewports"] == [1280]
    assert pr.load_rules(tmp_path / "missing.json") == pr.DEFAULT_RULES                           # no file -> defaults


def test_a_corrupt_or_non_object_rules_file_falls_back_to_the_defaults(tmp_path):
    f = tmp_path / "rules.json"
    f.write_text("{not json")
    assert pr.load_rules(f) == pr.DEFAULT_RULES
    f.write_text("[1, 2]")
    assert pr.load_rules(f) == pr.DEFAULT_RULES


def test_the_evaluation_uses_the_same_rules_object_not_its_own_copy():
    assert ev.DEFAULT_RULES is pr.DEFAULT_RULES
    assert ev.load_rules() == pr.load_rules()


def test_project_validation_follows_the_rules_not_a_hard_coded_list(tmp_path):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"categories": {"Cooking": "cooking"}, "project_spec": {"required": ["title", "slug", "category"], "slug_pattern": "[a-z]+"}}))
    spec = {"title": "T", "slug": "stew", "category": "Cooking", "subtitle": "s", "description": "d", "body_html": "<p/>", "stack_csv": "Python", "hero_image_url": "/h.jpg", "thumbnail": "/t.jpg"}
    out = pt.plan_new_project(spec, rules_path=rules)
    assert out["ok"] and out["url"] == "/cooking/stew/"                         # a category and slug shape that exist only in the rules file
    assert pt.plan_new_project({**spec, "slug": "has-hyphen"}, rules_path=rules)["ok"] is False
    assert pt.plan_new_project({**spec, "category": "Gaming"}, rules_path=rules)["ok"] is False           # unknown to the merged rules
    assert pt.plan_new_project({**spec, "category": "AI & Machine Learning"}, rules_path=rules)["ok"] is True   # defaults stay; overrides add


def test_no_consumer_keeps_its_own_copy_of_the_category_list():
    lib = Path(__file__).resolve().parent.parent
    for name in ("portfolio_add_project.py", "portfolio_apply.py", "portfolio_eval.py", "portfolio_imagegen.py"):
        assert '"ai-projects"' not in (lib / name).read_text().replace('"/ai-projects/"', ""), name
