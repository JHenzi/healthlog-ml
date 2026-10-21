# Extra Grafana dashboards

Two dashboards next to upstream's three, in the same *HealthLog* folder. They
read only HealthLog's own tables and views (`sleep_nightly`, `daily_metrics`,
`metric_registry`, `app_settings`), so they could be offered upstream as they
are.

- **Sleep & Activity** (`healthlog-sleep-activity`): a key with each term in
  its chart colour, sleep stages per night, sleep and the next day's exercise
  and steps on one timeline, the day after longer vs shorter nights, and the
  overnight measures.
- **All Metrics** (`healthlog-all-metrics`): every metric with data in the
  last 180 days as its own small chart, grouped by category, with no dropdowns.

Screenshots (synthetic data, R4): [Sleep & Activity](screenshots/sleep-activity.png),
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
