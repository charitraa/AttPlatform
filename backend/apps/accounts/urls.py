from django.urls import path

from . import views

auth_urlpatterns = [
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("register/", views.RegisterView.as_view(), name="auth-register"),
    path("password/forgot/", views.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("password/reset/", views.ResetPasswordView.as_view(), name="auth-password-reset"),
    path("invitations/preview/", views.InvitationPreviewView.as_view(), name="auth-invitation-preview"),
    path("invitations/accept/", views.InvitationAcceptView.as_view(), name="auth-invitation-accept"),
]

me_urlpatterns = [
    path("", views.MeView.as_view(), name="me"),
    path("password/", views.ChangePasswordView.as_view(), name="me-password"),
]
