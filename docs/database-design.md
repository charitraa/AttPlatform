# ATT Platform — Database Design

PostgreSQL 16. This document is the target schema; tables are created incrementally
per phase through Django migrations (see `development-roadmap.md`).

## 1. Conventions

| Decision | Rule |
|----------|------|
| Primary keys | `id UUID` (uuid4) on every externally exposed model. Join/through tables and append-only logs may use `BIGSERIAL` internally. |
| Human references | Tickets and work orders also have an org-scoped sequential `number` (e.g. `TCK-001042`, `WO-000318`) — unique per `(organization, number)`. |
| Timestamps | `timestamptz`, UTC storage (`USE_TZ=True`, `TIME_ZONE=UTC`). Presentation timezone comes from user/org settings. Every model has `created_at`, `updated_at`. |
| Tenancy | Every tenant-owned table has `organization_id NOT NULL` + index; uniqueness constraints are scoped by organization. |
| Money | `NUMERIC(12,2)` (`DecimalField`) plus `currency CHAR(3)`. |
| Soft delete | Tickets, customers, assets, articles use `archived_at` (nullable). Audit and history tables are never deleted. |
| Enums | Django `TextChoices` stored as `varchar`, with `CHECK` constraints. |
| Flexible data | `JSONB` only for genuinely variable payloads (AI raw output, integration config, event payloads, custom fields). Never for data we filter or join on routinely. |
| FK deletion | `PROTECT` for business references (ticket → customer), `CASCADE` only for owned children (ticket → comments), `SET_NULL` for optional actor references (history.actor). |

## 2. Entity overview

```
Organization ─┬─< Membership >── User
              ├─< Role ─< RolePermission >── Permission
              ├─< Invitation
              ├─< Customer ─┬─< CustomerContact
              │             └─< Asset ─< AssetServiceRecord
              ├─< TicketCategory (self-ref parent)
              ├─< Ticket ─┬─< TicketComment ─< TicketAttachment
              │           ├─< TicketAttachment
              │           ├─< TicketHistory
              │           ├─< TicketAssignment
              │           ├── SLAInstance ─< SLAEvent
              │           ├─< AIAnalysis ─< AIRecommendation
              │           └─< WorkOrder ─┬─< WorkOrderEvidence
              │                          ├─< WorkOrderStatusLog
              │                          └─< Appointment
              ├─< SLAPolicy ─< SLATarget ;  BusinessHours ─< Holiday
              ├─< Technician (1:1 User) ─┬─< TechnicianSkill >── Skill
              │                          ├─< TechnicianCertification
              │                          ├─< TechnicianAvailability
              │                          ├─< TechnicianLocation
              │                          └─< ServiceArea (M2M)
              ├─< KnowledgeArticle
              ├─< Notification ; NotificationPreference
              ├─< Integration ─┬─< IntegrationCredential (encrypted)
              │                ├─< WebhookEndpoint ─< WebhookDelivery
              │                └─< IntegrationLog
              ├─< WebhookEvent (inbound)
              ├─< AIInsight
              ├─< CustomerFeedback
              └─< AuditLog
```

## 3. Entities

### Identity & tenancy (`accounts`, `organizations`)

**Organization** — `id`, `name`, `slug` (unique), `timezone`, `locale`,
`settings JSONB` (routing policy, auto-close days, AI toggles), `is_active`.

**User** — custom `AbstractUser`; `id UUID`, `email` (unique, login identifier),
`first_name`, `last_name`, `phone`, `avatar`, `timezone`, `is_active`,
`email_verified_at`, `last_login`. Passwords hashed with Argon2.
A user may belong to several organizations via Membership (needed for Super Admin
and MSP-style operators); most users have exactly one.

**Membership** — `user`, `organization`, `role`, `is_active`, `joined_at`.
`UNIQUE(user, organization)`. The active organization for a request is resolved
from membership server-side.

**Role** — `organization` (NULL for system roles), `code`
(`super_admin`, `org_admin`, `ops_manager`, `support_agent`, `field_technician`,
`customer`), `name`, `is_system`. `UNIQUE(organization, code)`.

