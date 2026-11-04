"""The Shortcuts build prompt spells out a request the API accepts (docs/api.md)."""

from __future__ import annotations

from app import shortcut_prompt

URL = "https://tv.example.ts.net:8443/api/log/x"


def _build(t_type, **kw):
    args = {"name": "X", "t_type": t_type, "unit": None, "scale": (1, 10), "options": [], "url": URL}
    return shortcut_prompt.build(**(args | kw))


def test_prompt_has_post_bearer_and_spoken_reply():
    text = _build("count", token="hlc_abc")
    assert URL in text and "Method: POST" in text
    assert "Authorization = Bearer hlc_abc" in text and '"message"' in text


def test_without_a_token_it_leaves_a_placeholder():
    assert shortcut_prompt.TOKEN_PLACEHOLDER in _build("count")


def test_value_follows_the_tracker_type():
    assert "adds 1" in _build("count")
    assert "adds 1" in _build("quantity", unit="sessions")
    assert "How many minutes?" in _build("duration")
    assert "1 to 10" in _build("scale")
    assert '"a", "b"' in _build("choice", options=["a", "b"])


def test_siri_name_starts_with_snap_a_and_names_one_entry():
    assert shortcut_prompt.siri_name("Coffee breaks") == "Snap a coffee break"
    assert shortcut_prompt.siri_name("Stretching session") == "Snap a stretching session"
    assert shortcut_prompt.siri_name("Stress") == "Snap a stress"
    assert 'named "Snap a x"' in _build("count")
