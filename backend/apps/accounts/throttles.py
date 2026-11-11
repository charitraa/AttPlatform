from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    """
    Limits credential endpoints per client IP *and* per submitted email, so neither
    rotating emails from one IP nor spreading one email across IPs bypasses it.
    """

    scope = "auth"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ""
        if hasattr(request, "data") and isinstance(request.data, dict):
            email = str(request.data.get("email", "")).strip().lower()[:254]
        return self.cache_format % {"scope": self.scope, "ident": f"{ident}:{email}"}


class AuthIPRateThrottle(SimpleRateThrottle):
    scope = "auth_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
