"""At-a-glance discovery heads: direction from the effect's sign, never a judgement."""

from __future__ import annotations

from app.glance import card, icon_for
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
