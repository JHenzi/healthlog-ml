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
| Navigation | Five sections: Overview, Discover, Log, Metrics, Trackers. A bottom tab bar on phones (≤ 720px), header links above that. | `_nav.html` |

## Wireframe screens → pages

| Wireframe | Page | State |
|---|---|---|
| 1a Overview | `/` | built: coverage strip, "worth exploring", baseline sentences, quick add |
| 1b Discoveries | `/insights` | built, without the likely-range bar (needs intervals) |
| 1c Evidence | `/insights/{id}` | built: finding, method, effect, days, effective days, p. Raw-observation plot and "things that could explain this" to come |
| 2a Daily log | `/review` | built: per-type controls, coloured ratings, tag chips, reviewed state. "Not recorded" toggling to come |
| 2b Metric builder | `/trackers` | built, simplified past the wireframe: presets, then name + kind + only the needed detail. Reminders come with web push (M11) |
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
