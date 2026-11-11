"""
The refresh token lives in an HttpOnly cookie scoped to the auth endpoints, so
page scripts (and any XSS) cannot read it. The short-lived access token is
returned in the JSON body and kept in memory by the SPA.
"""
from django.conf import settings


def set_refresh_cookie(response, refresh_token: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH, samesite=settings.REFRESH_COOKIE_SAMESITE
    )


def get_refresh_cookie(request) -> str | None:
    return request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
