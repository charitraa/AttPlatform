# ATT Platform — API Documentation

The authoritative, always-current contract is the generated OpenAPI 3 schema:

| URL | Content |
|-----|---------|
| `/api/v1/schema/` | OpenAPI 3 schema (YAML; `?format=json` for JSON) |
| `/api/v1/docs/` | Swagger UI |
| `/api/v1/redoc/` | ReDoc |

This document describes conventions and the planned endpoint map. Endpoints are
marked with the phase in which they are delivered.

## 1. Conventions

- **Base path**: `/api/v1/`. Breaking changes require `/api/v2/`.
- **Format**: JSON, `snake_case` fields, ISO-8601 UTC timestamps (`2026-11-11T18:00:00Z`).
- **IDs**: UUID strings. Tickets/work orders also expose `number` (`TCK-001042`).
- **Auth**: `Authorization: Bearer <access_token>`.
- **Organization**: never sent by the client; derived from the authenticated user.
  (Users with several memberships send `X-Organization: <slug>`, which is
  *validated against their memberships* server-side.)
- **Request ID**: clients may send `X-Request-ID`; the server always returns one.

### Pagination

Page-number pagination, `?page=2&page_size=25` (max 100):

```json
{ "count": 132, "next": "…?page=3", "previous": "…?page=1", "results": [ … ] }
```

### Filtering, search, ordering

- Filters as query params: `?status=open&priority=high,critical&assigned_agent=<uuid>`
- Date ranges: `?created_after=2026-11-01&created_before=2026-11-30`
- Search: `?search=router offline`
- Ordering: `?ordering=-created_at` (whitelisted fields only)

### Errors

All errors share one envelope (central exception handler):

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid input.",
    "details": { "title": ["This field is required."] },
    "request_id": "6f1c…"
  }
}
```

| HTTP | `code` examples |
|------|-----------------|
| 400 | `validation_error`, `invalid_transition` |
| 401 | `not_authenticated`, `token_not_valid` |
| 403 | `permission_denied` |
| 404 | `not_found` (also returned for other organizations' resources — no existence leak) |
| 409 | `conflict` |
| 429 | `throttled` |
| 500 | `server_error` (no internals exposed) |
| 503 | `service_unavailable` (e.g. readiness check failure) |

### Rate limits

| Scope | Default | Applies to |
|-------|---------|------------|
| `anon` / `user` | 30/min / 600/min | everything without a narrower scope |
| `auth` | 5/min per IP+email | login, register, password forgot/reset, invitation preview/accept |
| `auth_ip` | 30/min per IP | the same endpoints across all emails, plus change-password |
| `session` | 60/min | token refresh (called on every page load) |
| `system` | 120/min | health, readiness, meta (polled by the UI) |
| `ai` | 30/min per user | AI endpoints (Phase 4) |

Clients are identified by IP. Behind a reverse proxy set `NUM_PROXIES`, or every
client shares the proxy's address (and one bucket). All values are env-configurable.

## 2. Endpoint map

### System (Phase 1)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/` | Liveness. Public. |
| GET | `/health/ready/` | Readiness: database + Redis. Public, no internals. |
| GET | `/meta/` | Public client config: app version, environment, enabled features. |

### Auth & accounts (Phase 2 ✅)

