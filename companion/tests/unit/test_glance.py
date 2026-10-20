"""At-a-glance discovery heads: direction from the effect's sign, never a judgement."""

from __future__ import annotations

from app.glance import card, icon_for, likely_range
from app.models import FeatureDef, Insight


def _insight(**kw) -> Insight:
    base = dict(kind="association", feature_a="sleep.total_h", feature_b="tracker.coffee.total", lag=0, effect=-0.4)
    return Insight(**(base | dict(strength="strong", details={}) | kw))


DEFS = {
    "sleep.total_h": FeatureDef(feature="sleep.total_h", label="Sleep (total)", family="sleep"),
    "tracker.coffee.total": FeatureDef(feature="tracker.coffee.total", label="Coffee", family="tracker:coffee"),
}


def test_association_reads_as_two_arrows():
    c = card(_insight(), DEFS)
    assert (c.a.label, c.a.icon, c.a.arrow) == ("Sleep (total)", "moon", "up")
    assert (c.b.label, c.b.icon, c.b.arrow, c.link, c.dots) == ("Coffee", "pencil", "down", "opposite", 3)
    together = card(_insight(effect=0.3, lag=1, strength="weak"), DEFS)
    assert (together.b.arrow, together.link, together.next_day, together.dots) == ("up", "together", True, 1)


def test_change_and_weekday():
    change = card(_insight(kind="change", feature_b=None, effect=0.5, details={"pct": -12.0}), DEFS)
    assert (change.a.arrow, change.b, change.link) == ("down", None, "lately")
    weekday = card(_insight(kind="weekday", feature_b=None, details={"high": 1, "low": 6}), DEFS)
    assert (weekday.a.arrow, weekday.link) == (None, "highest Tue, lowest Sun")


def test_icons_by_feature_then_family():
    assert icon_for("tracker.day_tags.tag.travel") == "tag"
    assert icon_for("hl.resting_heart_rate", "vital") == "heart"
    assert icon_for("something.new") == "dot"


def test_day_tags_keep_their_colour_and_show_as_pills():
    from app.glance import tag_colours

    tags = tag_colours(["meeting heavy", "Travel", *[f"t{k}" for k in range(7)]])
    assert tags["meeting_heavy"] == ("meeting heavy", 0) and tags["travel"] == ("Travel", 1)
    assert tags["t6"][1] == 0  # eight colours, then they repeat
    c = card(_insight(feature_a="tracker.day_tags.tag.travel", effect=-0.3, strength="moderate"), DEFS, tags)
    assert (c.a.label, c.a.colour, c.a.arrow) == ("Travel", 1, "up") and c.b.colour is None


def test_likely_range_marks_where_no_effect_sits():
    r = likely_range(_insight(effect=-0.4, details={"ci": [-0.62, -0.18]}))
    assert r.lo_x < r.est_x < r.hi_x < r.zero_x == 100.0
    assert r.clear and r.text == "−0.62 to −0.18 (0 is no link)"
    unclear = likely_range(_insight(effect=0.3, details={"ci": [-0.05, 0.55]}))
    assert unclear.lo_x < unclear.zero_x < unclear.hi_x and not unclear.clear


def test_change_range_is_in_percent_and_old_runs_have_none():
    r = likely_range(_insight(kind="change", feature_b=None, details={"pct": 20.0, "pct_ci": [8.0, 31.0]}))
    assert r.text == "+8% to +31% (0 is no change)" and r.zero_x == 100.0
    assert likely_range(_insight(details={})) is None
    assert likely_range(_insight(kind="weekday", feature_b=None, details={"high": 1, "low": 6})) is None


def test_adjusted_recheck_in_words():
    from app.glance import adjusted

    adj = {"for": ["sleep.total_h", "hl.step_count"], "rho": -0.31, "ci": [-0.52, -0.08], "verdict": "holds"}
    a = adjusted(_insight(details={"adjusted": adj}))
    assert a.text == "still holds allowing for sleep and steps" and a.range.clear
    weaker = adjusted(_insight(details={"adjusted": adj | {"verdict": "weaker", "ci": [-0.4, 0.1]}}))
    assert weaker.text == "weaker once sleep and steps are allowed for" and not weaker.range.clear
    one = adjusted(_insight(details={"adjusted": adj | {"for": ["sleep.total_h"], "verdict": "explained"}}))
    assert one.text == "largely accounted for by sleep"
    assert adjusted(_insight(details={})) is None
