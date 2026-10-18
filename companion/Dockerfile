# HealthLog Companion image: one image, two compose services (web + jobs).
# Build context is companion/ (see compose.companion.yml).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # No model or hub downloads at runtime, ever (R5).
    HF_HUB_OFFLINE=1

RUN groupadd -g 1000 companion && useradd -u 1000 -g 1000 -d /app -s /usr/sbin/nologin companion

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY app/ app/
COPY migrations/ migrations/
COPY web/ web/
RUN pip install --no-deps -e .

USER companion
EXPOSE 8000

# Loopback only; /api/health also checks the database connection.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status != 200)"

ENTRYPOINT ["companion"]
CMD ["web"]
