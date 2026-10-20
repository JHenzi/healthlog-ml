"""Engine tunables. Changing one changes what counts as a finding, so the stats suite pins their effect."""

from __future__ import annotations

# Benjamini-Hochberg target over the whole family (all features x lags x horizons, R8).
FDR_Q = 0.10

# Day-level relationships.
LAGS = (0, 1)  # same day; exposure today -> outcome tomorrow (both directions are tested)
MIN_PAIRED_DAYS = 21  # overlapping days a continuous pair needs
MIN_GROUP_DAYS = 8  # days in each group (with / without) for a yes/no exposure
RHO_FLOOR = 0.25  # |Spearman rho| below this is never reported, however small p is
CLIFF_FLOOR = 0.25  # |Cliff's delta| floor for yes/no comparisons
TREND_WINDOW_DAYS = 28  # centred rolling mean removed as the slow trend
TREND_MIN_PERIODS = 7
# Autocorrelation lags summed for the effective sample size. One lag was measurably too optimistic on
# autocorrelated noise (11% false positives at p<.05); ten lags are calibrated (~5%), see tests/stats.
NEFF_MAX_LAG = 10

# Week / month changes: recent window vs the window before it.
CHANGE_HORIZONS = {"week": (7, 28), "month": (28, 56)}  # recent days, baseline days
CHANGE_MIN_FRACTION = 0.7  # each window needs at least this share of its days observed
CHANGE_PCT_FLOOR = 15.0  # % change floor
CHANGE_CLIFF_FLOOR = 0.33

# Weekday rhythm.
WEEKDAY_MIN_PER_DAY = 4
WEEKDAY_ETA2_FLOOR = 0.06  # Kruskal-Wallis effect size (~"medium")

# Distributed lags: an exposure's link to an outcome spread over days 0..DLM_MAX_LAG, as one smooth curve
# (Almon polynomial of DLM_DEGREE) and one test per exposure-outcome pair. Exposures are things you do or get
# (trackers, sleep, caffeine, daylight); outcomes are everything else. Only curves that peak at DLM_MIN_PEAK days
# or later are reported: same-day and next-day links are the day-level tests' job.
DLM_MAX_LAG = 7
DLM_DEGREE = 2
DLM_MIN_DAYS = 56
DLM_MIN_PEAK = 2
DLM_EXPOSURE_FAMILY_PREFIXES = ("tracker:",)
DLM_EXPOSURES = ("sleep.total_h", "hl.caffeine", "hl.time_in_daylight")

# Adjusted re-check of reported relationships: does the link survive once these everyday drivers are allowed
# for? A finding is re-checked against each one that isn't in either side's family. Not new tests (no p-values
# join the FDR family): a robustness reading of findings already reported.
ADJUST_FOR = ("sleep.total_h", "hl.step_count")
ADJUST_EXPLAINED_SHARE = 0.5  # adjusted |rho| below this share of the unadjusted one, and unclear: "explained"

# Likely ranges shown with every finding (design 1b/1c).
INTERVAL_LEVEL = 0.95

# Wording thresholds for |rho| / |delta|.
STRENGTH_BANDS = ((0.5, "strong"), (0.3, "moderate"), (0.0, "weak"))
