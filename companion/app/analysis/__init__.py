"""The insight engine (M5): day-level relationships with lags, week/month changes, weekday rhythms.

``pure`` holds the statistics (DB-free, seed-tested), ``engine`` turns a daily
feature frame into findings with one multiple-testing family, ``sentences``
words them (association language only, R10; evidence on every line, R13),
and ``run`` reads ``daily_features`` and stores ``insights``.
"""
