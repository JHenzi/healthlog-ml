# The weather collector (companion-collector) and the reminder courier (companion-courier): standard library only.
# Network access, no database credentials, no health data. The collector writes one CSV to a shared volume; the
# courier posts reminders the Companion has already sealed (encrypted for the phone) from another one.
FROM python:3.14-slim@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd -g 1000 collector && useradd -u 1000 -g 1000 -d /nonexistent -s /usr/sbin/nologin collector \
    && mkdir /data /push && chown 1000:1000 /data /push

COPY collector.py /usr/local/lib/collector.py
RUN printf '#!/bin/sh\nexec python /usr/local/lib/collector.py "$@"\n' > /usr/local/bin/collector \
    && chmod +x /usr/local/bin/collector

USER collector
VOLUME /data
ENTRYPOINT ["collector"]
CMD ["run"]
