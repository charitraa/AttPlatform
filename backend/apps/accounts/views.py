from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import exceptions, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.context import get_request_id
from apps.organizations import services as org_services
from apps.organizations.permissions import IsOrganizationMember

from . import services
from .cookies import clear_refresh_cookie, get_refresh_cookie, set_refresh_cookie
from .serializers import (
    AcceptInvitationSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    InvitationPreviewSerializer,
    InvitationTokenSerializer,
    LoginSerializer,
    MeSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    build_me,
)
from .throttles import AuthIPRateThrottle, AuthRateThrottle

User = get_user_model()

SessionResponse = inline_serializer("SessionResponse", {"access": serializers.CharField(), "user": MeSerializer()})
AccessResponse = inline_serializer("AccessResponse", {"access": serializers.CharField()})
DetailResponse = inline_serializer("DetailResponse", {"detail": serializers.CharField()})


class UnauthenticatedView(APIView):
    """
    Endpoints reachable without an access token. Declaring the auth scheme keeps
    authentication failures as 401 (DRF downgrades them to 403 without it).
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


class PublicAuthView(UnauthenticatedView):
    """Credential endpoints: strict throttling."""

    throttle_classes = [AuthRateThrottle, AuthIPRateThrottle]


def _session_response(user, refresh, *, status_code=status.HTTP_200_OK, membership=None) -> Response:
    response = Response({"access": str(refresh.access_token), "user": build_me(user, membership)}, status=status_code)
    set_refresh_cookie(response, str(refresh))
    return response


@extend_schema(tags=["auth"])
class LoginView(PublicAuthView):
    @extend_schema(
        request=LoginSerializer,
        responses={200: SessionResponse, 401: OpenApiResponse(description="Invalid credentials")},
    )
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user, refresh = services.login(request=request, **s.validated_data)
        return _session_response(user, refresh)


@extend_schema(tags=["auth"])
class RefreshView(UnauthenticatedView):
    """Rotates the refresh cookie and returns a new access token."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "session"

    @extend_schema(request=None, responses={200: AccessResponse, 401: OpenApiResponse(description="Session expired")})
    def post(self, request):
        raw = get_refresh_cookie(request)
        if not raw:
            raise exceptions.NotAuthenticated("No active session.")
        try:
            access, new_refresh = services.rotate_refresh(raw)
        except exceptions.AuthenticationFailed:
            response = Response(
                {"error": {"code": "session_expired", "message": "Your session has expired. Please sign in again.",
                           "details": None, "request_id": get_request_id()}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_refresh_cookie(response)
            return response
        response = Response({"access": access})
        set_refresh_cookie(response, new_refresh)
        return response


@extend_schema(tags=["auth"])
class LogoutView(UnauthenticatedView):

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        services.revoke_refresh(get_refresh_cookie(request))
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


@extend_schema(tags=["auth"])
class RegisterView(PublicAuthView):
    @extend_schema(request=RegisterSerializer, responses={201: SessionResponse})
    def post(self, request):
        if not settings.REGISTRATION_ENABLED:
            raise Http404
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user, membership = org_services.register_organization(request=request, **s.validated_data)
        refresh = RefreshToken.for_user(user)
        return _session_response(user, refresh, status_code=status.HTTP_201_CREATED, membership=membership)


@extend_schema(tags=["auth"])
class ForgotPasswordView(PublicAuthView):
    @extend_schema(request=ForgotPasswordSerializer, responses={202: DetailResponse})
    def post(self, request):
        s = ForgotPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.request_password_reset(email=s.validated_data["email"], request=request)
        return Response(
            {"detail": "If an account exists for that email, a reset link has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(tags=["auth"])
class ResetPasswordView(PublicAuthView):
    @extend_schema(request=ResetPasswordSerializer, responses={200: DetailResponse})
    def post(self, request):
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.reset_password(request=request, **s.validated_data)
        return Response({"detail": "Your password has been reset. You can now sign in."})


@extend_schema(tags=["auth"])
class InvitationPreviewView(PublicAuthView):
    @extend_schema(request=InvitationTokenSerializer, responses={200: InvitationPreviewSerializer})
    def post(self, request):
        s = InvitationTokenSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        invitation = org_services.get_pending_invitation(s.validated_data["token"])
        return Response(
            InvitationPreviewSerializer(
                {
                    "organization_name": invitation.organization.name,
                    "email": invitation.email,
                    "role_name": invitation.role.name,
                    "existing_account": User.objects.filter(email__iexact=invitation.email).exists(),
                }
            ).data
        )


@extend_schema(tags=["auth"])
class InvitationAcceptView(PublicAuthView):
    @extend_schema(request=AcceptInvitationSerializer, responses={201: SessionResponse})
    def post(self, request):
        s = AcceptInvitationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user, membership = org_services.accept_invitation(request=request, **s.validated_data)
        refresh = RefreshToken.for_user(user)
        return _session_response(user, refresh, status_code=status.HTTP_201_CREATED, membership=membership)


@extend_schema(tags=["account"])
class MeView(APIView):
    permission_classes = [IsOrganizationMember]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(build_me(request.user, request.membership))

    @extend_schema(request=ProfileUpdateSerializer, responses=MeSerializer)
    def patch(self, request):
        s = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        services.update_profile(user=request.user, data=s.validated_data, request=request)
        return Response(build_me(request.user, request.membership))


@extend_schema(tags=["account"])
class ChangePasswordView(APIView):
    permission_classes = [IsOrganizationMember]
    throttle_classes = [AuthIPRateThrottle]

    @extend_schema(request=ChangePasswordSerializer, responses={200: AccessResponse})
    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        refresh = services.change_password(user=request.user, request=request, **s.validated_data)
        response = Response({"access": str(refresh.access_token)})
        set_refresh_cookie(response, str(refresh))
        return response
