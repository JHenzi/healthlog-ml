"""A prompt to paste into Shortcuts' AI builder, so it builds a tracker's logging Shortcut step by step (pure).

Everything the Shortcut needs is spelled out: the URL, POST, the bearer header, the JSON body for the tracker's type,
and speaking the reply's ``message`` back, so a misheard entry is caught right away (docs/api.md).
"""

from __future__ import annotations

TOKEN_PLACEHOLDER = "<paste your log-only token here>"  # noqa: S105 (a placeholder, not a secret)


def _value_steps(t_type: str, name: str, unit: str | None, scale: tuple[float, float], options: list[str]) -> str:
    """How the Shortcut gets the value, and what goes in the JSON body."""
    if t_type == "count":
        return "No question needed. Send an empty JSON dictionary; each run adds 1."
    if t_type == "quantity":
        return "No question needed. Send an empty JSON dictionary; each run adds 1."
    if t_type == "duration":
        what = unit or ("minutes" if t_type == "duration" else "amount")
        return (
            f'Ask for a number with the prompt "How many {what}?" (number input, default 1). '
            'Send a JSON dictionary with one key, "value", set to that number.'
        )
    if t_type == "scale":
        lo, hi = scale
        return (
            f'Ask for a number with the prompt "{name}, {lo:g} to {hi:g}?". '
            'Send a JSON dictionary with one key, "value", set to that number.'
        )
    if t_type == "check":
        return 'No question needed. Send a JSON dictionary with "value" set to the text "yes".'
    if t_type == "choice" and options:
        listed = ", ".join(f'"{o}"' for o in options)
        return (
            f"Choose from a list with these items: {listed}. "
            'Send a JSON dictionary with one key, "value", set to the chosen item.'
        )
    if t_type == "moment":
        return 'No question needed. Send an empty JSON dictionary. (Optional: "value" 1 to 3 for intensity.)'
    return "No question needed. Send an empty JSON dictionary; the time of the run is what gets logged."


SIRI_PREFIX = "Snap a"  # Siri doesn't claim "snap", unlike "log", "record", "add" or "play"


def siri_name(name: str) -> str:
    """The Shortcut's name, which is what you say to Siri: "Snap a stretching session" for "Stretching sessions"."""
    words = name.strip().split()
    last = words[-1] if words else name
    if len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        words[-1] = last[:-1]  # one entry: "sessions" → "session"
    return f"{SIRI_PREFIX} {' '.join(words).lower()}"


def build(
    *,
    name: str,
    t_type: str,
    unit: str | None,
    scale: tuple[float, float],
    options: list[str],
    url: str,
    token: str | None = None,
) -> str:
    return "\n".join(
        [
            f'Make a shortcut named "{siri_name(name)}" that logs one entry to my Companion app.',
            "",
            "Steps:",
            f"1. {_value_steps(t_type, name, unit, scale, options)}",
            f"2. Get Contents of URL: {url}",
            "   - Method: POST",
            f"   - Header: Authorization = Bearer {token or TOKEN_PLACEHOLDER}",
            "   - Header: Content-Type = application/json",
            "   - Request Body: JSON, the dictionary from step 1",
            '3. Get the value for the key "message" from the result, and Speak it.',
            '4. If the result has no "message", Speak "Not logged" and show the result.',
            "",
            "Don't add any other steps. Make it available to Siri.",
        ]
    )
