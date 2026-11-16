"""Minimal Django settings for the manual-entry API.

Deliberately tiny: no Django database, no sessions, no admin. The data lives in the same SQL
database the crawlers write to (see crawlers.storage), reached through SQLAlchemy.

DEMO AUTH ONLY: API keys come from MANUAL_ENTRY_KEYS ("alice:key1,bob:key2"). With no keys
configured every request is rejected (secure by default). A real deployment would use your
company's SSO or Django's own auth, plus HTTPS.
"""

import os

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-for-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() in {"1", "true"}
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")

INSTALLED_APPS = ["rest_framework"]
ROOT_URLCONF = "manual_entry.urls"
DATABASES: dict = {}  # Django itself needs no database here
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["manual_entry.auth.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

# The same database the crawlers write to.
MANUAL_ENTRY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/crawl.db")
MANUAL_ENTRY_KEYS = os.environ.get("MANUAL_ENTRY_KEYS", "")
