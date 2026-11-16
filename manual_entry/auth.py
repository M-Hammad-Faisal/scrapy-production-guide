"""Demo API-key authentication. The key decides WHO entered a value; the client cannot choose it.

That matters for the audit trail: ``entered_by`` is taken from the authenticated identity, never
from the request body, so nobody can record a change under someone else's name.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


@dataclass(frozen=True)
class ApiUser:
    username: str
    is_authenticated: bool = True


def parse_keys(raw: str) -> dict[str, str]:
    """'alice:key1,bob:key2' -> {'key1': 'alice', 'key2': 'bob'}"""
    keys = {}
    for pair in raw.split(","):
        name, sep, key = pair.strip().partition(":")
        if sep and name and key:
            keys[key] = name
    return keys


class ApiKeyAuthentication(BaseAuthentication):
    header = "HTTP_X_API_KEY"

    def authenticate(self, request):
        supplied = request.META.get(self.header)
        if not supplied:
            return None  # no credentials -> 401 via IsAuthenticated
        for key, username in parse_keys(settings.MANUAL_ENTRY_KEYS).items():
            # constant-time comparison: do not leak how much of a key matched
            if hmac.compare_digest(supplied.encode(), key.encode()):
                return ApiUser(username), None
        raise AuthenticationFailed("invalid API key")

    def authenticate_header(self, request):
        return "X-API-Key"
