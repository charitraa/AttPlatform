# ATT Platform — Integration Roadmap

## 1. Framework (Phase 7)

`backend/apps/integrations/` provides:

- **Integration** registry rows per organization (`kind`, `provider`, non-secret
  `config`, enabled flag) and encrypted **IntegrationCredential** rows.
- **Connector interface**:

  ```python
  class Connector(Protocol):
      kind: str; provider: str
      def validate_config(self, config: dict) -> None: ...
      def test_connection(self) -> TestResult: ...
      def send(self, message: OutboundMessage) -> DeliveryResult: ...       # outbound
      def parse_inbound(self, request) -> list[InboundEvent]: ...           # inbound
      def verify_signature(self, request) -> bool: ...
  ```

- A **connector registry** mapping `(kind, provider)` → class, so a new provider is a
  new class plus registration — no changes to callers.
- **Outbound webhooks**: per-org endpoints subscribe to domain events
  (`ticket.created`, `ticket.status_changed`, `work_order.completed`, `sla.breached`…).
  Deliveries are signed, queued, retried with exponential backoff
  (1m, 5m, 30m, 2h, 12h), then marked failed and surfaced in the UI.
- **Inbound webhooks**: `/api/v1/webhooks/inbound/{integration_id}/`,
  signature-verified, stored as `WebhookEvent`, processed asynchronously and
  idempotently.
- **IntegrationLog** for every call (no secrets), error tracking with last-error
  status on the integration, and a "test connection" action.

## 2. Channels

| Integration | Phase | Notes |
|-------------|-------|-------|
| Email outbound (SMTP / provider API) | 6 | Notifications via Django email backend; console backend in dev. |
| Email inbound (ticket creation from mailbox) | 7 | IMAP poller task or provider inbound-parse webhook; threading by `Message-ID` / ticket number in subject. |
| SMS (Twilio, Vonage) | 7 (architecture), 8+ (providers) | `SmsChannel` adapter; delivery receipts via inbound webhook. |
| WhatsApp Business Cloud API | 7 (architecture), 8+ | Template messages for outbound notifications; inbound messages → ticket comments; 24-hour session window rules respected. |
| Generic REST | 7 | Configurable base URL + auth (API key / OAuth2 client credentials) for custom calls on events. |
| ITSM (ServiceNow, Jira Service Management, Zendesk) | 8+ | Bidirectional ticket sync using external ID mapping table; conflict policy: last-writer with history. |
| LLM providers | 4 | Through `apps.ai.providers`, configured as `kind=llm`. |
| Calendar (Google/Microsoft) | Backlog | Technician appointment sync. |
| Maps / geocoding | 5 | Address → coordinates for routing distance; provider adapter, cached. |

## 3. Non-goals for now

- No iPaaS-style visual workflow builder.
- No storing third-party OAuth refresh tokens until a connector requires it; when it
  does, they use the same encrypted credential store.
