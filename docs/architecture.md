# ATT Platform — System Architecture

ATT is an AI-driven ticketing and field-service management platform. This document
describes the system architecture, module boundaries, communication paths, and the
reasoning behind the main technical decisions.

---

## 1. Architectural style: modular monolith

ATT starts as a **modular monolith**: one Django project, one PostgreSQL database,
one deployable backend image, split internally into domain apps with explicit
boundaries. Microservices are deliberately avoided until a module has a proven,
independent scaling or release requirement.

Rules that keep the monolith modular:

1. **Each domain is a Django app** under `backend/apps/<domain>/`.
2. **Business logic lives in `services.py`**, never in views or serializers.
   Views validate input → call a service → serialize output.
3. **Cross-module calls go through the other module's services or selectors**,
   not by reaching into its models' internals or writing to its tables.
4. **Side effects that cross modules are published as domain events**
   (`apps.core.events`) — e.g. `ticket.created` is consumed by the AI, SLA and
   notification modules. This keeps the ticketing module unaware of its consumers.
5. **All tenant-owned models carry an `organization` FK** and are queried through
   organization-scoped managers/querysets.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                               Browser                                    │
│   React SPA (Vite build) — staff app, technician mobile UI, customer     │
│   portal — TanStack Query (REST), WebSocket client (real-time)           │
└───────────────┬─────────────────────────────────────┬────────────────────┘
                │ HTTPS  /api/v1/*                    │ WSS  /ws/*
┌───────────────▼─────────────────────────────────────▼────────────────────┐
│                         Nginx (reverse proxy)                            │
│   static SPA files · /api → backend · /ws → backend (upgrade) · /media   │
│   request size limits · security headers · gzip                          │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│                Backend — Django ASGI app (Daphne)                        │
│                                                                          │
│  DRF API layer (/api/v1)          Channels consumers (/ws)               │
│  ── auth (JWT) ─ permissions (RBAC + org scope) ─ throttling ──          │
│                                                                          │
│  Domain apps (services / selectors / models)                             │
│  accounts · organizations · customers · assets · tickets · sla           │
│  ai · knowledge · field_service · notifications · integrations           │
│  analytics · audit · core                                                │
│                                                                          │
│  core.events  ──►  in-process domain event bus  ──► Celery tasks         │
└──────┬──────────────────────┬───────────────────────────┬────────────────┘
       │                      │                           │
┌──────▼──────┐      ┌────────▼────────┐        ┌─────────▼───────────────┐
│ PostgreSQL  │      │     Redis       │        │  Celery worker / beat   │
│ system of   │      │ Celery broker,  │◄───────┤  AI jobs, SLA monitor,  │
│ record      │      │ Channels layer, │        │  notifications, webhook │
│             │      │ cache, throttle │        │  delivery + retries     │
└─────────────┘      └─────────────────┘        └─────────┬───────────────┘
                                                          │
                                         ┌────────────────▼───────────────┐
                                         │ External providers (adapters)  │
                                         │ LLM APIs · SMTP · SMS ·        │
                                         │ WhatsApp · webhooks · ITSM     │
                                         └────────────────────────────────┘
```

---

## 2. Runtime components

| Component      | Technology                         | Responsibility |
|----------------|------------------------------------|----------------|
| Frontend       | React 19, TypeScript, Vite, Tailwind, shadcn/ui | SPA for staff, technicians (mobile-optimised routes) and customers (portal routes). |
| Reverse proxy  | Nginx                              | TLS termination (prod), static assets, routing `/api`, `/ws`, `/media`, upload limits, security headers. |
| Backend        | Django 5.2 LTS, DRF, Channels, Daphne | REST API, WebSockets, admin, business logic. |
| Worker         | Celery 5                           | Asynchronous AI processing, notification fan-out, webhook delivery, report generation. |
| Scheduler      | Celery beat (django-celery-beat)   | Periodic jobs: SLA monitoring, insight generation, retry sweeps. |
| Database       | PostgreSQL 16                      | System of record; full-text search; JSONB for AI payloads. |
| Cache / broker | Redis 7                            | Celery broker + result backend, Channels layer, cache, throttle counters. |
| File storage   | Local volume (dev) / S3-compatible (prod) via `django-storages` | Attachments, evidence photos, generated reports. |

### Why these choices

- **Django + DRF**: mature ORM and migrations, admin for ops, robust auth/permissions.
- **ASGI (Daphne) for one process type** handling both HTTP and WebSockets keeps
  deployment simple. In production HTTP can be split to Gunicorn+Uvicorn workers if
  needed without code change.
- **PostgreSQL full-text search** covers ticket/knowledge search initially;
  `pgvector` is the planned upgrade path for semantic similarity (see `ai-engine.md`).
- **Redis** is used for four roles; at scale these can be split into separate
  instances via environment variables alone.

---

## 3. Backend module map

```
backend/
├── config/                 # project: settings (base/dev/test/prod), urls, asgi, celery
└── apps/
    ├── core/               # base models, exceptions, pagination, events, health, utils
    ├── accounts/           # User, auth flows, JWT, invitations, password reset, profile
    ├── organizations/      # Organization, membership, roles, permissions, settings
    ├── audit/              # AuditLog — append-only, written via service + signals
    ├── customers/          # Customer, CustomerContact, portal access, feedback
    ├── assets/             # Asset, AssetCategory, maintenance/service records
    ├── tickets/            # Ticket, categories, comments, attachments, history, assignment
    ├── sla/                # SLAPolicy, business hours, SLA instances, events, escalation
    ├── ai/                 # provider abstraction, AIAnalysis, AIRecommendation, AI tasks
    ├── knowledge/          # KnowledgeArticle, extraction from resolved tickets, review
    ├── field_service/      # Technician, skills, availability, WorkOrder, evidence, appointments
    ├── notifications/      # Notification, channels (in-app/email/SMS/WhatsApp), preferences
    ├── integrations/       # Integration config, encrypted credentials, webhooks, logs
    └── analytics/          # read-only aggregation selectors, dashboard + reports, CSV export
```

Each app follows the same internal layout:

```
apps/<domain>/
├── models.py         # data + invariants (constraints, indexes)
├── services.py       # write-side business logic, transactions, events
├── selectors.py      # read-side query logic (org-scoped)
├── serializers.py    # API input/output shapes only
├── views.py          # DRF viewsets / APIViews — thin
├── permissions.py    # DRF permission classes for the domain
├── tasks.py          # Celery tasks (thin wrappers around services)
├── urls.py           # router registration
├── admin.py
└── tests/
```

### Module dependency direction

Lower layers must not import from higher layers.

```
core  ◄── accounts, organizations, audit
              ▲
   customers, assets
              ▲
           tickets  ◄── sla, field_service, knowledge
              ▲
     ai (reads tickets/knowledge/field_service via selectors)
              ▲
 notifications, integrations (consume events from everything)
              ▲
          analytics (read-only over everything)
```

When a lower module needs a reaction from a higher one (e.g. tickets → AI
classification), it **emits an event**; the higher module subscribes. Event
handlers that do I/O enqueue Celery tasks *on transaction commit*
(`transaction.on_commit`) so workers never see uncommitted rows.

---

## 4. Communication

### 4.1 Frontend ↔ Backend: REST

- Versioned under `/api/v1/`. See `api-documentation.md`.
- JSON only; consistent error envelope produced by a central exception handler.
- JWT: short-lived access token (15 min) in memory; refresh token (7 days) rotated
  on use with blacklist-after-rotation. See `security.md` for storage decisions.
- OpenAPI 3 schema generated by drf-spectacular at `/api/v1/schema/`, Swagger UI at
  `/api/v1/docs/`. The frontend can generate types from this schema.

### 4.2 Frontend ↔ Backend: real-time

- WebSocket endpoint `/ws/events/` authenticated with a short-lived JWT passed as
  a query parameter on connect (browsers can't set WS headers), validated server-side.
- On connect the consumer joins groups derived **server-side** from the user:
  `user.<id>`, `org.<id>`, and role-specific groups (e.g. `org.<id>.dispatch`).
- Server pushes typed events: `notification.created`, `ticket.updated`,
  `work_order.status_changed`, `sla.warning`, `ai.analysis.completed`.
- The client uses events to invalidate TanStack Query caches rather than treating
  WS payloads as the source of truth — REST remains authoritative.

### 4.3 Backend ↔ Workers

- Celery over Redis. Tasks receive IDs, never model instances, and re-load inside
  the task with organization scope.
- AI, notification and webhook tasks are idempotent and retried with exponential
  backoff; terminal failures are recorded (`AIAnalysis.status=failed`,
  `IntegrationLog`, `WebhookDelivery.status=failed`).

### 4.4 Backend ↔ External providers

All external calls go through **adapter interfaces** in the owning module:

- `apps.ai.providers.base.AIProvider` — `MockProvider`, `AnthropicProvider`,
  `OpenAICompatibleProvider`.
- `apps.notifications.channels.base.Channel` — in-app, email, SMS, WhatsApp.
- `apps.integrations.connectors.base.Connector` — webhooks, REST, ITSM systems.

Providers are selected by configuration (environment for platform defaults,
per-organization `Integration` rows for tenant-specific credentials). Business logic
depends only on the interface.

---

## 5. Multi-tenancy and authorization

- **Tenant = Organization.** Shared database, shared schema, row-level isolation via
  an `organization_id` column on every tenant-owned table.
- The active organization is resolved **from the authenticated user's membership**,
  never from a client-supplied ID. Super Admins can act across organizations through
  explicit, audited admin endpoints.
- Base `OrganizationScopedViewSet` filters every queryset by `request.organization`
  and injects it on create; serializers never accept `organization` as input.
- RBAC: six system roles (Super Admin, Organization Admin, Operations Manager,
  Support Agent, Field Technician, Customer) map to a permission set of
  `<resource>.<action>` codes. Permission checks happen in DRF permission classes
  *and* in services for critical actions (defence in depth).
- Object-level rules: technicians see only work orders assigned to them; customers
  see only their own customer account's tickets, and never internal notes.

Details in `security.md`.

---

## 6. Key workflows (cross-module view)

| Workflow | Path through modules |
|----------|----------------------|
| Ticket creation | `tickets.services.create_ticket` → `ticket.created` event → `sla` applies policy (sync, same transaction) → `ai` enqueues classification + priority (async) → `ai` stores `AIAnalysis` → routing recommendation → auto-assign or wait for human approval per org policy → `notifications` informs assignee. |
| AI routing | `ai.services.recommend_routing` reads candidates via `organizations`/`field_service` selectors (skills, availability, workload, location) → deterministic scoring + LLM explanation → `AIRecommendation` (pending/accepted/rejected). |
| Field service | `tickets` → `field_service.services.create_work_order` → assign technician → `Appointment` → status transitions (state machine) → evidence uploads → completion report → customer confirmation → ticket resolution. |
| SLA monitoring | beat runs `sla.tasks.scan_sla_instances` every minute → computes business-time remaining → emits `sla.warning` / `sla.breached` → `SLAEvent` rows → escalation service updates ticket + notifies. |
| Resolution | resolution notes → customer confirmation (portal/email) → `resolved` → auto-close after N days (beat) → `closed`. |
| Knowledge improvement | `ticket.closed` → `knowledge` enqueues AI extraction → draft `KnowledgeArticle` (status=draft, source_ticket) → human review → published → used by knowledge assistant. |

Status transitions for tickets and work orders are enforced by explicit state
machines in services (allowed-transition maps), not by free-form status updates.

---

## 7. Configuration

- All configuration comes from environment variables (`django-environ`), with
  `.env.example` documenting every key. No secrets in the repository.
- Settings modules: `config.settings.base`, `.dev`, `.test`, `.prod`, selected by
  `DJANGO_SETTINGS_MODULE`.
- Frontend config uses `VITE_*` variables containing **only public values**
  (API base URL, WS URL). No provider keys ever reach the frontend.

---

## 8. Observability

- Structured logging (JSON in prod, readable in dev) with a request ID propagated via
  `X-Request-ID` and attached to log records, error responses and Celery tasks.
- `/api/v1/health/` (liveness) and `/api/v1/health/ready/` (DB + Redis readiness).
- Error tracking hook (Sentry DSN optional via env).
- Integration and AI calls log latency, provider, model and outcome.

---

## 9. Scaling path

1. Scale backend and worker containers horizontally (stateless; sessions are JWT).
2. Dedicated Celery queues: `ai`, `notifications`, `webhooks`, `default`, `sla`.
3. Split Redis roles; add read replica for analytics queries.
4. `pgvector` for semantic search; materialised views for heavy analytics.
5. Only then consider extracting a module (most likely `ai` or `integrations`) into
   a separate service — its adapter boundary already exists.