Session model: `login` returns the **access token in the body** (keep it in
memory) and sets the **refresh token as an HttpOnly cookie** (`att_refresh`,
`Path=/api/v1/auth/`, `SameSite=Strict`, `Secure` outside debug). The refresh
token is never present in a response body.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login/` | — | `{email, password}` → `{access, user}` + refresh cookie. 401 `invalid_credentials` for any failure (unknown email, wrong password, inactive, no membership). Throttled per IP+email and per IP. |
| POST | `/auth/refresh/` | cookie | Rotates the cookie (old token blacklisted) → `{access}`. 401 `session_expired` clears the cookie. |
| POST | `/auth/logout/` | cookie | Blacklists the refresh token, clears the cookie. 204. |
| POST | `/auth/register/` | — | Only when `REGISTRATION_ENABLED`; otherwise 404. Creates org + Organization Admin. 409 if email exists. |
| POST | `/auth/password/forgot/` | — | `{email}` → always 202 (no account enumeration). Emails a single-use link valid for `PASSWORD_RESET_TIMEOUT`. |
| POST | `/auth/password/reset/` | — | `{uid, token, new_password}`. Revokes every session of the user. |
| POST | `/auth/invitations/preview/` | — | `{token}` → `{organization_name, email, role_name, existing_account}`. |
| POST | `/auth/invitations/accept/` | — | `{token, password, first_name?, last_name?}` → `{access, user}` + cookie. Existing accounts must supply their current password. |
| GET/PATCH | `/me/` | bearer | Profile + active organization, role, permission codes, memberships. PATCH: `first_name`, `last_name`, `phone`, `timezone`. |
| POST | `/me/password/` | bearer | `{current_password, new_password}` → `{access}` + new cookie; all other sessions revoked. |

### Organization & users (Phase 2 ✅)
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET / PATCH | `/organization/` | `organization.view` / `organization.manage` | Current org. `settings` accepts only `routing_policy` (`manual`/`recommend`/`auto`), `ai_enabled`, `ticket_auto_close_days` (1–90); unknown keys → 400. `slug` is read-only. |
| GET | `/users/` | `users.view` | Members of the current org. Filters: `role`, `is_active`; `search` (name/email); `ordering`. |
| GET / PATCH / DELETE | `/users/{user_id}/` | `users.view` / `users.manage` | PATCH `{role?, is_active?}`. DELETE deactivates (memberships are never hard-deleted). Rules: no self-changes (400); can't grant a role above your own or manage a higher-ranked user (403); Super Admin only by Super Admins; the last active admin can't be demoted/deactivated (400). Deactivation revokes the user's sessions. |
| GET / POST | `/invitations/` | `invitations.manage` | Filter `status` = `pending`/`accepted`/`expired`/`revoked`. POST `{email, role}`; 409 if already a member or an open invitation exists. |
| DELETE | `/invitations/{id}/` | `invitations.manage` | Revoke. |
| POST | `/invitations/{id}/resend/` | `invitations.manage` | New token and expiry; the old link stops working. |
| GET | `/roles/` | `roles.view` | System roles with permission codes and `assignable` (whether the caller may grant it). |
| GET | `/audit-logs/` | `audit.view` | Org-scoped audit trail. Filters: `action` (prefix), `actor`, `target_type`, `target_id`, `created_after`, `created_before`. |

### Dashboard (Phase 3 ✅)
All dashboard figures are computed from the tickets the caller can see (`tickets.view_all`
or `tickets.view_own`). `?days=` is clamped to 7–180 (default 30).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard/summary/` | Counts (total, open, new, in progress, resolved, closed, overdue, critical open, unassigned open, created/resolved in period) and average resolution / first-response hours. Metrics owned by unbuilt modules (`sla_compliance`, `technicians_available`, `active_work_orders`) are `null`, with the reason in `unavailable`. |
| GET | `/dashboard/trends/` | One row per day `{date, created, resolved}`, bucketed in the organization's timezone. |
| GET | `/dashboard/breakdown/` | Status counts, open tickets by priority, top 8 categories. |
| GET | `/dashboard/workload/` | Per-agent open / resolved / average resolution (`tickets.view_all`). |
| GET | `/dashboard/activity/` | Latest 15 history events (internal events hidden from customers). |

### Tickets (Phase 3 ✅)

