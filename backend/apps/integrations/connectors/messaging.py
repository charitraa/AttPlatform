"""
SMS and WhatsApp adapters (architecture level, Phase 7).

They implement the connector contract against the providers' public REST APIs
through the SSRF-guarded egress path, with request shapes covered by tests.
Wiring them into notification preferences comes with the channel rollout.
"""

import base64
import uuid
from urllib.parse import quote

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
    description = (
        "Send SMS through your Twilio account. Sign in with an API key (recommended: it can be revoked on its own) "
        "or with the account auth token."
    )
    fields = (Field("from_number", "From number", kind="phone", help="Your Twilio number in E.164, e.g. +14155550123"),)
    secrets = (
        Field("account_sid", "Account SID", help="Starts with AC."),
        Field("api_key_sid", "API key SID", required=False, help="Starts with SK. Use with the API key secret."),
        Field("api_key_secret", "API key secret", required=False),
        Field("auth_token", "Auth token", required=False, help="Alternative to an API key."),
    )
    can_send = True
    API = "https://api.twilio.com/2010-04-01"

    @classmethod
    def validate_secrets(cls, given: dict) -> None:
        has_key = given.get("api_key_sid") and given.get("api_key_secret")
        if not (has_key or given.get("auth_token")):
            raise ValueError({"secrets": ["Enter an API key SID and secret, or the auth token."]})
        if given.get("api_key_sid") and not str(given["api_key_sid"]).startswith("SK"):
            raise ValueError({"api_key_sid": ["API key SIDs start with SK."]})
        if given.get("account_sid") and not str(given["account_sid"]).startswith("AC"):
            raise ValueError({"account_sid": ["Account SIDs start with AC."]})

    def _auth(self) -> dict:
        key, key_secret = self.integration.secret("api_key_sid"), self.integration.secret("api_key_secret")
        if key and key_secret:  # API key: username is the key SID, URLs still use the account SID
            user, password = key, key_secret
        else:
            user, password = self.secret("account_sid"), self.secret("auth_token")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_connection(self) -> TestResult:
        # API keys can't read the account resource itself, so check the number instead (works for both).
        sid, number = self.secret("account_sid"), self.integration.config["from_number"]
        data = _ensure_ok(
            net.request(
                "GET",
                f"{self.API}/Accounts/{sid}/IncomingPhoneNumbers.json?PhoneNumber={quote(number)}",
                headers=self._auth(),
            ),
            "Twilio sign-in",
        )
        numbers = data.get("incoming_phone_numbers") or []
        if not numbers:
            raise ConnectorError(f"Signed in, but {number} isn't a number on this Twilio account.")
        if not (numbers[0].get("capabilities") or {}).get("sms"):
            raise ConnectorError(f"{number} can't send SMS.")
        return TestResult(True, f"Connected. {number} is ready to send SMS.")

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
