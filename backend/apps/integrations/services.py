"""
Integration business logic.

Outbound webhooks
  domain event (after commit) → `dispatch_event` builds one envelope with a stable
  `event_id` and creates a `WebhookDelivery` per subscribed endpoint → Celery
  `deliver` POSTs it signed. Non-2xx / network errors retry on RETRY_SCHEDULE, then
  the delivery is marked failed and shown in the UI (manual redeliver available).
  Payloads carry identifiers and public fields only — never internal notes.

Inbound webhooks
  `receive` verifies size and signature, stores a `WebhookEvent` (unique per
  integration + external id, so retries by the sender are harmless) and queues
  `process_inbound`, which creates a ticket or adds a reply to one.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import logs, net, signing
from .connectors.base import ConnectorError, TestResult
from .models import Integration, IntegrationLog, WebhookDelivery, WebhookEndpoint, WebhookEvent

logger = logging.getLogger(__name__)

# Delay before attempt 2, 3, … (attempt 1 is immediate): about 15 hours in total.
RETRY_SCHEDULE = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)
MAX_ATTEMPTS = len(RETRY_SCHEDULE) + 1

EVENT_TYPES: dict[str, str] = {
    "ticket.created": "A ticket was created",
    "ticket.status_changed": "A ticket's status changed",
    "ticket.assigned": "A ticket was assigned",
    "ticket.commented": "A public reply was added to a ticket",
    "work_order.created": "A work order was created",
    "work_order.status_changed": "A work order's status changed",
    "work_order.confirmed": "A customer signed off a work order",
    "sla.warning": "An SLA target is at risk",
    "sla.breached": "An SLA target was breached",
}


# ------------------------------------------------------------------ payloads
def _ticket_data(ticket_id) -> dict | None:
    from apps.tickets.models import Ticket

    t = Ticket.objects.select_related("customer", "category", "assigned_agent").filter(pk=ticket_id).first()
    if t is None:
        return None
    return {
        "ticket": {
            "id": str(t.id),
            "reference": t.reference,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "channel": t.channel,
            "category": t.category.name if t.category_id else None,
            "customer": {"id": str(t.customer_id), "name": t.customer.name},
            "assigned_agent": t.assigned_agent.full_name if t.assigned_agent_id else None,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }
    }


def _work_order_data(wo_id) -> dict | None:
    from apps.field_service.models import WorkOrder

    wo = WorkOrder.objects.select_related("customer", "technician__user", "ticket").filter(pk=wo_id).first()
    if wo is None:
        return None
    return {
        "work_order": {
            "id": str(wo.id),
            "reference": wo.reference,
            "title": wo.title,
            "status": wo.status,
            "priority": wo.priority,
            "customer": {"id": str(wo.customer_id), "name": wo.customer.name},
            "ticket": {"id": str(wo.ticket_id), "reference": wo.ticket.reference} if wo.ticket_id else None,
            "technician": wo.technician.user.full_name if wo.technician_id else None,
            "scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
            "customer_confirmed_at": wo.customer_confirmed_at.isoformat() if wo.customer_confirmed_at else None,
        }
    }


def build_envelope(name: str, payload: dict) -> dict | None:
    """The JSON body sent to subscribers, or None when the event isn't shared (e.g. internal notes)."""
    if name == "ticket.commented" and payload.get("visibility") != "public":
        return None
    if name.startswith(("ticket.", "sla.")):
        data = _ticket_data(payload["ticket_id"])
    elif name.startswith("work_order."):
        data = _work_order_data(payload["work_order_id"])
    else:
        data = None
    if data is None:
        return None
    extra = {k: payload[k] for k in ("old_status", "new_status", "metric", "due_at", "comment_id") if k in payload}
    return {
        "id": str(uuid.uuid4()),
        "type": name,
        "created_at": timezone.now().isoformat(),
        "organization_id": payload["organization_id"],
        "data": {**data, **extra},
    }


# ------------------------------------------------------------------ outbound
def dispatch_event(name: str, payload: dict) -> list[WebhookDelivery]:
    endpoints = list(
        WebhookEndpoint.objects.filter(
            integration__organization_id=payload["organization_id"],
            integration__kind=Integration.Kind.WEBHOOK,
            integration__is_enabled=True,
            is_active=True,
            events__contains=[name],
        )
    )
    if not endpoints:
        return []
    envelope = build_envelope(name, payload)
    if envelope is None:
        return []
    deliveries = []
    for endpoint in endpoints:
        d = WebhookDelivery.objects.create(
            endpoint=endpoint, event_id=envelope["id"], event_type=name, payload=envelope
        )
        deliveries.append(d)
        transaction.on_commit(lambda pk=d.pk: _enqueue(pk))
    return deliveries


