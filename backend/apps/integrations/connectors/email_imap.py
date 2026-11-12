import contextlib

from .base import Connector, ConnectorError, Field, TestResult, register


@register
class EmailToTicket(Connector):
    kind, provider = "email", "imap"
    label = "Email to ticket (IMAP)"
    description = (
        "Turn emails sent to one address into tickets, and replies that mention a ticket reference into replies. "
        "Checks the mailbox every 2 minutes, read-only: nothing is marked read, moved or deleted."
    )
    fields = (
        Field("host", "IMAP server", help="e.g. imap.gmail.com"),
        Field("port", "Port", required=False, help="993 (TLS) if empty"),
        Field("username", "Mailbox user name", help="Usually the full email address."),
        Field(
            "only_to",
            "Only messages sent to",
            help="Required, so a shared inbox stays private: e.g. you+att@example.com (Gmail plus-address).",
        ),
        Field("folder", "Folder", required=False, help="INBOX if empty"),
        Field(
            "default_customer_id",
            "Default customer",
            required=False,
            help="For senders who aren't a customer contact. Without it, their emails are ignored.",
        ),
    )
    secrets = (Field("password", "Password or app password", help="For Gmail: an app password, not your normal one."),)
    receives = True

    @classmethod
    def validate_config(cls, config: dict) -> dict:
        cleaned = super().validate_config(config)
        errors = {}
        if "@" not in cleaned.get("only_to", "@"):
            errors["only_to"] = ["Enter an email address."]
        port = cleaned.get("port")
        if port and (not str(port).isdigit() or not 0 < int(port) < 65536):
            errors["port"] = ["Enter a port number."]
        if errors:
            raise ValueError(errors)
        cleaned["only_to"] = cleaned["only_to"].lower()
        return cleaned

    def open(self):
        from .. import mailbox

        cfg = self.integration.config
        return mailbox.connect(cfg["host"], int(cfg.get("port") or 993), cfg["username"], self.secret("password"))

    def test_connection(self) -> TestResult:
        import imaplib

        from .. import mailbox

        cfg = self.integration.config
        try:
            client = self.open()
        except imaplib.IMAP4.error as exc:
            raise ConnectorError(f"Sign-in failed: {exc}. For Gmail, use an app password.") from exc
        try:
            found = mailbox.fetch_new(
                client, folder=cfg.get("folder") or "INBOX", only_to=cfg["only_to"], since=self.integration.created_at
            )
        except ValueError as exc:
            raise ConnectorError(str(exc)) from exc
        finally:
            with contextlib.suppress(Exception):  # closing is best effort
                client.logout()
        return TestResult(True, f"Signed in. {len(found)} new message(s) to {cfg['only_to']} since this was set up.")
