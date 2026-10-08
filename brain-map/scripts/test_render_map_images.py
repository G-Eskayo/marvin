#!/usr/bin/env python3
"""render_map_images.py crop maths: the card and hero come from the same box, so they always match."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from render_map_images import CARD, HERO, card_box, hero_box  # noqa: E402


def test_card_box_hugs_the_nodes_at_8_by_5():
    nodes = [{"sx": 1000, "sy": 500}, {"sx": 1400, "sy": 900}]
    l, t, r, b = card_box(nodes, frame=(2200, 1375), pad=0)
    assert abs((r - l) / (b - t) - CARD[0] / CARD[1]) < 1e-9
    assert l <= 1000 and r >= 1400 and t <= 500 and b >= 900
    assert (r - l) < 2200 * 0.5  # cropped in, not the whole frame


def test_card_box_stays_inside_the_frame():
    l, t, r, b = card_box([{"sx": 5, "sy": 5}, {"sx": 2195, "sy": 1370}], frame=(2200, 1375))
    assert l >= 0 and t >= 0 and r <= 2200 and b <= 1375


def test_hero_is_a_band_of_the_card_centred_on_marvin():
    box = (100, 100, 900, 600)
    l, t, r, b = hero_box(box, centre_y=350)
    assert (l, r) == (100, 900)
    assert abs((r - l) / (b - t) - HERO[0] / HERO[1]) < 1e-9
    assert abs((t + b) / 2 - 350) < 1e-9
    assert hero_box(box, centre_y=110)[1] == 100  # pinned inside the card box