**Visibility:** `tickets.view_all` sees every ticket in the organization. Technicians
(`tickets.view_own`) see tickets assigned to them or raised by them. Customer-portal
users see their customer account's tickets. Anything else returns 404. Internal notes,
internal attachments and internal history events need `tickets.internal_notes`.

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/tickets/` | view | Filters: `status` (comma list or `active`), `priority` (comma list), `category`, `customer`, `asset`, `assigned_agent` / `assigned_technician` (user ID, `me`, `none`), `created_after`, `created_before`, `overdue`, `tag`, `archived` (`false` default, `true`, `all`). `search`: full text over title + description, partial title or customer name, or a ticket number (`TCK-42`, `42`). `ordering`: `created_at`, `updated_at`, `due_at`, `number`, `status`, `priority` (by severity). |
| POST | `/tickets/` | `tickets.create` | `{title, description, customer, contact?, asset?, category?, priority?, channel?, tags?}`. Contact and asset must belong to the customer. Customer-portal users may omit `customer` (their linked account is used); their `priority` is ignored in favour of the category default. |
| GET / PATCH | `/tickets/{id}/` | view / `tickets.update` | PATCH: `title`, `description`, `priority`, `category`, `contact`, `asset`, `tags`. Every changed field is written to history; a priority change sets `priority_source=manual`. Detail includes `allowed_transitions` and `capabilities` for the caller. |
| POST | `/tickets/{id}/transition/` | `tickets.update` (customers: `portal.access`) | `{status, note?, resolution_notes?}`. Checked against the state machine (`apps/tickets/lifecycle.py`); otherwise 400 `invalid_transition`. `resolved` requires resolution notes. Customers may only move `resolved` → `closed` (confirms the resolution) or `reopened`. |
| POST | `/tickets/{id}/assign/` | `tickets.assign` | `{agent?, technician?}`: omit to leave unchanged, `null` to unassign. Agents must hold an agent-capable role and technicians the technician role, in this organization. Assigning an agent moves `new`/`open`/`reopened` tickets to `assigned`. |
| POST | `/tickets/{id}/escalate/` | `tickets.update` | `{reason}`, recorded as an internal note. |
| POST | `/tickets/{id}/archive/` · `/unarchive/` | `tickets.archive` | Archived tickets are hidden from lists and frozen. Tickets are never hard-deleted through the API. |
| GET / POST | `/tickets/{id}/comments/` | view | `{body, visibility: public\|internal}`. The first public staff reply sets `first_response_at`; a customer reply on `pending_customer` moves the ticket back to the team. |
| GET / POST | `/tickets/{id}/attachments/` | view | Multipart `file` + `visibility`. Up to `MAX_UPLOAD_SIZE_MB`; extension allow-list; content sniffed with libmagic and must match the extension; SVG and executables rejected. |
| GET | `/tickets/{id}/attachments/{aid}/download/` | view | Authenticated stream with `Content-Disposition: attachment` (`?inline=1` allowed only for PNG/JPEG/WebP/GIF), `nosniff` and a sandboxing CSP. |
| GET | `/tickets/{id}/history/` | view | Field-level timeline. |
| GET / POST / PATCH / DELETE | `/ticket-categories/` | read: `organization.view`; write: `organization.manage` | Deleting a category that's in use deactivates it instead. |

### Customers & assets (Phase 3 ✅)
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET / POST / PATCH | `/customers/` | `customers.view` / `customers.manage` | Search: name, email, phone, city, contact name/email. Filters: `type`, `tier`, `archived`. Includes `open_ticket_count`, `asset_count`, `primary_contact`. Active names are unique per organization (case-insensitive). |
| DELETE / POST `restore/` | `/customers/{id}/` | `customers.manage` | DELETE archives; restore un-archives. |
| GET / POST / PATCH / DELETE | `/customers/{id}/contacts/` | same | Setting `is_primary` clears the previous primary contact. |
| GET / POST / PATCH / DELETE | `/assets/` | `assets.view` / `assets.manage` | Filters: `customer`, `category`, `status`, `warranty` (`active`/`expired`). Tags are upper-cased and unique per organization. Assets that have tickets can't be deleted (409); retire them instead. |
| GET / POST | `/asset-categories/` | same | |

### AI (Phase 4 ✅)

AI work is asynchronous: POST endpoints return **202** with `pending` analyses. Poll
`GET /ai/analyses/{id}/` until `status` is `completed` or `failed`. A failure never
affects the ticket; the analysis carries a readable `error`. Every analysis records
`provider`, `model`, `prompt_version`, `confidence`, `reasoning`, tokens, latency and
`is_mock` (true for the offline demo provider). POSTs use the `ai` throttle scope.

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/tickets/{id}/ai/` | `ai.use` + ticket visibility | Latest analysis per capability, recent recommendations, `ai_enabled`. |
| POST | `/tickets/{id}/ai/` | `ai.use` | `{kinds: [classification, priority, routing, summary, response_suggestion]}` → 202. Identical input analysed in the last 10 minutes is reused. |
| GET | `/ai/analyses/{id}/` | `ai.use` | Poll one analysis (org-scoped and ticket-visibility-scoped). |
| GET | `/ai/recommendations/` | `ai.use` | Filters `status`, `type`, `ticket`. Types: `category`, `priority`, `assignee`, `technician`. |
| POST | `/ai/recommendations/{id}/decide/` | `ai.override` | `{decision: accept\|reject\|override, value?, note?}`. Accept applies the suggestion (history records a person accepting it; priority source `ai`; assignment source `ai_accepted`). Override applies the person's value through normal ticket services. A second decision returns 400. |
| GET / POST | `/ai/assistant/` | `ai.use` + `knowledge.view` | GET: caller's recent questions. POST `{question}` → 202. Answers use only published articles and resolved tickets; `output.sources` lists what was cited. |
| GET | `/ai/insights/` | `ai.use` + `analytics.view` | Filters `type`, `is_dismissed`. |
| POST | `/ai/insights/generate/` · `/ai/insights/{id}/dismiss/` | same | Generate: `{days: 7–180}` → 202. Also runs daily at 06:00 UTC (Celery beat). |
| GET | `/ai/status/` | `ai.use` | Active provider and model (never the key), policies, and acceptance rates per type and prompt version (with `analytics.view`). |

