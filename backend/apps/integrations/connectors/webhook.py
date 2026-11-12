from .base import Connector, TestResult, register


@register
class OutboundWebhooks(Connector):
    kind, provider = "webhook", "generic"
    label = "Outbound webhooks"
    description = (
        "POST signed JSON events (tickets, work orders, SLA) to your own endpoints. "
        "Retried with backoff for about 15 hours."
    )

    def test_connection(self) -> TestResult:
        from ..services import send_ping

        endpoints = list(self.integration.endpoints.filter(is_active=True))
        if not endpoints:
            return TestResult(False, "Add an active endpoint first.")
        results = [send_ping(e) for e in endpoints]
        failed = [r for r in results if not r.ok]
        if failed:
            return TestResult(False, "; ".join(r.message for r in failed)[:400])
        return TestResult(True, f"{len(results)} endpoint(s) answered the ping.")
