"""Test settings: deterministic, fast, isolated from external services."""
from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
ENVIRONMENT = "test"
ALLOWED_HOSTS = ["*"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

AI_PROVIDER = "mock"
AI_API_KEY = ""

# Throttling is disabled globally in tests; throttle tests opt in explicitly.
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
