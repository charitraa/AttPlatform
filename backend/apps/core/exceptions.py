"""
Central API exception handling.

Every error response uses the same envelope:

    {"error": {"code": str, "message": str, "details": any, "request_id": str}}
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .context import get_request_id

logger = logging.getLogger(__name__)


class DomainError(exceptions.APIException):
    """Base class for business-rule violations raised by services."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"
    default_detail = "The request violates a business rule."


class InvalidTransition(DomainError):
    default_code = "invalid_transition"
    default_detail = "This status transition is not allowed."


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "The resource was modified concurrently or already exists."


class ServiceUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "service_unavailable"
    default_detail = "A required service is temporarily unavailable."


_CODE_OVERRIDES = {
    exceptions.ValidationError: "validation_error",
    exceptions.ParseError: "parse_error",
    exceptions.NotFound: "not_found",
}


def _error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details, "request_id": get_request_id()}}


def api_exception_handler(exc, context):
    # Translate Django-native exceptions into DRF ones first.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()
    elif isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    response = drf_exception_handler(exc, context)

    if response is None:
        # Unhandled: log with traceback, never leak internals to the client.
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            _error_body("server_error", "An unexpected error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _CODE_OVERRIDES.get(type(exc)) or getattr(exc, "default_code", None) or "error"
    if isinstance(exc, exceptions.ValidationError):
        message, details = "Invalid input.", response.data
    else:
        detail = response.data.get("detail") if isinstance(response.data, dict) else response.data
        code = getattr(detail, "code", None) or code
        message, details = str(detail) if detail else "Request failed.", None
        if isinstance(response.data, dict):
            extra = {k: v for k, v in response.data.items() if k != "detail"}
            details = extra or None

    response.data = _error_body(code, message, details)
    return response
