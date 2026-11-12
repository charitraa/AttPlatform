"""
Connector interface and registry.

A connector is the code for one `(kind, provider)`. Adding a provider is a new
class decorated with `@register`; callers (API, tasks) never change. Connectors
describe their settings (`fields`) and secrets (`secrets`) so the API can validate
them and the UI can render a form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


class ConnectorError(Exception):
    """Expected failure talking to a provider (shown to admins; never contains secrets)."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    required: bool = True
    help: str = ""
    kind: str = "string"  # string | url | phone | choice
    choices: tuple[str, ...] = ()


@dataclass
class TestResult:
    ok: bool
    message: str


@dataclass
class OutboundMessage:
    to: str
    text: str = ""
    template: str = ""
    variables: list[str] = field(default_factory=list)


@dataclass
class SendResult:
    provider_id: str
    status: str = "queued"


class Connector:
    kind: ClassVar[str]
    provider: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    fields: ClassVar[tuple[Field, ...]] = ()
    secrets: ClassVar[tuple[Field, ...]] = ()
    # Secrets the server generates (e.g. an inbound signing secret), shown to the admin once.
    generated_secrets: ClassVar[tuple[str, ...]] = ()
    can_send: ClassVar[bool] = False
    receives: ClassVar[bool] = False

    def __init__(self, integration):
        self.integration = integration

    @classmethod
    def validate_config(cls, config: dict) -> dict:
        """Return the cleaned config or raise ValueError(field-keyed dict)."""
        errors, cleaned = {}, {}
        for f in cls.fields:
            value = config.get(f.name, "")
            value = value.strip() if isinstance(value, str) else value
            if f.required and not value:
                errors[f.name] = ["This field is required."]
            elif value and f.choices and value not in f.choices:
                errors[f.name] = [f"Choose one of: {', '.join(f.choices)}."]
            elif value:
                cleaned[f.name] = value
        unknown = set(config) - {f.name for f in cls.fields}
        if unknown:
            errors["config"] = [f"Unknown settings: {', '.join(sorted(unknown))}."]
        if errors:
            raise ValueError(errors)
        return cleaned

    @classmethod
    def validate_secrets(cls, given: dict) -> None:
        """Cross-field checks on secrets at creation (raise ValueError(field-keyed dict))."""

    def secret(self, name: str) -> str:
        value = self.integration.secret(name)
        if not value:
            raise ConnectorError(f"The {name.replace('_', ' ')} isn't set.")
        return value

    def test_connection(self) -> TestResult:
        raise NotImplementedError

    def send(self, message: OutboundMessage) -> SendResult:
        raise ConnectorError(f"{self.label} can't send messages.")


_REGISTRY: dict[tuple[str, str], type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[(cls.kind, cls.provider)] = cls
    return cls


def connector_class(kind: str, provider: str) -> type[Connector] | None:
    return _REGISTRY.get((kind, provider))


def connector_for(integration) -> Connector:
    cls = connector_class(integration.kind, integration.provider)
    if cls is None:
        raise ConnectorError(f"No connector for {integration.kind}/{integration.provider}.")
    return cls(integration)


def catalog() -> list[type[Connector]]:
    return sorted(_REGISTRY.values(), key=lambda c: (c.kind, c.label))
