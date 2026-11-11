"""Dependency checks used by the readiness endpoint."""
import logging
import time

import redis
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)


def _timed(check) -> dict:
    started = time.perf_counter()
    try:
        check()
        ok = True
    except Exception as exc:  # report failure without leaking connection details
        logger.warning("Readiness check failed: %s", exc.__class__.__name__)
        ok = False
    return {"status": "ok" if ok else "error", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def check_database() -> dict:
    def run():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    return _timed(run)


def check_redis() -> dict:
    def run():
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            client.ping()
        finally:
            client.close()

    return _timed(run)


CHECKS = {"database": check_database, "redis": check_redis}


def run_checks() -> dict[str, dict]:
    return {name: check() for name, check in CHECKS.items()}
