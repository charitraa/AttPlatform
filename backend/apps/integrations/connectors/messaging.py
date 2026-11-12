"""
SMS and WhatsApp adapters (architecture level, Phase 7).

They implement the connector contract against the providers' public REST APIs
through the SSRF-guarded egress path, with request shapes covered by tests.
Wiring them into notification preferences comes with the channel rollout.
"""

import base64
import uuid

from .. import net
from .base import Connector, ConnectorError, Field, OutboundMessage, SendResult, TestResult, register


def _ensure_ok(resp: net.Response, what: str) -> dict:
    try:
        data = resp.json() or {}
    except ValueError:
        data = {}
    if resp.status >= 400:
        detail = (
            (data.get("message") or (data.get("error") or {}).get("message") or "") if isinstance(data, dict) else ""
        )
        raise ConnectorError(f"{what} failed (HTTP {resp.status}){': ' + str(detail)[:200] if detail else ''}.")
    return data if isinstance(data, dict) else {}


@register
class ConsoleSMS(Connector):
    kind, provider = "sms", "console"
    label = "SMS (development log)"
    description = "Doesn't send anything: records each message in the integration log. For demos and testing."
    fields = (Field("from_number", "Sender ID", required=False),)
    can_send = True

    def test_connection(self) -> TestResult:
        return TestResult(True, "Messages will appear in this integration's log.")

    def send(self, message: OutboundMessage) -> SendResult:
        return SendResult(provider_id=f"console-{uuid.uuid4().hex[:12]}", status="logged")


@register
class TwilioSMS(Connector):
    kind, provider = "sms", "twilio"
    label = "SMS via Twilio"
    description = "Send SMS through your Twilio account."
    fields = (Field("from_number", "From number", kind="phone", help="E.164, e.g. +97798XXXXXXXX"),)
    secrets = (Field("account_sid", "Account SID"), Field("auth_token", "Auth token"))
    can_send = True
    API = "https://api.twilio.com/2010-04-01"

    def _auth(self) -> dict:
        token = base64.b64encode(f"{self.secret('account_sid')}:{self.secret('auth_token')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_connection(self) -> TestResult:
        sid = self.secret("account_sid")
        data = _ensure_ok(net.request("GET", f"{self.API}/Accounts/{sid}.json", headers=self._auth()), "Twilio sign-in")
        return TestResult(True, f"Connected to Twilio account “{data.get('friendly_name', sid)}”.")

    def send(self, message: OutboundMessage) -> SendResult:
        sid = self.secret("account_sid")
        resp = net.post_form(
            f"{self.API}/Accounts/{sid}/Messages.json",
            {"To": message.to, "From": self.integration.config["from_number"], "Body": message.text},
            headers=self._auth(),
        )
        data = _ensure_ok(resp, "Sending the SMS")
        return SendResult(provider_id=data.get("sid", ""), status=data.get("status", "queued"))


@register
class WhatsAppCloud(Connector):
    kind, provider = "whatsapp", "meta_cloud"
    label = "WhatsApp Business (Cloud API)"
    description = (
        "Send approved WhatsApp template messages. Free-form text is only allowed within 24 hours of the customer's "
        "last message, so notifications use templates."
    )
    fields = (
        Field("phone_number_id", "Phone number ID", help="From WhatsApp Manager → API setup."),
        Field("language", "Template language", required=False, help="e.g. en_US (default)"),
    )
    secrets = (Field("access_token", "Access token"),)
    can_send = True
    API = "https://graph.facebook.com/v21.0"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret('access_token')}"}

    def test_connection(self) -> TestResult:
        pid = self.integration.config["phone_number_id"]
        data = _ensure_ok(
            net.request("GET", f"{self.API}/{pid}?fields=display_phone_number,verified_name", headers=self._headers()),
            "WhatsApp sign-in",
        )
        return TestResult(
            True, f"Connected as {data.get('verified_name', '')} {data.get('display_phone_number', '')}".strip()
        )

    def send(self, message: OutboundMessage) -> SendResult:
        if not message.template:
            raise ConnectorError("WhatsApp notifications must use an approved template.")
        pid = self.integration.config["phone_number_id"]
        body = {
            "messaging_product": "whatsapp",
            "to": message.to.lstrip("+"),
            "type": "template",
            "template": {
                "name": message.template,
                "language": {"code": self.integration.config.get("language") or "en_US"},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": v} for v in message.variables]}]
                if message.variables
                else [],
            },
        }
        data = _ensure_ok(
            net.post_json(f"{self.API}/{pid}/messages", body, headers=self._headers()), "Sending the message"
        )
        return SendResult(provider_id=((data.get("messages") or [{}])[0]).get("id", ""), status="accepted")
