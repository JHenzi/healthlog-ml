# Design: the Modernist look

The Companion's visual system and how it maps to the wireframes. Source:
Claude Design project "Personal analytics · Mobile wireframes · Mid-fi · v1"
(`Wireframes.dc.html`), built on its *Modernist* design system. Adopted
2026-10-18.

## The system

| Element | Rule | In code |
|---|---|---|
| Type | Archivo only, at 400 / 600 / 800 with tabular figures. Self-hosted: the app makes no runtime calls to font services (R5), and the CSP allows `'self'` only. | `web/static/fonts/` (OFL, see `OFL.txt`) |
| Color | Ink `#201e1d` on ground `#f3f2f2`. One accent, `#ec3013`, kept for the primary action, the current section and Preliminary tags. Paragraph-size accent text uses `#ae1800` (4.5:1). A dark mode inverts ground and ink. | `:root` tokens in `style.css` |
| Structure | Zero corner radius. 2px ink rules between sections, 1px rules between rows. No cards, shadows or floating panels. | `.card`, `.sentences`, `.entries`, `.discovery` |
| Labels | Flush left everywhere, including inside buttons. Uppercase, tracked kickers above titles. | `.kicker`, `button` |
| Missing data | Days without data are hatched and never drawn as zero (R7). | `.coverage span.missing` |
| Provenance | Every metric is tagged **Imported** (Apple Health via HealthLog), **Logged** (trackers) or **Derived** (stress, energy reserve). | `metrics_view.PROVENANCE` |
| Confidence | Findings resting on fewer than 30 days carry a **Preliminary** tag. Strength (weak / moderate / strong) is always shown. | `insights.html`, `today.html` |
| Navigation | Five sections: Overview, Discovery, Capture, My Metrics, Trackers. On phones (≤ 720px) a row of tabs under the brand in a sticky header, never at the bottom (the home bar and Safari's toolbar cover it); header links above that. | `_nav.html` |
| Saving | A form post updates the page in place: no reload, same scroll position, a double tap posts once. Sign-in and sign-out navigate normally. | `app.js` |

## Wireframe screens → pages

| Wireframe | Page | State |
|---|---|---|
| 1a Overview | `/` | built: coverage strip, "worth exploring", "worth noting" (streaks, records; `app/highlights.py`), baseline sentences, quick add |
| 1b Discoveries | `/insights` | built, with the likely-range bar (2026-10-19) |
| 1c Evidence | `/insights/{id}` | built: finding, method, effect, likely range, days, effective days, p. Raw-observation plot and "things that could explain this" to come |
| 2a Daily log | `/review` | built: per-type controls, coloured ratings, tag chips, reviewed state. "Not recorded" toggling to come |
| 2b Metric builder | `/trackers` | built, reshaped into three panels: what you track, day tags, and name + kind + only the needed detail, with ideas that fill in the form. Reminders come with web push (M11) |
| 3a Explore | — | not built: aligned timelines, scatter, calendar, lag option |
| 3b Metric detail | `/metrics/{feature}`, `/trackers/{key}` | built: provenance, 30-day comparison, weekday profile, recent days |
| 4a Experiments | — | not built (M9) |
| 4b Settings and data | — | not built: source health, export, delete |

## Direction: open

The Modernist look was the design tool's suggestion and was adopted to have
something concrete to react to. The wireframes are in
[`design/wireframes-v1.pdf`](design/wireframes-v1.pdf) and were shared with
the upstream maintainer on #107 (2026-10-18). The owner prefers warmth: an
organic palette (browns, greens) and softer, curvier type. Everything visual
lives in `style.css` tokens and the self-hosted font, so a re-skin doesn't
touch templates or structure. The structural decisions above (missing days
hatched, provenance and Preliminary tags, discoveries above baselines,
five sections) hold whichever skin is chosen.

## At a glance (2026-10-19)

Owner feedback: the insights were buried in text, and nothing could be read
from arm's length. Every place that states a finding or a value now leads
with a glance layer, with the sentence kept beneath as the detail (R10, R13):

- **Overview tiles:** icon, label, big value, and ▲/▼ with the change
  against the 30-day average. Colour (the accent) marks only values clearly
  above or below usual; "about usual" stays quiet. The arrow says which way,
  never whether that's good. The full sentences sit under "In words".
- **Discovery heads:** "[icon] Sleep ▲ ↔ [icon] Productivity ▲", then strength
  dots, "rise together" or "move opposite", and the days. Used on the
  Overview and the Discoveries page (`app/glance.py`, `_icons.html`).
- **Icons:** small inline line drawings, no icon font and no outside request.

## Warm look, live (2026-10-19)

The owner chose the warm look to pressure-test in daily use: `base.html`
now loads `warm.css` after `style.css`. Removing that one `<link>` brings back
the Modernist look. `SKIN=modernist` renders the review page in the old look
for comparison.

**Day tag colours:** each day tag keeps one of eight colours (`tc-0` … `tc-7`
in `style.css`: golden, teal, plum, brick, blue, forest, rose, violet),
assigned by its place in the list. It's filled when on, with coloured outline and text
when off, and a coloured pill when a discovery is about it. Removing a tag
shifts the colours of the tags after it.

**Good-day colours** (2026-10-30): a good-day part or score (0–100, ranked
against your own history) takes one of five bands, `gd-b0` … `gd-b4`: clay
(low for you), apricot, sand (usual), sage, moss (high). Higher is better
for every part by definition, so low → high reads bad → good. The
`/good-days` page leads with the last 14 days as a grid (a row per day,
the score and each part a coloured cell, ★ on best days, hatched where
there's no data); the Overview card's bars use the same bands.

## Warm candidate (2026-10-19)

`web/static/warm.css` is a second look that loads after `style.css` and only
overrides it. It uses paper and soil colours, moss green for actions and
switched-on tags, rounded tiles instead of 2px rules, and sentence-case
labels. Headings use Fraunces and body text uses Nunito (both SIL OFL, self-hosted, see
`fonts/OFL-warm.txt`). It has its own warm dark mode. The structural rules above
are unchanged. Nothing links it yet: switching means adding one `<link>` to
`base.html`. `SKIN=warm scripts/design_preview/run.sh <dir>` renders the
review page in it. That page is published privately at
https://claude.ai/artifact/5YEQVBwdtnxZx2SHLCD7pG.

The Claude Design project export (2026-10-19) holds the same
`Wireframes.dc.html` this look was built from and the Modernist design
system. It also has an unused top-level stylesheet from a different system
("Industry": Barlow, slate blue) that the wireframes never load.

## Owner feedback (2026-10-18)

- The metric builder was "a nightmare": too many choices. Make assumptions
  for the user; "flexible" isn't helpful. Done: presets; ratings are always
  1–10 with no labels, coloured from low to high (red → green when higher is
  better, a neutral ramp otherwise); the key, scale labels, category and
  polarity are gone from creation (polarity and the rest live on the
  metric's page); rarer kinds sit under "More kinds".
- **Tags** in setup and daily capture, e.g. "Work day" rated 1–10 with
  "in-fighting" and "meeting heavy" to tap, so a tag can be related to, say,
  fewer steps.
- Ideas, not pre-listed trackers: suggestions fill in the form and are
  grouped by who they fit ("at work", "training"…). Nothing overlapping
  Apple Health (coffee, alcohol, water): there's no way to write back to it,
  so those are logged there.
- Second pass: tags belong to the **day**, not to a measure, so they're
  their own panel. One scale everywhere with 10 as high, and no "higher is
  better" anywhere: the data says which way a tracker goes (meeting-heavy
  days might go with less drinking, or more crochet). The Trackers page is
  three bounded panels: what you track, day tags, new tracker.
- Third pass (2026-10-19): day tags start empty, no suggestions or
  categories; one find-or-add box picks a tag for the day, tiles toggle,
  removing for good sits under "Edit list". Logging shows the number
  ("2 cups", − / +), never a list of timed entries: the history is like git
  history, invisible but kept. A tracker's page is the number and its
  settings; connecting a Shortcut or token is a separate page.
- Tone: friendly beats stark. WaterLlama (a friendly, non-threatening bear
  mascot) is a reference people like.

## Review preview

`scripts/design_preview/run.sh <dir>` renders the real templates with
synthetic data (90 days, three planted relationships, the engine's real
output) into one self-contained review page. It never touches real data.
The current version is published privately at
https://claude.ai/artifact/3neuyiGRsjX3L7iZ9iXWgM. It's shared only when the
owner shares it. Sharing the Claude Design project link itself fails with a
size error, which is why the wireframes are exported as a PDF.
