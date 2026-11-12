"""Write audit records. Call from services, never from serializers or views directly."""

import logging

from apps.core.context import get_request_id

from .models import AuditLog

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "credential", "refresh", "access"}


def client_ip(request) -> str | None:
    """
    Client IP for audit purposes. X-Forwarded-For is only trusted for the first hop
    set by our own proxy (Nginx sets X-Real-IP).
    """
    if request is None:
        return None
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def _scrub(changes: dict) -> dict:
    return {
        k: ("[redacted]" if any(s in k.lower() for s in _SENSITIVE_KEYS) else v) for k, v in (changes or {}).items()
    }


def record(
    action: str,
    *,
    request=None,
    actor=None,
    organization=None,
    target=None,
    target_type: str = "",
    target_id: str = "",
    changes: dict | None = None,
    actor_type: str | None = None,
) -> AuditLog | None:
    if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
    if organization is None and request is not None:
        organization = getattr(request, "organization", None)
    if target is not None:
        target_type = target_type or target._meta.label_lower
        target_id = target_id or str(target.pk)
    try:
        return AuditLog.objects.create(
            organization=organization,
            actor=actor,
            actor_type=actor_type or (AuditLog.ActorType.USER if actor else AuditLog.ActorType.ANONYMOUS),
            action=action,
            target_type=target_type,
            target_id=target_id,
            changes=_scrub(changes or {}),
            ip_address=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
            request_id=get_request_id() if get_request_id() != "-" else "",
        )
    except Exception:  # auditing must never break the business operation; log loudly instead
        logger.exception("Failed to write audit log entry for %s", action)
        return None