**Permission** — `code` (`tickets.view`, `tickets.assign`, `ai.override`…),
`description`. **RolePermission** — through table.

**Invitation** — `organization`, `email`, `role`, `token_hash` (SHA-256 of token;
token itself only in the email), `expires_at`, `accepted_at`, `invited_by`.

Password reset uses Django's signed, single-use token generator — no table needed.

### Customers & assets

**Customer** — a customer organization/account: `organization`, `name`, `type`
(business/individual), `email`, `phone`, `address` fields, `tier`, `notes`,
`archived_at`. Index `(organization, name)`.

**CustomerContact** — `customer`, `user` (nullable — portal login), `name`,
`email`, `phone`, `job_title`, `is_primary`.

**AssetCategory**, **Asset** — `organization`, `customer`, `category`,
`asset_tag` (`UNIQUE(organization, asset_tag)`), `name`, `manufacturer`, `model`,
`serial_number` (index), `installed_at`, `warranty_expires_at`, `location`,
`status`, `purchase_cost NUMERIC(12,2)`, `currency`.

**AssetServiceRecord** — `asset`, `work_order` (nullable), `performed_at`,
`description`, `performed_by`, `cost NUMERIC(12,2)`.

### Ticketing

**TicketCategory** — `organization`, `name`, `parent` (self FK), `department`,
`default_priority`, `required_skills` (M2M Skill). `UNIQUE(organization, parent, name)`.

**Ticket**
| Column | Notes |
|--------|-------|
| `id` UUID, `organization`, `number` | `UNIQUE(organization, number)` |
| `title`, `description` | `search_vector tsvector` (generated) + GIN index |
| `status` | new, open, assigned, in_progress, pending_customer, pending_parts, escalated, resolved, closed, reopened |
| `priority` | low, medium, high, critical |
| `priority_source` | manual, ai, policy — explains who set it |
| `category` | FK TicketCategory, nullable |
| `channel` | portal, email, phone, whatsapp, api, staff |
| `customer`, `contact`, `asset` | `PROTECT` FKs |
| `assigned_agent`, `assigned_technician` | FK User, nullable |
| `created_by` | FK User |
| `first_response_at`, `resolved_at`, `closed_at`, `due_at` | denormalised for fast SLA/analytics queries |
| `resolution_notes`, `customer_confirmed_at` | |
| `tags` | `ArrayField(varchar)` + GIN |
| `archived_at` | soft delete |

Indexes: `(organization, status)`, `(organization, priority)`,
`(organization, assigned_agent, status)`, `(organization, created_at)`,
`(organization, due_at) WHERE status NOT IN (resolved, closed)`.

**TicketComment** — `ticket`, `author`, `body`, `visibility` (`public` | `internal`),
`source` (staff, customer, ai_suggestion_accepted, system). Internal notes are
comments with `visibility=internal`, filtered out for customers at the selector level.

**TicketAttachment** — `ticket`, `comment` (nullable), `file`, `original_name`,
`content_type`, `size_bytes`, `sha256`, `uploaded_by`, `visibility`.

**TicketHistory** — append-only field-level change log: `ticket`, `actor`
(nullable for system/AI), `actor_type` (user, system, ai), `field`, `old_value`,
`new_value` (JSONB), `created_at`. Drives the activity timeline.

**TicketAssignment** — assignment history: `ticket`, `assignee`, `role`
(agent/technician), `assigned_by`, `source` (manual, ai_auto, ai_accepted),
`recommendation` (FK AIRecommendation, nullable), `assigned_at`, `unassigned_at`.

### SLA

**BusinessHours** — `organization`, `name`, `timezone`, `schedule JSONB`
(weekday → list of intervals). **Holiday** — `business_hours`, `date`, `name`.

**SLAPolicy** — `organization`, `name`, `is_default`, `business_hours`,
`conditions JSONB` (match on category/customer tier/channel), `priority_order`.