def _enqueue(delivery_id, countdown: float = 0) -> None:
    from .tasks import deliver_webhook

    deliver_webhook.apply_async(args=[str(delivery_id)], countdown=countdown)


def _post_signed(endpoint: WebhookEndpoint, envelope: dict, *, attempt: int) -> net.Response:
    body = json.dumps(envelope, separators=(",", ":")).encode()
    return net.request(
        "POST",
        endpoint.url,
        body=body,
        headers={
            "Content-Type": "application/json",
            signing.HEADER: signing.sign(endpoint.signing_secret, body),
            "X-ATT-Event": envelope["type"],
            "X-ATT-Event-Id": envelope["id"],
            "X-ATT-Attempt": str(attempt),
        },
    )


def deliver(delivery_id) -> str:
    """One delivery attempt. Returns the new status. Safe to call twice (row lock + status check)."""
    with transaction.atomic():
        d = (
            WebhookDelivery.objects.select_for_update(of=("self",))
            .select_related("endpoint__integration")
            .filter(pk=delivery_id)
            .first()
        )
        if d is None or d.status in (WebhookDelivery.Status.SUCCEEDED, WebhookDelivery.Status.FAILED):
            return d.status if d else "missing"
        endpoint, integration = d.endpoint, d.endpoint.integration
        if not (endpoint.is_active and integration.is_enabled):
            d.status, d.error = WebhookDelivery.Status.FAILED, "Endpoint or integration was disabled."
            d.save(update_fields=["status", "error", "updated_at"])
            return d.status
        d.attempts += 1
        ok, code, body, error, duration = False, None, "", "", None
        try:
            resp = _post_signed(endpoint, d.payload, attempt=d.attempts)
            code, body, duration = resp.status, resp.text[:1000], resp.duration_ms
            ok = 200 <= resp.status < 300
            if not ok:
                error = f"HTTP {resp.status}"
        except (net.UnsafeURL, net.EgressError) as exc:
            error = str(exc)
        d.response_code, d.response_body, d.error = code, body, error[:500]
        if ok:
            d.status, d.delivered_at, d.next_retry_at = WebhookDelivery.Status.SUCCEEDED, timezone.now(), None
        elif d.attempts >= MAX_ATTEMPTS:
            d.status, d.next_retry_at = WebhookDelivery.Status.FAILED, None
        else:
            d.status = WebhookDelivery.Status.RETRYING
            d.next_retry_at = timezone.now() + RETRY_SCHEDULE[d.attempts - 1]
        d.save()
        logs.record(
            integration,
            operation=f"deliver {d.event_type}",
            ok=ok,
            duration_ms=duration,
            request=f"POST {endpoint.url} (attempt {d.attempts})",
            response=f"HTTP {code}" if code else "",
            error=error,
        )
        if d.status == WebhookDelivery.Status.RETRYING:
            delay = (d.next_retry_at - timezone.now()).total_seconds()
            transaction.on_commit(lambda: _enqueue(d.pk, countdown=max(0, delay)))
    return d.status


def redeliver(delivery: WebhookDelivery) -> WebhookDelivery:
    """Manual retry from the UI: the same event (same event_id) gets a fresh set of attempts."""
    WebhookDelivery.objects.filter(pk=delivery.pk).update(
        status=WebhookDelivery.Status.PENDING, attempts=0, next_retry_at=None, error="", updated_at=timezone.now()
    )
    transaction.on_commit(lambda: _enqueue(delivery.pk))
    delivery.refresh_from_db()
    return delivery


def sweep_due(*, now=None) -> int:
    """Re-queue retries whose task was lost (broker restart). Runs every 5 minutes."""
    now = now or timezone.now()
    due = list(
        WebhookDelivery.objects.filter(
            status__in=[WebhookDelivery.Status.RETRYING, WebhookDelivery.Status.PENDING],
            next_retry_at__lte=now - timedelta(minutes=2),
        ).values_list("pk", flat=True)[:500]
    )
    stale_pending = list(
        WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.PENDING,
            next_retry_at__isnull=True,
            created_at__lte=now - timedelta(minutes=5),
        ).values_list("pk", flat=True)[:500]
    )
    for pk in {*due, *stale_pending}:
        _enqueue(pk)
    return len({*due, *stale_pending})


