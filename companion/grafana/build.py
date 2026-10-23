"""Builds the Companion's extra Grafana dashboards: python companion/grafana/build.py companion/grafana/dashboards."""

import json
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1])
DS = {"uid": "healthlog-db"}
TZ_VAR = {
    "name": "tz",
    "type": "query",
    "label": "Timezone",
    "hide": 2,
    "datasource": {"uid": "healthlog-db"},
    "description": "Hidden. HealthLog's configured TZ (app_settings.local_tz), as in the upstream dashboards.",
    "query": "SELECT value FROM app_settings WHERE key = 'local_tz'",
    "definition": "SELECT value FROM app_settings WHERE key = 'local_tz'",
    "refresh": 1,
    "sort": 0,
    "multi": False,
    "includeAll": False,
    "current": {},
    "options": [],
}
DAY = "(day::timestamp AT TIME ZONE '$tz')"
NIGHT = "(sleep_date::timestamp AT TIME ZONE '$tz')"
NOT_REPORTED = "Not reported by your devices in this range"

C = {  # one colour per term, the same in the key and in the charts
    "deep": "#3b5bdb",
    "core": "#74c0fc",
    "rem": "#9c36b5",
    "awake": "#f08c00",
    "sleep": "#5c7cfa",
    "exercise": "#2f9e44",
    "steps": "#e8590c",
    "avg": "#868e96",
}

_id = 0


def nid():
    global _id
    _id += 1
    return _id


def term(key, text):
    return f'<b style="color:{C[key]}">{text}</b>'


def text_panel(html, x, y, w, h, title=""):
    return {
        "id": nid(),
        "type": "text",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "html", "content": html},
    }


def fixed(name, colour, extra=()):
    props = [{"id": "color", "value": {"mode": "fixed", "fixedColor": colour}}, *extra]
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def target(sql, fmt="time_series", ref="A"):
    return {"refId": ref, "datasource": DS, "rawQuery": True, "editorMode": "code", "rawSql": sql, "format": fmt}


def dashboard(uid, title, description, panels, variables, time_from="now-90d"):
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["healthlog", "companion"],
        "editable": False,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "",
        "timezone": "browser",
        "time": {"from": time_from, "to": "now"},
        "templating": {"list": variables},
        "annotations": {"list": []},
        "links": [],
        "panels": panels,
    }


# --- Sleep & Activity ----------------------------------------------------------------------------------------------
KEY = f"""<div style="font-size:15px;line-height:1.6">
<p>Each night is dated by the morning you woke up. Your watch estimates the stages from movement and heart rate,
not a sleep lab, so the pattern over weeks says more than any single night.</p>
<p>{term("sleep", "Total sleep")} is time asleep, all stages together.
{term("deep", "Deep sleep")} is the slow-wave stage, when you are hardest to wake; most of it comes in the first half
of the night. {term("core", "Core sleep")} is Apple's name for light sleep and usually fills most of the night.
{term("rem", "REM sleep")} is the stage with the most vivid dreaming; its stretches get longer towards morning, so a
short night trims REM first. {term("awake", "Awake")} counts brief wakings; everyone has some and most are never
remembered.</p>
<p>Some measures only come from newer watches or once a feature is switched on. A panel that says
<i>{NOT_REPORTED.lower()}</i> means no data, never zero.</p></div>"""

NORMAL_KEY = f"""<div style="font-size:15px;line-height:1.6">
<p><b>Reading the combined chart.</b> Hours of sleep, minutes of exercise and steps don't share a scale, so each line
shows <b>where that day ranks among your own days</b> on screen: 100 is your highest, 0 your lowest, and the grey
line at 50 is a typical day. Ranking puts a long night and a big exercise day on the same footing, however different
the units, and one extreme day can't flatten the rest. Each date pairs
{term("sleep", "the night that ended that morning")} with that day's
{term("exercise", "exercise")} and {term("steps", "steps")}: the day after the night.</p>
<p>Peaks and dips that line up are worth a look, not proof: over a few weeks, lines can match by chance.</p></div>"""


def stat(title, sql, x, y, w, h, unit, decimals=1, fmt="table", colour=None, desc=""):
    defaults = {
        "unit": unit,
        "decimals": decimals,
        "noValue": "–",
        "color": {"mode": "fixed", "fixedColor": colour or C["sleep"]},
    }
    return {
        "id": nid(),
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql, fmt)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
            "colorMode": "value",
            "graphMode": "none",
            "textMode": "value_and_name",
            "justifyMode": "auto",
            "orientation": "auto",
        },
    }


