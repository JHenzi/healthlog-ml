# henzis.com/health-companion — showcase notes

The public home page for this project is <https://henzis.com/health-companion/>.
It lives in the henzis.com **Astro** site (a separate repo), where every project page
looks the same. This folder is the bridge: the repo records what changed, and the
page gets refreshed from it.

GitHub is the developer's view. The page is the showcase: what it is, why it's
different, what it looks like, how to try it. Write for that reader.

## Files

- `page-facts.md` — the page's sections and the hard facts it quotes (test count,
  number of series, upstream PRs merged, screenshots, roadmap). Keep these true.
- `updates.md` — a log of page-worthy changes, newest first. Each entry is
  **pending** until it has been put on the page.

## When to add an entry

Add one in the same PR as any of these:

- a major feature or a new screen,
- a change in how the analysis works or what it claims,
- a discovery worth telling someone about,
- a number on the page going stale (tests, series, upstream PRs, install time),
- a roadmap item moving from Next to Now, or shipping.

Bug fixes and internal refactors don't need an entry.

## Refreshing the page (on the Mac)

1. Pull this repo next to the Astro site.
2. Ask Claude to read `page-facts.md` and the **pending** entries in `updates.md`,
   then update the health-companion page in the Astro site to match, keeping its
   voice and layout. New screenshots go in the site's `/health-companion/` assets.
3. Mark each entry it used `published YYYY-MM-DD`, update `page-facts.md`,
   and commit both here.

A full rewrite is fine later. Until then, keep the page fresh with small refreshes.
