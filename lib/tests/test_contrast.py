"""marvin#1062: every MARVIN colour pair is measured against the accessibility rule (Gil, 2026-11-03)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contrast as cx  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# ── colours and the formula ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,rgb", [("#f0b32a", (240, 179, 42)), ("#F0B32A", (240, 179, 42)), ("#fff", (255, 255, 255)),
                                      ("rgb(5, 4, 10)", (5, 4, 10)), ("rgba(5,4,10,0.2)", (5, 4, 10))])
def test_colours_parse(text, rgb):
    assert cx.parse(text)[:3] == rgb


def test_rgba_keeps_its_alpha():
    assert cx.parse("rgba(5,4,10,0.25)")[3] == pytest.approx(0.25)
    assert cx.parse("#05040A")[3] == 1.0


@pytest.mark.parametrize("bad", ["", "f0b32a", "#f0b32", "#ggg", "rgb(300,0,0)", "rgba(1,2,3,1.5)", "red", None, 12])
def test_malformed_colours_are_refused(bad):
    with pytest.raises(ValueError):
        cx.parse(bad)


def test_known_ratios_match_wcag():
    assert cx.ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert cx.ratio("#000000", "#000000") == pytest.approx(1.0)
    assert round(cx.ratio("#f0b32a", "#05040A"), 1) == 10.9
    assert round(cx.ratio("#6b551f", "#05040A"), 1) == 2.9
    assert cx.ratio("#05040A", "#f0b32a") == cx.ratio("#f0b32a", "#05040A")   # order doesn't matter


def test_glass_is_composited_over_its_backdrop():
    # 60% MARVIN black over a white window: the background the text really sits on
    bg = cx.over("#05040A", 0.6, "#ffffff")
    assert bg == pytest.approx((105, 104.4, 108), abs=0.5)
    assert cx.ratio("#f0b32a", bg) < 4.5


def test_opacity_out_of_range_is_refused():
    with pytest.raises(ValueError):
        cx.over("#000", 1.2, "#fff")


# ── checking a palette ──────────────────────────────────────────────────────────────────────

def _spec(**over):
    s = {"name": "t", "levels": {"text": 4.5, "pixel": 7.0},
         "pairs": [{"what": "main text", "fg": "#f0b32a", "bg": "#05040A", "level": "pixel"}]}
    s.update(over)
    return s


def test_a_passing_palette_passes():
    r = cx.check(_spec())
    assert r["ok"] and r["results"][0]["ratio"] == pytest.approx(10.9, abs=0.05)


def test_a_pair_below_its_level_fails_with_a_clear_message():
    r = cx.check(_spec(pairs=[{"what": "secondary text", "fg": "#6b551f", "bg": "#05040A", "level": "text"}]))
    assert not r["ok"]
    assert "secondary text" in r["failures"][0] and "2.9" in r["failures"][0] and "4.5" in r["failures"][0]


def test_exactly_at_the_threshold_passes_and_just_under_fails():
    passing = cx.check(_spec(levels={"x": 21.0}, pairs=[{"what": "a", "fg": "#fff", "bg": "#000", "level": "x"}]))
    failing = cx.check(_spec(levels={"x": 21.0001}, pairs=[{"what": "a", "fg": "#fff", "bg": "#000", "level": "x"}]))
    assert passing["ok"] and not failing["ok"]


def test_a_glass_pair_is_measured_over_its_backdrop():
    r = cx.check(_spec(pairs=[{"what": "glass", "fg": "#f0b32a", "bg": "#05040A", "opacity": 0.6, "backdrop": "#ffffff",
                               "level": "text"}]))
    assert not r["ok"]


def test_an_exception_is_reported_not_failed_but_needs_a_reason():
    ok = cx.check(_spec(pairs=[{"what": "glass", "fg": "#f0b32a", "bg": "#05040A", "opacity": 0.3, "backdrop": "#fff",
                                "level": "text", "exception": "Gil chose 30% unfocused (2026-11-03)"}]))
    assert ok["ok"] and ok["exceptions"] and "Gil chose" in ok["exceptions"][0]
    bad = cx.check(_spec(pairs=[{"what": "glass", "fg": "#f0b32a", "bg": "#05040A", "opacity": 0.3, "backdrop": "#fff",
                                 "level": "text", "exception": "  "}]))
    assert not bad["ok"]


def test_an_exception_on_a_pair_that_passes_is_flagged_as_stale():
    r = cx.check(_spec(pairs=[{"what": "fine", "fg": "#fff", "bg": "#000", "level": "text", "exception": "old"}]))
    assert not r["ok"] and "no longer needed" in r["failures"][0]


@pytest.mark.parametrize("pair", [{"fg": "#fff", "bg": "#000", "level": "nope", "what": "a"},
                                  {"fg": "#fff", "level": "text", "what": "a"},
                                  {"fg": "bogus", "bg": "#000", "level": "text", "what": "a"},
                                  {"fg": "#fff", "bg": "#000", "level": "text"}])
def test_a_malformed_pair_fails_the_check_rather_than_being_skipped(pair):
    r = cx.check(_spec(pairs=[pair]))
    assert not r["ok"]


def test_the_same_pair_listed_twice_with_different_levels_is_refused():
    p = {"what": "a", "fg": "#f0b32a", "bg": "#05040A"}
    r = cx.check(_spec(pairs=[{**p, "level": "text"}, {**p, "level": "pixel", "what": "b"}]))
    assert not r["ok"] and "twice" in r["failures"][0]


def test_the_cli_exits_non_zero_on_a_failure(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(_spec(pairs=[{"what": "dim", "fg": "#6b551f", "bg": "#05040A", "level": "text"}])))
    assert cx.main(["check", str(f)]) == 1
    assert "dim" in capsys.readouterr().out
    f.write_text("{not json")
    assert cx.main(["check", str(f)]) == 1


# ── MARVIN's own palettes pass (this is what keeps the rule from depending on memory) ───────

def test_every_marvin_palette_meets_the_rule():
    palettes = sorted((REPO / "config" / "palette").glob("*.json"))
    assert palettes, "no palettes declared"
    for f in palettes:
        r = cx.check(json.loads(f.read_text()))
        assert r["ok"], f"{f.name}: " + "; ".join(r["failures"])
