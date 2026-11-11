# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# libmagic: upload content-type sniffing; curl: container health checks.
# The apt lists cleanup keeps the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
# Upload directory owned by the runtime user. A fresh named volume mounted here
# inherits this ownership; without it uploads fail with PermissionError.
RUN mkdir -p /app/media && chown app:app /app/media

# ---- development: dev dependencies, source mounted as a volume ----
FROM base AS dev
COPY requirements/ requirements/
RUN pip install -r requirements/dev.txt
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]

# ---- production: runtime dependencies only, collected static files ----
FROM base AS prod
COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt
COPY --chown=app:app . .
RUN DJANGO_SETTINGS_MODULE=config.settings.base DJANGO_SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.db \
    python manage.py collectstatic --noinput
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/api/v1/health/ || exit 1
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--proxy-headers", "config.asgi:application"]