def series(title, sql, x, y, w, h, unit, overrides, draw="line", stacked=False, desc="", decimals=1, extra=None):
    custom = {
        "drawStyle": draw,
        "lineWidth": 2,
        "fillOpacity": 70 if draw == "bars" else 10,
        "lineInterpolation": "smooth",
        "showPoints": "auto",
        "spanNulls": False,
        "stacking": {"mode": "normal" if stacked else "none", "group": "A"},
    }
    defaults = {
        "unit": unit,
        "decimals": decimals,
        "noValue": NOT_REPORTED,
        "custom": custom,
        "color": {"mode": "palette-classic"},
    }
    if extra:
        defaults.update(extra)
    return {
        "id": nid(),
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql)],
        "fieldConfig": {"defaults": defaults, "overrides": overrides},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }


def row(title, y):
    return {
        "id": nid(),
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


NIGHTS = f"FROM sleep_nightly WHERE $__timeFilter({NIGHT})"
P = []
P.append(text_panel(KEY, 0, 0, 16, 8, "How to read this page"))
P.append(
    stat(
        "Last night",
        'SELECT total_sleep_h AS "Total sleep" FROM sleep_nightly ORDER BY sleep_date DESC LIMIT 1',
        16,
        0,
        4,
        4,
        "h",
        desc="Total sleep, the most recent night recorded.",
    )
)
P.append(
    stat(
        "Average night",
        f'SELECT AVG(total_sleep_h) AS "Total sleep" {NIGHTS}',
        20,
        0,
        4,
        4,
        "h",
        desc="Mean total sleep over the nights in the selected range.",
    )
)
P.append(
    stat(
        "Nights recorded",
        f'SELECT COUNT(*) AS "Nights" {NIGHTS}',
        16,
        4,
        4,
        4,
        "none",
        0,
        desc="Nights with sleep data in the selected range. Nights without the watch are missing, not zero.",
    )
)
P.append(
    stat(
        "REM share",
        f'SELECT 100 * SUM(rem_h) / NULLIF(SUM(total_sleep_h), 0) AS "REM" {NIGHTS}',
        20,
        4,
        4,
        4,
        "percent",
        0,
        colour=C["rem"],
        desc="REM sleep as a share of total sleep over the range.",
    )
)
P.append(row("Your nights", 7))
P.append(
    series(
        "Sleep stages per night",
        f'SELECT {NIGHT} AS time, deep_h AS "Deep", core_h AS "Core", rem_h AS "REM", awake_h AS "Awake" '
        f"{NIGHTS} ORDER BY sleep_date",
        0,
        8,
        24,
        9,
        "h",
        [fixed("Deep", C["deep"]), fixed("Core", C["core"]), fixed("REM", C["rem"]), fixed("Awake", C["awake"])],
        draw="bars",
        stacked=True,
        desc="Hours in each stage, stacked: the bar's height is time in bed asleep plus brief wakings.",
    )
)
P.append(row("Sleep and the next day", 17))
P.append(text_panel(NORMAL_KEY, 0, 18, 24, 5))
NORMAL_SQL = f"""WITH s AS (
  SELECT sleep_date AS day, total_sleep_h AS v {NIGHTS}
), e AS (
  SELECT day, sum AS v FROM daily_metrics WHERE metric = 'apple_exercise_time' AND $__timeFilter({DAY})
), st AS (
  SELECT day, sum AS v FROM daily_metrics WHERE metric = 'step_count' AND $__timeFilter({DAY})
), days AS (SELECT day FROM s UNION SELECT day FROM e UNION SELECT day FROM st)
SELECT {DAY} AS time,
  s.r AS "Sleep (the night before)", e.r AS "Exercise", st.r AS "Steps"
FROM days
  LEFT JOIN (SELECT day, 100 * percent_rank() OVER (ORDER BY v) AS r FROM s) s USING (day)
  LEFT JOIN (SELECT day, 100 * percent_rank() OVER (ORDER BY v) AS r FROM e) e USING (day)
  LEFT JOIN (SELECT day, 100 * percent_rank() OVER (ORDER BY v) AS r FROM st) st USING (day)
ORDER BY day"""
P.append(
    series(
        "Sleep and the next day's activity, ranked against your own days",
        NORMAL_SQL,
        0,
        23,
        24,
        10,
        "none",
        [
            fixed("Sleep (the night before)", C["sleep"], [{"id": "custom.lineWidth", "value": 3}]),
            fixed("Exercise", C["exercise"]),
            fixed("Steps", C["steps"]),
        ],
        decimals=0,
        desc="Each series as its percentile rank over the selected range: 100 = your highest day, 50 = typical, "
        "0 = lowest.",
        extra={
            "custom": {
                "drawStyle": "line",
                "lineWidth": 2,
                "fillOpacity": 0,
                "lineInterpolation": "smooth",
                "showPoints": "always",
                "pointSize": 5,
                "spanNulls": False,
                "thresholdsStyle": {"mode": "line+area"},
            },
            "thresholds": {
                "mode": "absolute",
                "steps": [{"color": "transparent", "value": None}, {"color": "#adb5bd", "value": 50}],
            },
            "min": 0,
            "max": 100,
        },
    )
)
AFTER_SQL = f"""WITH s AS (
  SELECT sleep_date AS day, total_sleep_h AS v {NIGHTS}
), m AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY v) AS mid FROM s),
a AS (
  SELECT s.day, s.v >= m.mid AS longer, d.metric, d.sum
  FROM s CROSS JOIN m JOIN daily_metrics d ON d.day = s.day AND d.metric IN ('apple_exercise_time', 'step_count')
)
SELECT CASE WHEN longer THEN 'After longer nights' ELSE 'After shorter nights' END
         || ' (' || COUNT(*) || ' days)' AS "Group",
       AVG(sum) AS "Value"
FROM a WHERE metric = '%s' GROUP BY longer ORDER BY longer DESC"""
P.append(
    stat(
        "Exercise the day after",
        AFTER_SQL % "apple_exercise_time",
        0,
        33,
        12,
        4,
        "m",
        0,
        colour=C["exercise"],
        desc="Average exercise minutes on days after nights at or above your median sleep (longer) and below it "
        "(shorter), over the selected range. A description, not a test.",
    )
)
P.append(
    stat(
        "Steps the day after",
        AFTER_SQL % "step_count",
        12,
        33,
        12,
        4,
        "none",
        0,
        colour=C["steps"],
        desc="Average steps on days after your longer and shorter nights (split at your median sleep).",
    )
)
P.append(row("Overnight measures", 37))
for k, (metric, name, unit, agg) in enumerate(
    (
        ("apple_sleeping_wrist_temperature", "Sleeping wrist temperature", "celsius", "avg"),
        ("respiratory_rate", "Respiratory rate (breaths/min)", "none", "avg"),
        ("breathing_disturbances", "Breathing disturbances", "none", "sum"),
    )
):
    P.append(
        series(
            name,
            f"SELECT {DAY} AS time, {agg} AS \"{name}\" FROM daily_metrics WHERE metric = '{metric}' "
            f"AND $__timeFilter({DAY}) ORDER BY day",
            8 * k,
            38,
            8,
            7,
            unit,
            [fixed(name, C["sleep"])],
            desc="Only from watches that measure it (some need a newer model or a setting turned on).",
        )
    )

sleep = dashboard(
    "healthlog-sleep-activity",
    "HealthLog – Sleep & Activity",
    "Sleep stages, and sleep against the next day's activity on one scale.",
    P,
    [TZ_VAR],
)

# --- All Metrics ---------------------------------------------------------------------------------------------------
_id = 0
GLOSSARY = f"""<div style="font-size:15px;line-height:1.6">
<p>Every measure your devices sent in the last six months, one chart each, grouped by kind. Nothing to choose:
a measure your watch doesn't record simply isn't listed, and older watches report fewer.</p>
<p><b>Totals</b> are things that add up (steps, exercise minutes, energy): each day is a
<b style="color:{C["sleep"]}">bar</b> from zero. <b>Measurements</b> are things that are measured (heart rate, walking
speed): each day is a <b style="color:{C["sleep"]}">point on a line</b>, the day's average, or the lowest reading for
resting heart rate. The <b style="color:{C["avg"]}">dashed line</b> is the 7-day average, which shows the trend under the
day-to-day noise.</p>
<p><b style="color:#c2255c">Heart rate variability</b> (HRV) is how much the time between heartbeats varies; it runs
higher when you're rested and is very personal, so compare it with your own history, not other people's.
<b style="color:#e8590c">Resting heart rate</b> is the lowest steady rate of the day.
<b style="color:#1971c2">Walking asymmetry</b> and <b style="color:#1971c2">double support</b> come from the iPhone in
your pocket: how evenly you step, and how much of each stride both feet are on the ground.</p></div>"""

# Titles show readable units (bpm, °C) instead of the registry's canonical ones (count/min, degC).
UNIT = (
    "CASE r.unit_canonical WHEN 'degC' THEN '°C' WHEN 'dBASPL' THEN 'dB' WHEN 'km/hr' THEN 'km/h' "
    "WHEN 'count/min' THEN CASE m.metric WHEN 'respiratory_rate' THEN 'breaths/min' ELSE 'bpm' END "
    "WHEN 'count' THEN NULL ELSE NULLIF(r.unit_canonical, '') END"
)
AGG = "COALESCE(r.agg_default, 'avg')"


def metric_var(name, kind):
    """A hidden variable listing every metric of one kind with data in the last 180 days, in category order."""
    return {
        "name": name,
        "type": "query",
        "label": "Metric",
        "hide": 2,
        "datasource": {"uid": "healthlog-db"},
        "description": "Hidden: every metric of this kind with data in the last 180 days, in category order. The "
        "page repeats one chart per metric.",
        "query": "SELECT initcap(COALESCE(NULLIF(r.category, 'unknown'), 'other')) || ' · ' || COALESCE(r.display_name, "
        f"m.metric) || COALESCE(' (' || {UNIT} || ')', '') AS __text, m.metric AS __value "
        "FROM (SELECT DISTINCT metric FROM daily_metrics WHERE day > current_date - 180) m "
        "LEFT JOIN metric_registry r USING (metric) "
        f"WHERE {kind} "
        "ORDER BY COALESCE(NULLIF(r.category, 'unknown'), 'zz'), 1",
        "refresh": 1,
        "sort": 0,
        "multi": True,
        "includeAll": True,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        "options": [],
    }


# Totals (steps, minutes, energy) are bars from zero; measured values (heart rate, HRV) are lines, because bars on an
# axis that doesn't start at zero exaggerate small changes.
KINDS = (
    ("total", "Totals", f"{AGG} = 'sum'", "bars"),
    ("measured", "Measurements", f"{AGG} <> 'sum'", "line"),
)


def metric_panel(name, draw, y):
    sql = f"""SELECT {DAY} AS time,
  CASE {AGG} WHEN 'sum' THEN d.sum WHEN 'min' THEN d.vmin WHEN 'max' THEN d.vmax ELSE d.avg END AS "Daily",
  AVG(CASE {AGG} WHEN 'sum' THEN d.sum WHEN 'min' THEN d.vmin WHEN 'max' THEN d.vmax ELSE d.avg END)
    OVER (ORDER BY d.day RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW) AS "7-day average"
FROM daily_metrics d LEFT JOIN metric_registry r USING (metric)
WHERE d.metric = '${name}' AND $__timeFilter({DAY})
ORDER BY d.day"""
    panel = series(
        f"${name}",
        sql,
        0,
        y,
        8,
        7,
        "short",
        [
            fixed("Daily", C["sleep"]),
            fixed(
                "7-day average",
                C["avg"],
                [
                    {"id": "custom.drawStyle", "value": "line"},
                    {"id": "custom.lineWidth", "value": 2},
                    {"id": "custom.fillOpacity", "value": 0},
                    {"id": "custom.showPoints", "value": "never"},
                    {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}},
                ],
            ),
        ],
        draw=draw,
        desc=f"Each day's value ({'bars' if draw == 'bars' else 'solid line'}) and the 7-day average (dashed).",
    )
    custom = panel["fieldConfig"]["defaults"]["custom"]
    if draw == "bars":
        custom["fillOpacity"] = 60
        custom["axisSoftMin"] = 0
    else:
        custom["showPoints"] = "always"
        custom["pointSize"] = 4
    panel["options"]["legend"]["showLegend"] = False
    panel.update({"repeat": name, "repeatDirection": "h", "maxPerRow": 3})
    return panel


metric_panels, metric_vars = [], []
for i, (name, title, kind, draw) in enumerate(KINDS):
    metric_panels += [row(title, 7 + 8 * i), metric_panel(name, draw, 8 + 8 * i)]
    metric_vars.append(metric_var(name, kind))
metrics = dashboard(
    "healthlog-all-metrics",
    "HealthLog – All Metrics",
    "Every metric as its own small chart, no dropdowns.",
    [text_panel(GLOSSARY, 0, 0, 24, 7, "How to read this page"), *metric_panels],
    [TZ_VAR, *metric_vars],
)

for name, d in (("sleep-activity.json", sleep), ("all-metrics.json", metrics)):
    (OUT / name).write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
print("ok")
