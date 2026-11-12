"""
Development safety net for real SMTP.

With EMAIL_REDIRECT_TO set (dev only), every outgoing email goes to that one
address instead of its recipients, with the intended recipients in the subject.
Demo users have made-up addresses (…@acme.test): without this, real SMTP would
try to deliver to them and the bounces would land in the sender's inbox.
"""

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend


class RedirectingSMTPBackend(EmailBackend):
    def send_messages(self, email_messages):
        target = settings.EMAIL_REDIRECT_TO
        for message in email_messages:
            original = [*message.to, *message.cc, *message.bcc]
            message.to, message.cc, message.bcc = [target], [], []
            message.subject = f"[dev → {', '.join(original)}] {message.subject}"
        return super().send_messages(email_messages)
