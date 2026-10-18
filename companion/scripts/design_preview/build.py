"""Assemble the design-review page from rendered screens (see run.sh).

Each screen is embedded as an ``<iframe srcdoc>`` with the stylesheet inlined, so the page is one
self-contained file. In the review page Archivo loads from Google Fonts, the only font host the
artifact viewer allows; the app itself self-hosts the same font.
"""

from __future__ import annotations

import html
import re
import sys

SCREENS = [  # file, wireframe screen, title, caption
    (
        "overview",
        "1a",
        "Overview",
        "Coverage strip first: hatched days are not recorded, never zero. Then the strongest discoveries, the "
        "baseline comparisons, and one-tap logging for pinned trackers.",
    ),
    (
        "discover",
        "1b",
        "Discoveries",
        "Each finding is a flush-left claim with its evidence underneath: days, adjusted p, a strength tag, and a "
        "Preliminary tag below 30 days. Sorted by strength, never by p-value alone.",
    ),
    (
        "evidence",
        "1c",
        "Evidence",
        "Plain finding first, then how it was found: method, effect, days, effective days after carry-over, raw "
        "and adjusted p. Association wording only.",
    ),
    (
        "log",
        "2a",
        "Daily log",
        "The evening pass. Every tracker in its own row with type-specific controls. Marking the day reviewed is "
        "what turns an empty count into a zero.",
    ),
    (
        "trackers",
        "2b",
        "Metric builder",
        "Create a logged metric: count, scale, yes/no, amount, duration, time, choice or moment. Type, unit and "
        "scale lock once it has data; changes make a new version.",
    ),
    (
        "metric",
        "3b",
        "Metric detail",
        "One template for every series, with a provenance tag (Imported, Logged, Derived), 30-day comparison, "
        "weekday profile and the last 30 days.",
    ),
    (
        "tracker",
        "2b",
        "Tracker set-up",
        "A logged metric's page: quick log with back-dating, a token that can log only this tracker, its settings "
        "and recent entries.",
    ),
    (
        "metrics",
        "3b",
        "Metrics library",
        "Every daily series the Companion builds, grouped by where it comes from, last 30 days against the 30 before.",
    ),
]


def main(root: str) -> None:
    css = open(f"{root}/preview/screens/style.css").read()
    css = re.sub(r"@font-face \{.*?\}\s*", "", css, flags=re.S)
    css = "@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&display=swap');\n" + css

    def screen(name: str) -> str:
        page = open(f"{root}/preview/screens/{name}.html").read()
        page = page.replace('<link rel="stylesheet" href="style.css">', f"<style>{css}</style>")
        page = re.sub(r'href="[a-z]+\.html"', 'href="#"', page)  # navigation is inert inside a frame
        return html.escape(page, quote=True)

    frames = "\n".join(
        f"""<figure class="phone">
  <div class="screen"><iframe title="{title} screen" srcdoc="{screen(name)}" loading="lazy"></iframe></div>
  <figcaption><span class="ref">{ref}</span> <strong>{title}</strong><span class="cap">{caption}</span></figcaption>
</figure>"""
        for name, ref, title, caption in SCREENS
    )
    desktop = f'<iframe title="Overview at desktop width" srcdoc="{screen("overview")}" loading="lazy"></iframe>'
    page = open(f"{root}/review_template.html").read()
    page = page.replace("{{FRAMES}}", frames).replace("{{DESKTOP}}", desktop)
    with open(f"{root}/preview/companion-design-review.html", "w") as fh:
        fh.write(page)


if __name__ == "__main__":
    main(sys.argv[1])
