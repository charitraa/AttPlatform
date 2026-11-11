import pytest
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import InvalidTransition


class _Input(serializers.Serializer):
    title = serializers.CharField()


class ValidateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        _Input(data=request.data).is_valid(raise_exception=True)
        return Response({})


class BoomView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise RuntimeError("database password is hunter2")


class DomainView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise InvalidTransition("Cannot move from closed to new.")


class PrivateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({})


urlpatterns = [
    path("validate/", ValidateView.as_view()),
    path("boom/", BoomView.as_view()),
    path("domain/", DomainView.as_view()),
    path("private/", PrivateView.as_view()),
]

pytestmark = [pytest.mark.urls(__name__)]


def test_validation_error_envelope(api_client):
    response = api_client.post("/validate/", {}, format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "title" in error["details"]
    assert error["request_id"] == response["X-Request-ID"]


def test_unhandled_error_hides_internals(api_client):
    api_client.raise_request_exception = False
    response = api_client.get("/boom/")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "server_error"
    assert "hunter2" not in response.content.decode()


def test_domain_error_code(api_client):
    response = api_client.get("/domain/")
    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "invalid_transition",
        "message": "Cannot move from closed to new.",
        "details": None,
        "request_id": response["X-Request-ID"],
    }


def test_unauthenticated_envelope(api_client):
    response = api_client.get("/private/")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_unknown_route_returns_404(api_client):
    assert api_client.get("/does-not-exist/").status_code == 404