def send_ping(endpoint: WebhookEndpoint) -> TestResult:
    envelope = {
        "id": str(uuid.uuid4()),
        "type": "ping",
        "created_at": timezone.now().isoformat(),
        "organization_id": str(endpoint.integration.organization_id),
        "data": {"message": "Hello from ATT"},
    }
    try:
        resp = _post_signed(endpoint, envelope, attempt=1)
    except (net.UnsafeURL, net.EgressError) as exc:
        logs.record(endpoint.integration, operation="ping", ok=False, request=f"POST {endpoint.url}", error=str(exc))
        return TestResult(False, f"{endpoint.url}: {exc}")
    ok = 200 <= resp.status < 300
    logs.record(
        endpoint.integration,
        operation="ping",
        ok=ok,
        duration_ms=resp.duration_ms,
        request=f"POST {endpoint.url}",
        response=f"HTTP {resp.status}",
        error="" if ok else f"HTTP {resp.status}",
    )
    return TestResult(ok, f"{endpoint.url}: HTTP {resp.status}")


def test_connection(integration: Integration) -> TestResult:
    from .connectors import connector_for

    try:
        result = connector_for(integration).test_connection()
    except (ConnectorError, net.UnsafeURL, net.EgressError) as exc:
        result = TestResult(False, str(exc))
    if integration.kind != Integration.Kind.WEBHOOK:  # webhook pings log per endpoint
        logs.record(
            integration,
            operation="test connection",
            ok=result.ok,
            response=result.message,
            error="" if result.ok else result.message,
        )
    return result


def send_message(integration: Integration, message) -> dict:
    """Send through an SMS/WhatsApp connector, logged. Raises ConnectorError on failure."""
    from .connectors import connector_for

    if not integration.is_enabled:
        raise ConnectorError("This integration is turned off.")
    connector = connector_for(integration)
    try:
        result = connector.send(message)
    except (ConnectorError, net.UnsafeURL, net.EgressError) as exc:
        logs.record(integration, operation="send", ok=False, request=f"to {_mask(message.to)}", error=str(exc))
        raise ConnectorError(str(exc)) from exc
    logs.record(
        integration,
        operation="send",
        ok=True,
        request=f"to {_mask(message.to)}",
        response=f"{result.status} {result.provider_id}",
    )
    return {"provider_id": result.provider_id, "status": result.status}


def _mask(phone: str) -> str:
    return phone[:4] + "…" + phone[-2:] if len(phone) > 6 else "…"


# ------------------------------------------------------------------- inbound
class InboundRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def receive(integration_id, *, body: bytes, headers: dict) -> tuple[WebhookEvent, bool]:
    """Verify and store an inbound call. Returns (event, created). Raises InboundRejected."""
    if len(body) > settings.INBOUND_WEBHOOK_MAX_BYTES:
        raise InboundRejected(413, "Payload too large.")
    integration = Integration.objects.filter(pk=integration_id, kind=Integration.Kind.INBOUND).first()
    # Unknown, disabled and badly signed requests all get the same answer: don't reveal which.
    if integration is None or not integration.is_enabled:
        raise InboundRejected(401, "Invalid signature.")
    secret = integration.secret("signing_secret") or ""
    if not signing.verify(secret, headers.get(signing.HEADER.lower()), body):
        logs.record(
            integration,
            direction=IntegrationLog.Direction.INBOUND,
            operation="receive",
            ok=False,
            error="Invalid or expired signature.",
        )
        raise InboundRejected(401, "Invalid signature.")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise InboundRejected(400, "Body must be JSON.") from exc
    external_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not external_id or len(external_id) > 200:
        raise InboundRejected(400, 'Include a unique "id" (max 200 characters) so retries aren\'t processed twice.')
    kept = {k: v for k, v in headers.items() if k in ("content-type", "user-agent", "x-att-event")}
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.create(
                organization_id=integration.organization_id,
                integration=integration,
                external_id=external_id,
                headers=kept,
                payload=payload,
                signature_valid=True,
            )
    except IntegrityError:
        return WebhookEvent.objects.get(integration=integration, external_id=external_id), False
    logs.record(
        integration,
        direction=IntegrationLog.Direction.INBOUND,
        operation="receive",
        ok=True,
        request=f"id {external_id[:60]}",
    )
    transaction.on_commit(lambda: _enqueue_inbound(event.pk))
    return event, True


def _enqueue_inbound(event_id) -> None:
    from .tasks import process_inbound as task

    task.delay(str(event_id))


REFERENCE_RE = re.compile(r"\bTCK-?0*(\d{1,9})\b", re.IGNORECASE)


