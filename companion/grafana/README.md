# Extra Grafana dashboards

Two dashboards next to upstream's three, in the same *HealthLog* folder. They
read only HealthLog's own tables and views (`sleep_nightly`, `daily_metrics`,
`metric_registry`, `app_settings`), so they could be offered upstream as they
are.

- **Sleep & Activity** (`healthlog-sleep-activity`): a key with each term in
  its chart colour, sleep stages per night, sleep and the next day's exercise
  and steps on one timeline, the day after longer vs shorter nights, and the
  overnight measures. **Activity counted** (top of the page) shifts sleep forward
  0–7 days, so Monday night's sleep can sit next to Wednesday's activity.
  **Which gap lines up** measures, for every gap from 7 days before to 7 days
  after a night, how closely sleep and exercise or steps move together (rank
  correlation, with the number of pairs in the tooltip). Both directions and
  every gap are shown; none is picked out (R17).
- **All Metrics** (`healthlog-all-metrics`): every metric with data in the
  last 180 days as its own small chart, grouped by category, with no dropdowns.
  Totals (steps, minutes, energy) are bars from zero; measurements (heart
  rate, HRV, temperature) are lines, since bars on an axis that doesn't start
  at zero exaggerate small changes. The dashed 7-day average covers 7 calendar
  days, so days without data don't stretch it. Titles show readable units
  (bpm, °C).

Screenshots (synthetic data, R4; taken before totals and measurements were split): [Sleep & Activity](screenshots/sleep-activity.png),
[All Metrics](screenshots/all-metrics.png).

**One scale for different units.** The combined chart ranks each day among
your own days in the range shown (percentile: 100 = your highest, 50 =
typical). A percentage of the average was tried first, but it flattened
sleep: sleep varies about ±15%, while exercise swings to 370%.

Edit `build.py`, not the JSON:

```bash
python3 companion/grafana/build.py companion/grafana/dashboards
```

`compose.local.yml` mounts upstream's dashboards and these side by side;
Grafana picks up changes within 30 seconds.

**Upstream ships its own copy.** Upstream adapted these two dashboards
(#121) with the same UIDs and puts them in `grafana/dashboards/`, with the
reading guide collapsed and the day-after panels dropped. Ours stay the live
ones: when a sync merge brings their `sleep-activity.json` /
`all-metrics.json`, delete them in the merge (see
[`docs/upgrading.md`](../docs/upgrading.md)). Their three dashboards link to
these UIDs, so the links land on ours.
