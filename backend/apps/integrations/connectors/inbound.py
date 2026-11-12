from .base import Connector, Field, TestResult, register


@register
class GenericInbound(Connector):
    kind, provider = "inbound", "generic"
    label = "Inbound webhook (tickets)"
    description = (
        "Let another system create tickets — or add replies by mentioning a ticket reference — by POSTing signed "
        "JSON to this integration's URL."
    )
    fields = (
        Field(
            "default_customer_id",
            "Default customer",
            required=False,
            help="Used when the sender's email matches no customer contact. Without it, such messages are ignored.",
        ),
        Field(
            "channel",
            "Ticket channel",
            required=False,
            kind="choice",
            choices=("api", "email", "phone", "whatsapp"),
            help="Recorded on created tickets (default: api).",
        ),
    )
    generated_secrets = ("signing_secret",)
    receives = True

    def test_connection(self) -> TestResult:
        if not self.integration.secret("signing_secret"):
            return TestResult(False, "The signing secret is missing. Rotate it to create a new one.")
        creator = self.integration.created_by
        from apps.organizations.models import Membership
        from apps.organizations.tenancy import permissions_for

        m = Membership.objects.filter(user=creator, organization=self.integration.organization, is_active=True).first()
        if not m or "tickets.create" not in permissions_for(m):
            return TestResult(
                False,
                "Tickets are created on behalf of the person who set this up, and they can no "
                "longer create tickets. Re-save the integration as an active admin.",
            )
        return TestResult(True, "Ready to receive. Send a signed POST to the inbound URL.")
