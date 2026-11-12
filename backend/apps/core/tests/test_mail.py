from unittest import mock

from django.core.mail import EmailMessage

from apps.core.mail import RedirectingSMTPBackend


def test_dev_redirect_sends_everything_to_one_address(settings):
    settings.EMAIL_REDIRECT_TO = "me@example.org"
    msg = EmailMessage(
        "SLA breached", "body", "from@example.org", ["ana@acme.test"], cc=["ops@acme.test"], bcc=["x@acme.test"]
    )
    with mock.patch("django.core.mail.backends.smtp.EmailBackend.send_messages", return_value=1) as send:
        assert RedirectingSMTPBackend().send_messages([msg]) == 1
    sent = send.call_args.args[0][0]
    assert sent.to == ["me@example.org"] and sent.cc == [] and sent.bcc == []
    assert sent.subject == "[dev → ana@acme.test, ops@acme.test, x@acme.test] SLA breached"