### Knowledge base (Phase 4 ✅)
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/knowledge/articles/` | `knowledge.view` | Readers see published articles only; editors (`knowledge.manage`) see all. `search` = full text; filters `status`, `source`, `category`. |
| POST / PATCH / DELETE | `/knowledge/articles/` | `knowledge.manage` | New articles start as drafts. |
| POST | `/knowledge/articles/{id}/submit/` · `publish/` · `return-to-draft/` · `archive/` | `knowledge.manage` | Review workflow; invalid moves return 400 `invalid_transition`. Publishing records the reviewer. |

### Field service (Phase 5)
`/technicians/`, `/technicians/{id}/availability/`, `/technicians/{id}/location/`,
`/skills/`, `/service-areas/`, `/work-orders/`, `/work-orders/{id}/transition/`,
`/work-orders/{id}/evidence/`, `/work-orders/{id}/confirm/`, `/appointments/`,
`/schedule/?start=&end=&technician=`, `/me/work-orders/` (technician app).

### SLA & notifications (Phase 6)

| Method | Path | Notes |
|--------|------|-------|
| GET/POST | `/sla/policies/` | `sla.view` / `sla.manage`. Targets nested per priority; the default policy must cover every priority and can't be deleted or deactivated. |
| GET/PATCH/PUT/DELETE | `/sla/policies/{id}/` | Edits apply to new clocks only (running clocks keep their snapshot). |
| GET/POST | `/sla/business-hours/` | Weekly schedule `{"mon": [["09:00","17:00"]], …}` (`24:00` allowed as an end), IANA time zone, holidays. 409 on delete while a policy uses it. |
| GET | `/tickets/{id}/sla/` | Clock state, remaining *working* seconds per metric, events. `null` when no policy applies. Needs `sla.view` and ticket visibility. |
| GET | `/sla/report/?start=&end=` | Met/breached per priority for tickets opened in the range (default 30 days, max 366). |
| GET | `/notifications/?unread=1` | Own in-app notifications in the active organization. |
| GET | `/notifications/unread-count/` | `{"unread": n}` |
| POST | `/notifications/{id}/read/`, `/notifications/read-all/` | `read-all` takes optional `{"ids": [...]}`. |
| GET/PUT | `/notifications/preferences/` | List of `{type, channel, enabled}`; PUT accepts a partial list. |

Ticket list/detail responses include `sla` (compact status) for people with `sla.view`.
WebSocket: `/ws/events/`, authenticated by the first message (see architecture §4.2).

### Integrations, analytics, portal (Phase 5/7)
`/assets/{id}/service-records/`, `/integrations/`,
`/integrations/{id}/test/`, `/integrations/{id}/logs/`,
`/webhooks/inbound/{integration_id}/` (signature-verified, unauthenticated),
`/analytics/{report}/?from=&to=&format=csv`,
`/portal/tickets/`, `/portal/tickets/{id}/comments/`, `/portal/feedback/`.

## 3. Asynchronous operations

AI and report endpoints return **202 Accepted** with the created resource:

```json
{ "id": "…", "kind": "classification", "status": "pending" }
```

Clients poll `GET /ai/analyses/{id}/` or listen for `ai.analysis.completed` on the
WebSocket.
