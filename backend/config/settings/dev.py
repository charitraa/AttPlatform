"""Local development settings."""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# Real SMTP in dev? Set EMAIL_REDIRECT_TO so every message goes to you, not to demo addresses.
EMAIL_REDIRECT_TO = env("EMAIL_REDIRECT_TO", default="")
if EMAIL_REDIRECT_TO and EMAIL_BACKEND.endswith("smtp.EmailBackend"):
    EMAIL_BACKEND = "apps.core.mail.RedirectingSMTPBackend"

# Browsable API is convenient while developing.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
