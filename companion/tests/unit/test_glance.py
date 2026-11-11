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
    three = adj | {"labels": ["Sleep (total)", "Temperature (mean)", "HRV"], "for": ["a", "b", "c"]}
    assert adjusted(_insight(details={"adjusted": three})).text == (
        "still holds allowing for sleep (total), temperature (mean) and HRV"
    )
    assert adjusted(_insight(details={})) is None


def test_spread_link_reads_days_later_and_draws_its_curve():
    from app.glance import lag_bars

    i = _insight(
        method="distributed_lag",
        lag=3,
        effect=0.35,
        details={"curve": [0.0, 0.05, 0.2, 0.3, 0.2, 0.0, -0.05, 0.0], "peak": 3},
    )
    c = card(i, DEFS)
    assert (c.next_day, c.days_later, c.link) == (False, 3, "together")
    bars = lag_bars(i)
    assert len(bars) == 8 and [b.lag for b in bars if b.peak] == [3]
    assert bars[3].height == 26 and bars[3].up and not bars[6].up
    assert lag_bars(_insight()) == []


def _assoc(a: str, b: str) -> Insight:
    return _insight(feature_a=a, feature_b=b)


TAGS = {f"t{k}": (f"Tag {k}", k) for k in range(4)}
T = ["tracker.day_tags.tag.t0", "tracker.day_tags.tag.t1", "tracker.day_tags.tag.t2"]


def test_three_tags_around_one_series_clump():
    from app.glance import clumps

    found = clumps([_assoc(t, "sleep.total_h") for t in T], DEFS, TAGS)
    assert len(found) == 1 and len(found[0].tags) == 3 and found[0].links == 3


def test_two_tags_need_a_spike_metric():
    from app.glance import clumps

    pair = [_assoc(t, "sleep.total_h") for t in T[:2]]
    assert clumps(pair, DEFS, TAGS) == []
    spike = _insight(kind="change", feature_a="sleep.total_h", feature_b=None, effect=0.5, details={"pct": 12.0})
    assert clumps([*pair, spike], DEFS, TAGS) == []  # tags not in regular use
    found = clumps([*pair, spike], DEFS, TAGS, habitual=set(T))
    assert len(found) == 1 and found[0].spikes == ("Sleep (total)",)


def test_separate_series_do_not_clump():
    from app.glance import clumps

    split = [_assoc(T[0], "sleep.total_h"), _assoc(T[1], "sleep.total_h"), _assoc(T[2], "tracker.coffee.total")]
    assert clumps(split, DEFS, TAGS) == []


def test_a_drop_is_not_a_spike():
    from app.glance import clumps

    pair = [_assoc(t, "sleep.total_h") for t in T[:2]]
    drop = _insight(kind="change", feature_a="sleep.total_h", feature_b=None, details={"pct": -12.0})
    assert clumps([*pair, drop], DEFS, TAGS, habitual=set(T)) == []
