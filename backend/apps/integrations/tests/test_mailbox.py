from datetime import timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from unittest import mock

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.integrations import mailbox, services
from apps.integrations.models import Integration, WebhookEvent
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketComment

pytestmark = pytest.mark.django_db
TO = "support+att@example.com"


def make_mail(
    *,
    to=TO,
    sender="Sita Rai <sita@bank.test>",
    subject="Printer jammed",
    body="It jams on every job.",
    html=None,
    when=None,
    headers=None,
):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, subject
    m["Message-ID"] = make_msgid(domain="bank.test")
    m["Date"] = format_datetime(when or timezone.now())
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


class FakeIMAP:
    """Records commands; serves messages by UID. Fails loudly if anything would change the mailbox."""

    def __init__(self, messages):
        self.messages = {str(i + 1).encode(): raw for i, raw in enumerate(messages)}
        self.commands = []

    def select(self, folder, readonly=False):
        self.commands.append(("select", folder, readonly))
        return "OK", [b"3"]

    def response(self, name):
        return name, [b"42"]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(self.messages)]
        if command == "FETCH":
            assert args[1] == "(BODY.PEEK[])", "must not mark messages as read"
            return "OK", [(b"1 (UID 1 BODY[] {100}", self.messages[args[0]]), b")"]
        raise AssertionError(f"unexpected IMAP command {command}")

    def logout(self):
        self.commands.append(("logout",))


@pytest.fixture
def setup(org, make_member, client_for):
    bank = Customer.objects.create(organization=org, name="Himalayan Bank")
    bank.contacts.create(name="Sita Rai", email="sita@bank.test")
    admin = make_member(org, RoleCode.ORG_ADMIN, email="admin@acme.test")
    r = client_for(admin).post(
        "/api/v1/integrations/",
        {
            "kind": "email",
            "provider": "imap",
            "name": "Support mailbox",
            "config": {
                "host": "imap.example.com",
                "username": "support@example.com",
                "only_to": "Support+ATT@example.com",
            },
            "secrets": {"password": "app-password-1234"},
        },
        format="json",
    )
    assert r.status_code == 201, r.json()
    integration = Integration.objects.get(pk=r.json()["id"])
    Integration.objects.filter(pk=integration.pk).update(created_at=timezone.now() - timedelta(hours=1))
    integration.refresh_from_db()
    return {"bank": bank, "integration": integration, "admin": admin}


def poll(integration, messages):
    fake = FakeIMAP(messages)
    with mock.patch.object(mailbox, "connect", return_value=fake):
        return services.poll_mailbox(integration), fake


# ------------------------------------------------------------------ parsing
def test_parse_prefers_plain_text_strips_quotes_and_flags_automatic_mail():
    reply = "Still broken.\n\nOn Tue, 10 Nov 2026 at 09:00, Support <s@x.com> wrote:\n> Is it fixed?\n"
    msg = mailbox.parse(make_mail(body=reply))
    assert msg.body == "Still broken." and msg.sender_email == "sita@bank.test" and TO in msg.recipients
    html_only = EmailMessage()
    html_only["From"], html_only["To"] = "a@b.test", TO
    html_only.set_content("<p>Hello</p><p>The <b>AC</b> is off</p><script>x()</script>", subtype="html")
    assert mailbox.parse(html_only.as_bytes()).body == "Hello\nThe AC is off"
    for headers in (
        {"Auto-Submitted": "auto-replied"},
        {"Precedence": "bulk"},
        {"X-ATT-Notification": "sla_breached"},
        {"List-Unsubscribe": "<mailto:x@y>"},
    ):
        assert mailbox.parse(make_mail(headers=headers)).automatic is True
    assert mailbox.parse(make_mail()).automatic is False


# ------------------------------------------------------------------ polling
def test_poll_creates_tickets_read_only_and_only_for_the_dedicated_address(setup):
    integration = setup["integration"]
    assert integration.config["only_to"] == TO  # normalised to lower case
    mails = [
        make_mail(),  # → ticket
        make_mail(to="support@example.com", subject="Personal email"),  # plain address: not ours
        make_mail(to="other+att@example.com", subject="Lookalike"),  # substring trap
        make_mail(subject="Old mail", when=timezone.now() - timedelta(days=3)),  # before set-up
        make_mail(subject="Out of office", headers={"Auto-Submitted": "auto-replied"}),
    ]
    counts, fake = poll(integration, mails)
    assert counts == {"new": 1, "duplicates": 0, "skipped": 1}
    assert ("select", '"INBOX"', True) in fake.commands  # read-only
    assert not any(c[0] in ("STORE", "COPY", "MOVE", "EXPUNGE") for c in fake.commands)
    t = Ticket.objects.get()
    assert (t.title, t.channel, t.customer, t.contact.email) == (
        "Printer jammed",
        "email",
        setup["bank"],
        "sita@bank.test",
    )

    counts, _ = poll(integration, mails)  # next poll sees the same messages
    assert counts["new"] == 0 and counts["duplicates"] == 1 and Ticket.objects.count() == 1


def test_our_own_notification_emails_never_become_tickets(setup):
    notification = make_mail(
        sender="ATT Platform <support@example.com>",
        subject="[Acme] TCK-000001 assigned to you",
        headers={"Auto-Submitted": "auto-generated", "X-ATT-Notification": "ticket_assigned"},
    )
    counts, _ = poll(setup["integration"], [notification])
    assert counts["skipped"] == 1 and not Ticket.objects.exists()


def test_reply_by_reference_and_unknown_sender(setup, org):
    ticket = Ticket.objects.create(organization=org, number=7, title="ATM", description="d", customer=setup["bank"])
    reply = make_mail(
        subject="Re: [TCK-000007] ATM", body="Works now.\n\nOn Mon, 9 Nov 2026, Support wrote:\n> Try again"
    )
    stranger = make_mail(sender="who@nowhere.test", subject="Hello")
    poll(setup["integration"], [reply, stranger])
    note = TicketComment.objects.get(ticket=ticket)
    assert note.visibility == "internal" and "Works now." in note.body and "Try again" not in note.body
    assert WebhookEvent.objects.get(payload__subject="Hello").status == "ignored"


def test_sign_in_failure_is_logged_not_raised(setup):
    import imaplib

    with mock.patch.object(mailbox, "connect", side_effect=imaplib.IMAP4.error("AUTHENTICATIONFAILED")):
        assert services.poll_mailbox(setup["integration"]) == {"new": 0, "duplicates": 0, "skipped": 0}
    setup["integration"].refresh_from_db()
    assert setup["integration"].health == "error" and "AUTHENTICATIONFAILED" in setup["integration"].last_error


def test_mailbox_host_must_be_public(setup):
    with pytest.raises(Exception, match="private"):
        mailbox.connect("127.0.0.1", 993, "u", "p")


def test_config_requires_the_dedicated_address(client_for, setup):
    r = client_for(setup["admin"]).post(
        "/api/v1/integrations/",
        {
            "kind": "email",
            "provider": "imap",
            "name": "No filter",
            "config": {"host": "imap.example.com", "username": "u@example.com"},
            "secrets": {"password": "x"},
        },
        format="json",
    )
    assert r.status_code == 400 and "only_to" in str(r.json())


def test_dates_without_a_time_zone_are_read_as_utc():
    raw = (
        make_mail()
        .replace(b"Date: ", b"X-Old-Date: ", 1)
        .replace(b"\nX-Old", b"\nDate: Thu, 12 Nov 2026 10:00:00 -0000\nX-Old", 1)
    )
    received = mailbox.parse(raw).received_at
    assert received is not None and received.tzinfo is not None