**SLATarget** — `policy`, `priority`, `first_response_minutes`,
`resolution_minutes`, `warning_threshold_pct` (e.g. 80).
`UNIQUE(policy, priority)`.

**SLAInstance** (named `SLA` in the brief) — the SLA applied to one ticket:
`ticket` (1:1), `policy`, `target` snapshot (minutes copied at apply time so policy
edits don't rewrite history), `response_due_at`, `resolution_due_at`,
`paused_at`, `paused_seconds`, `response_status`, `resolution_status`
(on_track, warning, breached, met). Indexed for the monitor:
`(resolution_status, resolution_due_at)`.

**SLAEvent** — `sla_instance`, `type` (applied, warning, breached, paused,
resumed, met, escalated), `metric` (response/resolution), `occurred_at`, `payload`.
`UNIQUE(sla_instance, type, metric)` for warning/breached to make monitoring idempotent.

### AI

**AIAnalysis** — one AI run: `organization`, `ticket` (nullable — insights may be
org-wide), `kind` (classification, priority, summary, routing, response_suggestion,
knowledge_extraction, insight), `status` (pending, running, completed, failed),
`provider`, `model`, `prompt_version`, `input_hash`, `output JSONB`,
`confidence NUMERIC(4,3)`, `reasoning TEXT`, `latency_ms`, `tokens_in`,
`tokens_out`, `error`, `is_mock BOOLEAN`, `created_at`, `completed_at`.

**AIRecommendation** — actionable output from an analysis: `analysis`, `ticket`,
`type` (category, priority, assignee, response, article), `value JSONB`,
`confidence`, `reasoning`, `status` (pending, accepted, rejected, overridden,
auto_applied, expired), `decided_by`, `decided_at`, `override_value`.
This table is the source for "AI classification accuracy" analytics
(accepted vs overridden).

**AIInsight** — org-level generated insights: `organization`, `type`
(recurring_issue, sla_risk, pattern, report), `title`, `body`, `data JSONB`,
`analysis`, `period_start`, `period_end`, `is_dismissed`.

### Knowledge

**KnowledgeArticle** — `organization`, `title`, `body` (markdown), `summary`,
`category`, `tags`, `status` (draft, in_review, published, archived),
`source` (manual, ai_extracted), `source_ticket` (nullable), `author`,
`reviewed_by`, `published_at`, `search_vector` + GIN, `helpful_count`.

### Field service

**Skill** — `organization`, `name`, `category`. `UNIQUE(organization, name)`.

**Technician** — 1:1 `user`, `organization`, `employee_id`, `status`
(available, busy, off_duty, on_leave), `home_base` (lat/lng), `max_daily_jobs`,
`hourly_cost NUMERIC(10,2)`, `currency`, `location_sharing_enabled`.

**TechnicianSkill** — `technician`, `skill`, `level` (1–5). **TechnicianCertification**
— `technician`, `name`, `issuer`, `number`, `issued_at`, `expires_at`, `document`.

**TechnicianAvailability** — `technician`, `type` (shift, time_off),
`starts_at`, `ends_at`, `recurrence` (nullable RRULE), `note`.

**TechnicianLocation** — `technician`, `lat`, `lng`, `accuracy_m`, `recorded_at`.
Only written while `location_sharing_enabled` and the technician is on an active
job; retention-limited (default 30 days) by a beat task.

**ServiceArea** — `organization`, `name`, `polygon JSONB` / postcodes;
M2M with Technician.

**WorkOrder** — `organization`, `number`, `ticket` (nullable — preventive
maintenance), `customer`, `asset`, `technician`, `status` (created, assigned,
accepted, en_route, on_site, in_progress, completed, cancelled), `priority`,
`description`, `service_address`, lat/lng, `scheduled_start`, `scheduled_end`,
`actual_start`, `actual_end`, `service_notes`, `completion_report JSONB`,
`customer_signature` (file), `customer_confirmed_at`, `labor_cost`,
`parts_cost NUMERIC(12,2)`, `currency`.

**WorkOrderStatusLog** — `work_order`, `from_status`, `to_status`, `actor`,
`lat`, `lng`, `created_at`.

**WorkOrderEvidence** — `work_order`, `kind` (before_photo, after_photo,
document, signature, other), `file`, `caption`, `sha256`, `uploaded_by`,
`captured_at`.

**Appointment** — `work_order`, `customer_contact`, `starts_at`, `ends_at`,
`status` (proposed, confirmed, rescheduled, cancelled, completed), `notes`.
Exclusion constraint (btree_gist) prevents overlapping confirmed appointments for
the same technician.

### Notifications

**Notification** — `organization`, `recipient` (User), `type`
(ticket_assigned, ticket_updated, sla_warning, sla_breached,
work_order_assigned, technician_status, customer_comment), `title`, `body`,
`data JSONB` (target IDs/links), `read_at`. Index `(recipient, read_at, created_at)`.

**NotificationDelivery** — `notification`, `channel` (in_app, email, sms,
whatsapp), `status`, `attempts`, `last_error`, `sent_at`.

**NotificationPreference** — `user`, `type`, `channel`, `enabled`.

### Integrations

**Integration** — `organization`, `kind` (email, sms, whatsapp, webhook,
rest_api, itsm, llm), `provider` (e.g. `twilio`, `smtp`, `anthropic`), `name`,
`config JSONB` (non-secret), `is_enabled`, `last_success_at`, `last_error_at`.

**IntegrationCredential** — `integration`, `key`, `ciphertext` (Fernet-encrypted
with a key from env, never returned by any API), `rotated_at`.

**WebhookEndpoint** (outbound subscriptions) — `integration`, `url`, `events`
(array), `signing_secret` (encrypted), `is_active`.
**WebhookDelivery** — `endpoint`, `event_type`, `payload`, `status`,
`attempts`, `next_retry_at`, `response_code`, `response_body` (truncated).

**WebhookEvent** (inbound) — `organization`, `integration`, `source`,
`external_id` (`UNIQUE(integration, external_id)` for idempotency), `headers`,
`payload`, `signature_valid`, `status` (received, processed, failed, ignored),
`processed_at`, `error`.

**IntegrationLog** — `integration`, `direction`, `operation`, `status`,
`duration_ms`, `request_summary`, `response_summary`, `error`. No secrets logged.

### Feedback, audit

**CustomerFeedback** — `organization`, `ticket` / `work_order`, `contact`,
`rating` (1–5, CHECK), `comment`.

**AuditLog** — append-only: `organization` (nullable for platform actions),
`actor`, `actor_type`, `action` (`ticket.updated`, `user.role_changed`,
`integration.credential_rotated`, `auth.login_failed`…), `target_type`,
`target_id`, `changes JSONB`, `ip_address`, `user_agent`, `request_id`,
`created_at`. BIGSERIAL PK; index `(organization, created_at)` and
`(target_type, target_id)`. Application DB role has no UPDATE/DELETE grant on this
table in production.

## 4. Important decisions

1. **Ticket history vs audit log** — `TicketHistory` is a domain feature (timeline
   shown to users); `AuditLog` is a security record across all entities. Both are
   written by the same service call to keep them consistent.
2. **SLA target snapshot** — copying minutes into `SLAInstance` makes historic SLA
   reports stable when policies change.
3. **AI outputs never overwrite silently** — AI writes to `AIAnalysis` /
   `AIRecommendation`. Changes to the ticket happen only through a service that
   records `priority_source`/`TicketHistory.actor_type=ai`, and only if the org's
   policy allows auto-apply. Otherwise a human accepts/overrides.
4. **Denormalised timestamps on Ticket** (`first_response_at`, `resolved_at`,
   `due_at`) trade a little write complexity for simple, indexable analytics.
5. **Shared-schema multi-tenancy** — simplest to operate; isolation enforced in the
   query layer + tests. Postgres Row Level Security is a documented hardening option
   (`security.md`).
6. **Sequential numbers per org** generated with `SELECT … FOR UPDATE` on an
   `OrganizationCounter` row inside the create transaction.