def process_inbound(event_id) -> str:
    """Turn a stored inbound message into a ticket or a reply. Idempotent per event."""
    with transaction.atomic():
        event = (
            WebhookEvent.objects.select_for_update(of=("self",))
            .select_related("integration")
            .filter(pk=event_id)
            .first()
        )
        if event is None or event.status != WebhookEvent.Status.RECEIVED:
            return event.status if event else "missing"
        try:
            with transaction.atomic():  # savepoint: a failure leaves no half-created ticket behind
                result = _apply_inbound(event)
            event.status, event.result = result.pop("status", WebhookEvent.Status.PROCESSED), result
        except InboundRejected as exc:
            event.status, event.error = WebhookEvent.Status.IGNORED, exc.message
        except Exception as exc:  # noqa: BLE001 - recorded on the event; the sender already got 202
            logger.exception("Inbound webhook %s failed", event_id)
            event.status, event.error = WebhookEvent.Status.FAILED, f"{type(exc).__name__}: {exc}"[:500]
        event.processed_at = timezone.now()
        event.save()
        logs.record(
            event.integration,
            direction=IntegrationLog.Direction.INBOUND,
            operation="process",
            ok=event.status != WebhookEvent.Status.FAILED,
            response=json.dumps(event.result)[:300] if event.result else event.status,
            error=event.error,
        )
    return event.status


def _creator_tenant(integration: Integration):
    from apps.organizations.models import Membership
    from apps.organizations.tenancy import TenantContext, permissions_for

    m = (
        Membership.objects.filter(user=integration.created_by, organization=integration.organization, is_active=True)
        .select_related("organization", "role")
        .first()
    )
    if m is None or "tickets.create" not in permissions_for(m):
        raise InboundRejected(0, "The person who set up this integration can no longer create tickets.")
    return TenantContext(membership=m, permissions=permissions_for(m))


def _apply_inbound(event: WebhookEvent) -> dict:
    from apps.customers.models import Customer, CustomerContact
    from apps.organizations.models import Membership
    from apps.organizations.tenancy import TenantContext, permissions_for
    from apps.tickets import services as tickets
    from apps.tickets.models import Ticket, TicketComment

    p, integration = event.payload, event.integration
    org = integration.organization
    sender = p.get("from") if isinstance(p.get("from"), dict) else {}
    email = str(sender.get("email") or "").strip().lower()
    subject = str(p.get("subject") or "").strip()[:200]
    body = str(p.get("body") or "").strip()[:20000]
    if not body:
        raise InboundRejected(0, "The message has no body.")
    contact = (
        CustomerContact.objects.filter(
            customer__organization=org, email__iexact=email, customer__archived_at__isnull=True
        )
        .select_related("customer", "user")
        .first()
        if email
        else None
    )
    staff = _creator_tenant(integration)

    # A reply: the subject or body mentions a ticket of the sender's customer.
    match = REFERENCE_RE.search(f"{subject} {body[:500]}")
    if match and contact:
        ticket = Ticket.objects.filter(
            organization=org, number=int(match.group(1)), customer=contact.customer, archived_at__isnull=True
        ).first()
        if ticket:
            portal = (
                Membership.objects.filter(user=contact.user, organization=org, is_active=True)
                .select_related("role")
                .first()
                if contact.user_id
                else None
            )
            if portal:  # the sender has a portal account: post as them (a real customer reply)
                tenant = TenantContext(membership=portal, permissions=permissions_for(portal))
                comment = tickets.add_comment(
                    tenant=tenant, ticket=ticket, body=body, visibility=TicketComment.Visibility.PUBLIC
                )
            else:  # otherwise keep it as an internal note so staff can see and answer it
                comment = tickets.add_comment(
                    tenant=staff,
                    ticket=ticket,
                    visibility=TicketComment.Visibility.INTERNAL,
                    body=f"Reply received via {integration.name} from {email}:\n\n{body}",
                    _skip_status_side_effects=True,
                )
            return {
                "action": "comment",
                "ticket_id": str(ticket.id),
                "reference": ticket.reference,
                "comment_id": str(comment.id),
            }

    customer = contact.customer if contact else None
    if customer is None and integration.config.get("default_customer_id"):
        customer = Customer.objects.filter(
            organization=org, pk=integration.config["default_customer_id"], archived_at__isnull=True
        ).first()
    if customer is None:
        raise InboundRejected(0, f"No customer contact matches {email or 'the sender'} and no default customer is set.")
    ticket = tickets.create_ticket(
        tenant=staff,
        data={
            "title": subject or body.splitlines()[0][:200] or "Message received",
            "description": body,
            "customer": customer,
            "contact": contact if contact and contact.customer_id == customer.id else None,
            "channel": integration.config.get("channel") or Ticket.Channel.API,
            "tags": ["inbound"],
        },
    )
    tickets.add_comment(
        tenant=staff,
        ticket=ticket,
        visibility=TicketComment.Visibility.INTERNAL,
        body=f"Created from {integration.name}" + (f" (sender {email})" if email else "") + ".",
        _skip_status_side_effects=True,
    )
    return {"action": "ticket", "ticket_id": str(ticket.id), "reference": ticket.reference}
