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

### Dashboard (Phase 2 shell, metrics from Phase 3+)
| GET | `/dashboard/summary/` | KPI tiles |
| GET | `/dashboard/trends/?period=30d` | Ticket trend series |
| GET | `/dashboard/activity/` | Recent activity |

### Tickets (Phase 3)
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/tickets/` | List (filter/search/sort/paginate) / create |
| GET/PATCH | `/tickets/{id}/` | Detail / edit |
| POST | `/tickets/{id}/archive/` | Archive (permission-gated) |
| POST | `/tickets/{id}/transition/` | `{ "status": "in_progress", "note": "…" }` — state machine |
| POST | `/tickets/{id}/assign/` | Assign agent / technician |
| POST | `/tickets/{id}/escalate/` | Manual escalation |
| GET/POST | `/tickets/{id}/comments/` | Public comments & internal notes |
| GET/POST | `/tickets/{id}/attachments/` | Multipart upload |
| GET | `/tickets/{id}/history/` | Audit trail / timeline |
| GET/POST | `/ticket-categories/` | Category tree |

### AI (Phase 4)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/tickets/{id}/ai/analyze/` | Enqueue classification + priority (202) |
| POST | `/tickets/{id}/ai/summarize/` | Enqueue summary (202) |
| POST | `/tickets/{id}/ai/route/` | Routing recommendation (202) |
| POST | `/tickets/{id}/ai/suggest-response/` | Draft reply (202) |
| GET | `/tickets/{id}/ai/analyses/` | Analysis history |
| GET | `/ai/recommendations/?status=pending` | Pending recommendations |
| POST | `/ai/recommendations/{id}/accept/` | Accept |
| POST | `/ai/recommendations/{id}/reject/` | Reject / override with value |
| POST | `/ai/assistant/query/` | Knowledge assistant question |
| GET | `/ai/insights/` | Generated insights |
| GET/POST/PATCH | `/knowledge/articles/` | Knowledge base + review workflow |

### Field service (Phase 5)
`/technicians/`, `/technicians/{id}/availability/`, `/technicians/{id}/location/`,
`/skills/`, `/service-areas/`, `/work-orders/`, `/work-orders/{id}/transition/`,
`/work-orders/{id}/evidence/`, `/work-orders/{id}/confirm/`, `/appointments/`,
`/schedule/?start=&end=&technician=`, `/me/work-orders/` (technician app).

### SLA & notifications (Phase 6)
`/sla/policies/`, `/sla/business-hours/`, `/tickets/{id}/sla/`, `/sla/report/`,
`/notifications/`, `/notifications/{id}/read/`, `/notifications/read-all/`,
`/notifications/preferences/`. WebSocket: `/ws/events/?token=<access>`.

### Customers, assets, integrations, analytics, portal (Phase 3/5/7)
`/customers/`, `/customers/{id}/contacts/`, `/customers/{id}/tickets/`,
`/assets/`, `/assets/{id}/service-records/`, `/integrations/`,
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
