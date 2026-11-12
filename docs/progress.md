# Development Progress

## Phase 1 — Foundation ✅ (2026-11-11)

### Completed

**Architecture & documentation**
- System architecture (modular monolith, module boundaries, event bus, tenancy,
  real-time, workers, scaling path): `architecture.md`
- Full target database schema with conventions and decisions: `database-design.md`
- API conventions, error envelope, endpoint map per phase: `api-documentation.md`
- AI engine design (provider abstraction, hybrid routing, human-in-the-loop,
  mock provider): `ai-engine.md`
- Security model, integration framework, phased roadmap

**Backend** (`backend/`)
- Django 5.2 LTS project with split settings (`base`, `dev`, `test`, `prod`) and
  env-based config. `prod` refuses weak secrets and enables HSTS/SSL/secure cookies.
- DRF: JWT auth (SimpleJWT with rotation + blacklist) configured as default,
  IsAuthenticated by default, page-number pagination, filter/search/ordering
  backends, throttle scopes, OpenAPI via drf-spectacular (`/api/v1/schema|docs|redoc`)
- `apps.core`:
  - abstract base models: UUID PK + timezone-aware timestamps
  - request-ID middleware (validates client IDs, adds `X-Request-ID`), log filter, JSON log formatter
  - central exception handler: one error envelope, no internals leaked on 500
  - `DomainError` / `InvalidTransition` / `Conflict` exceptions for services
  - domain event bus with `on_commit` delivery
  - `/health/` (liveness), `/health/ready/` (Postgres + Redis, 503 on failure), `/meta/` (public config, no secrets)
  - `/ws/system/` WebSocket consumer behind the allowed-origin validator
  - `core.ping` Celery task
- Celery app + django-celery-beat (DB scheduler), Channels with Redis layer, Argon2 hashing

**Frontend** (`frontend/`)
- Vite + React 19 + TS 7 + Tailwind v4 + shadcn/ui (Base UI) with brand tokens and light/dark/system themes
- API client mapping the backend error envelope to `ApiError`, with Zod response validation, a token provider hook and network-error handling
- TanStack Query client (no retry on 4xx), Zustand stores (theme, sidebar) with persistence
- App shell: collapsible sidebar (persisted), mobile drawer, top bar with live
  connection badge, "Demo AI" indicator, theme menu, skip link
- Routes for every module in the navigation. Modules not yet built render an
  explicit "ships in Phase N" page, with no mock data.
- System Status page wired to real health/readiness/meta APIs and the WebSocket,
  with loading skeletons, an error state with request ID, and retry

**Infrastructure**
- Docker Compose: `db`, `redis`, `backend` (auto-migrate), `worker`, `beat`, `frontend` (HMR), `nginx`
- Multi-stage Dockerfiles (dev/prod), non-root backend user, Postgres extensions
  (`pg_trgm`, `btree_gist`, `unaccent`), Nginx with WebSocket upgrade and security headers

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest (real PostgreSQL) | **21 passed**: health/readiness/meta, request IDs, error envelope (validation, 401, domain error, 500 without leaks), OpenAPI generation, event bus (sync, failure isolation, on_commit, rollback), WebSocket welcome/ping + origin rejection, Celery task |
| Backend `ruff check` / `manage.py check` / `makemigrations --check` | clean |
| Frontend Vitest | **13 passed**: API client (envelope, network error, schema mismatch, accepted 503, bearer token), System Status page (healthy, degraded 503, demo-mode label, unreachable + retry), shell (placeholder page, sidebar collapse persistence, 404), theme store |
| Frontend `tsc -b` / `vite build` / `oxlint` | clean (2 upstream shadcn fast-refresh warnings) |
| Docker stack smoke test | all 7 services up. Through Nginx: readiness 200 (db + redis ok), SPA 200, Swagger 200, WebSocket welcome/pong, Celery task executed by the worker container, extensions present. Visual check in headless Chromium (desktop, mobile, dark mode). |

### Known gaps carried forward
- ~~Bundle is a single 697 kB chunk~~ (split per route in Phase 2).
- ~~No authentication yet~~ (done in Phase 2).
- Global search input is shown disabled until the search API exists (Phase 3).
- Upload content sniffing (`python-magic`) is in the image (`libmagic1`) but not wired yet (Phase 3).

## Phase 2 — Identity, tenancy & RBAC ✅ (2026-11-11)

### Completed

**Backend**
- `apps.accounts`: custom `User` (UUID PK, email login, case-insensitive unique
  email, Argon2). Login, refresh, logout, optional self-registration, forgot and
  reset password, invitation preview and accept, profile (`/me/`), change password.
- Session model: access token in the response body (SPA keeps it in memory);
  refresh token in an HttpOnly `SameSite=Strict` cookie scoped to `/api/v1/auth/`,
  rotated on every use with replay rejection (blacklist). Password change/reset and
  deactivation revoke sessions.
- `apps.organizations`: `Organization`, `Membership`, `Role`, `Permission`,
  `RolePermission`, `Invitation` (token stored as SHA-256; single-use; resend
  rotates). `catalog.py` defines every permission code and the six roles (with
  privilege rank), synced to the DB on every migrate.
- Tenancy: the organization is resolved from the user's memberships
  (`X-Organization` only selects among them). Other tenants' objects return 404.
- Permission classes: `HasPermission(...)`, `MethodPermissions` (unlisted methods
  denied). Escalation guards: no self-changes, no granting above your own rank, no
  managing higher-ranked users, Super Admin only by Super Admins, last-admin guard.
- `apps.audit`: append-only `AuditLog`, secret redaction, org-scoped API.
- Organization settings with an allow-listed `settings` schema (routing policy,
  AI toggle, auto-close days).
- Throttling: separate scopes for credentials (IP+email and IP), session refresh
  and system endpoints; `NUM_PROXIES` for correct client identification behind Nginx.
- Transactional email through a Celery task queued after commit
  (`notifications` queue).
- `seed_demo` command: two organizations, one user per role.

**Frontend**
- Auth store (memory-only access token), session restore from the cookie on load,
  automatic token refresh on 401 with one shared in-flight refresh, retry of the
  original request, local sign-out when the session is gone.
- Pages: Login, Forgot password, Reset password, Accept invitation (new and existing
  account paths), Profile settings (profile + password), Organization settings
  (read-only without `organization.manage`), Users (members table with debounced
  search, role/status filters, pagination, role-change dialog, deactivate/reactivate
  confirmation; invitations tab with invite/resend/revoke).
- Route guards (`RequireAuth` with `?next=` and an open-redirect-safe target,
  `RedirectIfAuthenticated`, `RequirePermission`); permission-aware navigation;
  user menu with sign-out (clears the query cache).
- Shared form kit: accessible `Field` (label, `aria-invalid`, `aria-describedby`),
  native select, checkbox, form-level error, server-error-to-field mapping.
- Route-level code splitting: main bundle 697 kB → 391 kB; no chunk-size warning.

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest (real PostgreSQL) | **87 passed**. New: auth flows (cookie flags, generic failures + audit, throttling, rotation + replay rejection, logout, deactivated users, profile, change/reset password single-use + session revocation, registration toggle), RBAC matrix by role, settings allow-list, cross-tenant 404s, `X-Organization` validation, escalation guards, last-admin guard, session revocation on deactivation, invitations (hashed token, single-use, expiry, revoke, resend rotation, conflicts, existing-account password proof, role limits), audit isolation + append-only, proxy-aware throttle regression |
| Backend `ruff`, `check`, `makemigrations --check` | clean |
| Frontend Vitest | **43 passed**. New: login validation/errors/redirect, safe `next`, guards (redirect, session restore, permission block, nav hiding), sign-out, forgot/reset/accept-invite flows, single-flight token refresh + forced sign-out, users page (list, filters, read-only roles, invite incl. role limits and 409, role change, deactivation confirm), org settings (save, validation, read-only), profile (update, server error mapping), timezone options |
| Frontend `tsc -b`, `vite build`, `oxlint` | clean (remaining warnings are in generated shadcn files and react-hook-form's `watch`) |
| Backend pytest inside Docker | **87 passed** (with test settings, see correction below) |
| End to end via Nginx (curl) | login → `/me` → refresh rotation (old token 401) → invite (email delivered through the Celery worker) → preview → accept → agent forbidden from inviting → cross-org header 403 → logout (refresh 401) → audit trail recorded |
| Headless Chromium (Playwright) | redirect to login with `next`, sign-in, users page, invite dialog, **session survives reload**, org settings, technician on mobile (restricted nav + access-denied page); no console errors besides the expected 401 from the restore attempt on first visit |

### Bugs found and fixed during verification
- Empty `JWT_SIGNING_KEY=` in `.env` produced an empty HMAC key (500 on login);
  empty now falls back to `DJANGO_SECRET_KEY`.
- Endpoints without auth classes turned 401 into 403; they now declare the
  Bearer scheme.
- Behind Nginx all clients shared one rate-limit bucket (Django saw only the proxy
  IP), so session restore was throttled after a reload. Fixed with `NUM_PROXIES` +
  dedicated scopes; regression test added.
- After login, the auth-page guard redirected to `/` and overrode `?next=`.
- Chromium lists legacy zone names (`Asia/Katmandu`), so a saved `Asia/Kathmandu`
  showed a blank timezone select. The saved value is now always offered.
- Button-styled links lacked `nativeButton={false}` (Base UI accessibility warning).
- **Correction to Phase 1:** inside Docker, `DJANGO_SETTINGS_MODULE=config.settings.dev`
  overrode pytest's ini setting, so the Phase 1 "tests pass in Docker" run used dev
  settings (real Redis cache, non-eager Celery). pytest now passes
  `--ds=config.settings.test`, which takes precedence; 87/87 pass in Docker too.
- Vendor libraries are now split into cacheable chunks (`vendor-react`, `vendor-ui`,
  `vendor-data`). The app's own entry chunk is 33 kB.

### Known gaps carried forward
- Super Admin cross-organization administration endpoints are not built (a Super
  Admin acts within organizations they're a member of).
- No organization switcher in the UI yet. The API supports `X-Organization`; most
  users have one membership.
- Email verification for self-registered accounts is not implemented
  (registration is off by default).
- The authenticated WebSocket (`/ws/events/`) arrives with notifications in Phase 6.

## Phase 3 — Ticketing engine ✅ (2026-11-11)

### Completed

**Backend**
- `apps.customers`: customers (tier, type, address, archive/restore; active names unique
  per org) and contacts (one primary; linking a user grants portal access).
- `apps.assets`: assets and categories (org-unique tags, warranty, `Decimal` cost +
  currency, deletion blocked once tickets reference an asset).
- `apps.tickets`:
  - Per-org sequential references (`TCK-000042`) via a row-locked `OrganizationSequence`.
  - Status state machine (`lifecycle.py`); customers may only confirm or reopen a resolution.
  - Resolution notes required to resolve; lifecycle timestamps (`first_response_at`,
    `resolved_at`, `closed_at`, `customer_confirmed_at`).
  - Assignment with role/org validation and assignment history; auto-move to Assigned.
  - Public replies vs internal notes. A customer reply on `pending_customer` returns the
    ticket to the team.
  - Field-level `TicketHistory` (append-only) plus `AuditLog` on every mutation;
    domain events (`ticket.created|updated|status_changed|assigned|commented`) for
    AI/SLA/notifications.
  - Row-level visibility: all / technician-own / customer-account. Other tenants get 404.
  - Search (Postgres full text with GIN expression index, ticket-number lookup,
    partial title/customer), filters, severity-aware ordering, archive.
  - Attachments: size limit, extension allow-list, libmagic content check, random
    storage names, SHA-256, authenticated download with `nosniff` + sandbox CSP.
- `apps.analytics`: dashboard summary, trends (org-timezone buckets), breakdowns,
  agent workload, recent activity. Metrics of unbuilt modules are `null` with a reason.
- `seed_tickets`: realistic demo data through the real services.

**Frontend**
- Dashboard: KPI tiles linking to filtered lists, "not available yet" tiles for SLA
  and field-service metrics, created-vs-resolved line chart (colours validated with the
  dataviz palette checker in both themes, single axis, crosshair tooltip, table view),
  priority/status/category bar lists, recent tickets, activity feed, agent workload.
- Tickets list: filters and sorting in the URL, debounced search, pagination.
- Create ticket: dependent customer → contact/asset selects, category default
  priority hint; simplified form for portal customers.
- Ticket detail: status actions (with resolution and internal notes), assign,
  escalate, edit, archive; conversation with internal-note composer; attachments
  upload and authenticated download; activity timeline; details and dates.
- Customers list/detail (contacts CRUD, assets, tickets), Assets list with
  create/edit, global search in the top bar.
- Chart library split into its own cacheable chunk.

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest (local + Docker) | **144 passed**. New: ticket creation and numbering, cross-tenant references, portal rules, visibility matrix, filters/search/ordering, field history, state machine, customer confirm/reopen, escalation, assignment validation and history, internal notes isolation, first response, customer reply side effect, archiving, categories, attachments (round trip, disguised executable, SVG, empty, size, internal visibility, cross-org), customers, contacts, assets, dashboard metrics and visibility |
| Frontend Vitest | **60 passed**. New: ticket list filters → URL/request, create-ticket validation + payload (staff and portal), detail (timeline, internal note, resolve with server error, customer view), dashboard (values, unavailable metrics, table view, period, role-based workload), customers (create, validation, duplicate error, read-only) |
| Lint / type-check / build | clean |
| Headless Chromium walkthrough (Docker stack) | dashboard → filtered list → assign agent + technician → internal note → upload → download → resolve → create ticket → customer page → assets → global search; portal customer is refused another customer's ticket and sees only their own tickets |

### Bugs found and fixed during verification
- **Uploads failed in Docker** (`PermissionError` on `/app/media`): the named volume was
  root-owned while the app runs unprivileged. The image now creates the directory
  owned by `app`. **Existing volumes need a one-time fix:**
  `docker compose exec -u root backend chown -R app:app /app/media`. Unit tests use
  in-memory storage, so only the end-to-end run could catch this.
- Archived tickets returned 404 on their own detail page (DRF applies list filters
  inside `get_object`).
- Customer create/update responses lacked computed counts.
- Portal customers couldn't raise tickets without knowing their customer ID.
- Ticket history labelled people by email instead of name.

### Known gaps carried forward
- Customer pickers load the first 100 customers alphabetically; an async searchable
  combobox is needed for large customer bases.
- `due_at` is only set by demo data until SLA policies arrive (Phase 6); the
  "Overdue" figures therefore reflect seeded deadlines.
- No hard delete of tickets through the API (by design); the Django admin remains
  available to Super Admins.
- Ticket category management UI isn't built yet (the API exists).

## Phase 4 — AI engine ✅ (2026-11-12)

### Completed

**Backend** (`apps.ai`, `apps.knowledge`)
- Provider-independent layer: `AIProvider` interface with typed errors, plus three providers:
  - `MockProvider`: deterministic, offline, confidence ≤ 0.75, reasoning prefixed `[mock]`.
  - `AnthropicProvider`: official SDK, structured outputs, effort per capability,
    server-side refusal fallback, refusal and truncation handling.
  - `OpenAICompatibleProvider`.
- `client.run`: retries with backoff, one repair attempt for invalid output, JSON-schema
  validation, a circuit breaker, and every outcome persisted on `AIAnalysis` (provider,
  model, prompt version, confidence, reasoning, tokens, latency, attempts, error,
  `is_mock`). A provider failure never raises into business code.
- Capabilities: classification, priority, hybrid routing (deterministic scorer + LLM
  explanations, works with the provider down), summary, response suggestion
  (internal notes excluded), knowledge assistant (FTS retrieval, cited sources only),
  insights (aggregates only), knowledge extraction (draft articles).
- Human control: `AIRecommendation` with accept / reject / override (`ai.override`),
  supersession of stale suggestions, auto-apply only under explicit org policy and
  above `AI_AUTO_APPLY_MIN_CONFIDENCE`, never over a person's priority choice. AI-made
  changes are attributed `actor_type=ai` in history and audit.
- Triggers via domain events (ticket created → triage; ticket closed → knowledge
  draft), Celery `ai` queue, daily insights at 06:00 UTC (beat schedule via migration),
  `ai_backfill` command (triage, knowledge, insights, re-queue stuck work).
- Knowledge base with review workflow (draft → in review → published → archived);
  only published articles feed answers. Acceptance-rate statistics per type and
  prompt version.

**Frontend**
- AI panel on the ticket page: live "Analysing…" state, pending suggestions with
  confidence and reasoning, Accept / Choose other (with reason) / Dismiss, routing
  breakdown, summary, decision history, failure notice, "Demo AI" labelling.
- "Suggest reply": the draft is placed in the composer for editing and never sent
  automatically.
- AI Assistant page (questions with steps and linked sources; Knowledge base tab with
  the review workflow and an editor).
- AI Insights page (insight cards with evidence, dismiss, generate on demand, demo-mode
  notice, acceptance-rate table).

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest | **188 passed**. New: every mock output validates against its schema; Anthropic request shape (model, structured output, effort, fallback, no sampling params), error mapping, refusal and truncation handling; client retries, repair, config errors not retried, circuit breaker, unconfigured provider; triage on create; AI disabled; manual routing policy; auto-triage threshold and manual-priority protection; auto-routing with a clear winner; routing with the provider down; accept / override / reject and double decisions; permissions (agents can't decide, customers can't use AI); internal notes excluded from drafts; result reuse; org isolation; knowledge extraction → review → publish; assistant uses published sources only; insights; status never exposes the key; base-URL validation |
| Frontend Vitest | **71 passed**. New: AI panel (suggestions, accept, override with reason, read-only for agents, failure notice, hidden without `ai.use`), suggest-reply fills the composer without sending, assistant answers and sources, knowledge review and publish, insights list, generate and wait, dismiss, acceptance table |
| Lint / type-check / build | clean |

### Bugs found and fixed during verification
- **Worker silently dropped AI tasks in Docker** ("unregistered task"). Compose built
  separate images for backend, worker and beat, and only the backend image had the
  new dependencies. All three now share one image tag. `ai_backfill --requeue-pending`
  recovers analyses whose messages were dropped.
- The auto-assignment audit entry lacked the organization (it came from the HTTP
  request, which automatic changes don't have).
- Effect-driven "wait for analysis" logic in the UI was replaced with an awaited
  polling helper (`waitForAnalysis`) with a timeout.

### Known gaps carried forward
- ~~No live run against a real model~~. Resolved 2026-11-12: every capability verified live on
  NVIDIA Nemotron 3 Ultra through the OpenAI-compatible provider (see Phase 6 follow-up).
- Retrieval is keyword full-text search; semantic search (pgvector + embeddings) is the
  planned upgrade behind `retrieval.search`.
- Technician routing uses workload and experience only until skills, availability and
  location exist (Phase 5).

## Phase 5 — Field service ✅ (2026-11-12)

### Completed

**Backend** (`apps.field_service`)
- Technicians: a profile is created automatically for anyone with the Field Technician role.
  Profiles hold skills with levels 1–5, certifications with expiry, service areas, home base,
  daily job limit and hourly cost. Shifts and time off are self-service for the technician and
  managed by dispatchers otherwise. Technicians can set themselves on or off duty but not on leave.
- Work orders: per-org references (`WO-000042`), created from a ticket (customer, asset,
  priority and description copied; internal note added to the ticket) or standalone. State
  machine in `lifecycle.py`: created → assigned → accepted → en route → on site → in progress →
  completed, with cancel from any open state and "hand back" before travelling. Only the
  assigned technician moves the field steps; every change is row-locked, logged in
  `WorkOrderStatusLog` (with optional coordinates), audited and published as a domain event.
- Completion requires a summary and at least one photo or document. Labour minutes are
  measured from start of work, and labour and parts costs are computed in `Decimal`. A completion
  note goes on the linked ticket, followed by customer sign-off (name, 1–5 rating, comment).
- Evidence: before/after photos, documents and signatures with content-type sniffing and
  SHA-256. Downloads are permission-checked, with `nosniff`, a sandbox CSP and inline display
  for images only.
- Appointments: overlap is refused by the service *and* by a PostgreSQL exclusion
  constraint (`btree_gist`), so concurrent bookings can't both succeed. Time off blocks a slot.
  Slots outside a shift or past the daily limit come back as warnings. Rescheduling replaces
  the visit. Reassigning moves the visit to the new technician when they are free, otherwise
  releases it with a warning. Declining clears the schedule.
- Routing: `rank_technicians` scores skills 0.35, availability 0.25, workload 0.2 and
  distance (haversine) 0.2. Blocked technicians (on leave, off duty, time off) are listed last with the
  reason. The AI routing explanation uses the same scorer.
- Location: opt-in per technician and only accepted while a job is en route, on site or in
  progress. Only roles with `location.view` can read it, and pings are purged after 30 days
  (Celery beat, scheduled by migration).
- Schedule API (max 31 days): technicians see only their own calendar.
- `seed_field_service`: 4 technicians across 3 service areas, two weeks of shifts, one day
  off, an expired certificate and 12 work orders in every state.

**Frontend**
- Technicians list (search, status) and detail (skills editor, certifications, shifts and
  time off, current jobs).
- Work orders list (filters, search by reference) and detail (stepper, actions by
  capability, evidence gallery with upload, completion report, sign-off, status history).
- Dispatch dialogs: assign with ranked suggestions and the reason for each score, schedule and
  reschedule with server warnings, hand back, cancel, complete (parts, labour), customer sign-off.
- Weekly scheduling calendar per technician, with shifts and time off.
- My jobs (mobile-first technician view): the most urgent job first with large step buttons,
  directions, up-next list, recent completions awaiting sign-off, duty toggle and location
  sharing. Location is reported at most once a minute, only while a job is under way.

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest | **217 passed**. New: automatic profiles, self-service limits, skills, create from ticket, cross-org validation, assignment syncing the ticket, full workflow with costs, only the assigned technician advances, decline and cancel, customer confirmation, evidence rules and isolation, double-booking (service and database constraint), time off and shift warnings, schedule scoping, technicians see only their own jobs, location opt-in and purge, ranking and blocks, suggestions endpoint, dashboard figures, visit follows reassignment or is released, decline clears the schedule, technician status with several jobs and off duty |
| Frontend Vitest | **77 passed**. New: My jobs ordering and advancing, empty state and pending sign-off, duty and sharing toggles, location reported only for jobs under way (watcher cleared on unmount), reassignment warning shown to the dispatcher |
| Lint / type-check / build | clean (field service is fully ruff-formatted) |
| Live stack | technician endpoints through Nginx, location ping 409 with sharing off and 201 with it on, demo data seeded |

### Bugs found and fixed during verification
- **The frontend build failed**: `my-jobs-page.tsx` and `use-location-reporter.ts` had been
  committed empty.
- **Reassigning left the booked visit on the old technician's calendar**, which blocked their
  time and hid the slot from the new technician's double-booking check. Unassigning left it
  booked too. The visit now follows the job or is released with a warning.
- **Declining kept the planned time** on the work order after its appointment was cancelled.
- **Technician status**: completing or cancelling one job set the technician to available
  while another job still had them in the field, and completing put an off-duty technician
  back on duty.
- OpenAPI: the schedule endpoint had no schema, and the work-order assign request clashed with
  the ticket assign request (`AssignRequest`), so one replaced the other in the docs.

### Known gaps carried forward
- No visual check in a real browser in this environment (no browser installed). Covered by component tests and API checks.
- Location is shown to dispatchers as the latest ping only. A live map comes with real-time
  updates in Phase 6.
- Distance is straight-line (haversine), not road distance.
- drf-spectacular reports warnings across all apps because viewsets read `request.tenant`
  during schema generation; to fix in Phase 8. Ruff formatting has drifted in 23 files
  outside field service.

## Phase 6 — SLA, notifications, real-time ✅ (2026-11-12)

### Completed

**Backend: `apps.sla`**
- `business_time.py`: pure working-time arithmetic (weekly intervals, split and overnight
  shifts with `24:00`, holidays, IANA time zones). All maths runs on UTC instants, so DST
  days are measured in real seconds; there's a test for the London clock change.
- Working hours and holidays, policies with per-priority targets (first response,
  resolution, warning threshold) and conditions (category, customer tier, channel), an
  evaluation order, and a single default policy per organization (database constraint). New
  organizations get "Standard hours" (Sun–Fri 09–17 in the org time zone) and a "Standard"
  policy automatically; a migration does the same for existing ones.
- `SLAInstance` per ticket copies the targets and calendar when applied, so policy edits never
  rewrite running clocks. Deadlines are `start + target + paused working time`, so recomputing
  after a pause, resume or priority change is a pure function of stored fields.
- `sync_ticket` reconciles the clock with the ticket's *current* state after every ticket event
  (inside the ticket's transaction), so every path that changes a ticket keeps the clock right,
  including customer replies that change status without a status event. The resolution clock
  pauses on Pending customer / Pending parts and between resolve and reopen. First response is
  met by the first public staff reply (or by resolving). Priority changes take the new target.
  A breach is final; resolving late stays "breached".
- Monitor (`sla.scan`, beat every minute, `sla` queue): warnings and breaches per metric are
  recorded once (partial unique constraint), with row locks and `skip_locked` so concurrent
  runs are safe. A clock already past its deadline goes straight to breached with no late
  warning. A resolution breach escalates the ticket through the normal transition table
  (system actor in history and audit) when the policy allows it.
- Compliance report per priority. The dashboard's `sla_compliance` is now real (for `sla.view`).
- `sla_backfill` command starts clocks for open tickets created before SLA existed.

**Backend: `apps.notifications` and real-time**
- Notifications (8 types), per-user preferences per type × channel with sensible defaults
  (email only for things that need action), and email deliveries with status, attempts and
  last error. Delivery runs as a retried Celery task with backoff, gives up after 5 attempts,
  and never sends twice (row lock + status check). Inactive members are never notified; nobody
  is notified about their own action (`actor_id` added to ticket and work-order events).
- Subscribers (after commit): ticket assigned, customer reply, escalated (manual), reopened by
  customer, SLA at risk (owner, or managers if unassigned), SLA breached (owner + managers),
  work order assigned, completed, handed back or cancelled. A technician assigned through a work
  order gets the job notification, not a second "ticket assigned" one.
- `/ws/events/`: the JWT goes in the first message (never the URL), with a 10 s auth deadline
  and close 4401 on expiry. Groups are derived server-side (own user; staff group only with
  `tickets.view_all`; dispatch group only with `work_orders.view_all`). Pushes carry IDs only,
  and a broker outage never breaks the operation that triggered a push.

**Frontend**
- Event stream in the app shell: auth by first message, cache invalidation per event type,
  toast with "View" for new notifications, token refresh + reconnect on 4401, backoff on other
  drops, stays closed when the session is gone.
- Notification bell with unread badge and recent items, mark read / all read; Notifications
  page with inbox (all / unread, paging) and a preferences grid.
- Ticket page SLA panel: per metric status, progress, working time left or overdue, pause
  notice, calendar and clock history. The server supplies remaining *working* time; the
  panel ticks locally only for 24/7 clocks and refreshes every minute otherwise.
- Ticket list SLA chip showing the metric that needs attention first.
- SLA page: compliance report (7/30/90/365 days), policy cards and editor (targets, conditions,
  calendar, escalation), working-hours editor (weekly intervals, time zone, holidays).
  Read-only without `sla.manage`.

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest | **263 passed**. New: business time (weekends, holidays, split and overnight shifts, DST, inverse property, validation); SLA (defaults, apply on create, calendar and holidays, pause/resume, resume via a customer reply, first response, resolve and reopen, priority change, policy edits don't rewrite clocks, matching by tier, category and channel, inactive policies, monitor warn → breach → escalate once, response breach without late warning, paused clocks not breached, breach is final, report and dashboard, ticket SLA endpoint visibility, policy and working-hours API validation and permissions, default switching); notifications (assignment in-app + email, no self-notify, preferences, inactive members, customer reply and reopen, SLA warning vs breach recipients, work-order flow, inbox privacy across users and orgs, email retry → failed → no double send); WebSocket (auth, staff-only streams, invalid token, unauthenticated messages, other org, token expiry) |
| Frontend Vitest | **90 passed**. New: first-message auth, refetch on `ticket.changed`, toast + unread badge, reconnect with a fresh token on 4401, no reconnect without a session, inbox read / read-all, preferences save, SLA panel (at risk, paused, overdue, hidden without `sla.view`), list chip, policy editor (server validation, payload), read-only SLA page |
| Lint / type-check / build | clean |
| Live stack | migrations applied; beat → worker runs `sla.scan` every minute; through Nginx: the agent's socket authenticates, an ops assignment over REST arrives live as `ticket.changed` + `notification.created`, a bad token closes with 4401; SLA, report, notification and dashboard endpoints; customer gets 403 on SLA |

### Bugs found and fixed during verification
- The monitor's row lock joined the nullable policy (`FOR UPDATE` on an outer join), which
  PostgreSQL refuses. It now locks only the SLA row.
- The email task saved its failure state inside the transaction it then raised out of, which
  would have rolled the attempt count back. It now commits each attempt before retrying.
- WebSocket notification pushes overwrote the message `type` with the notification's own type;
  that field is now `kind`.
- Technicians received two notifications for one job (ticket + work order).
- Report dates without a time zone would have raised on comparison; they're now read in the
  server time zone.

### Known gaps carried forward
- **Demo data:** `sla_backfill` measured the old demo tickets from their creation dates, so most
  came out breached (compliance 0 % in the demo org, 14 tickets escalated). That's correct for
  the data, but the demo seed should be re-dated in Phase 7 so the dashboard tells a useful story.
- Nginx resolves the backend's address once at start-up; after recreating the backend
  container, restart Nginx (502 otherwise). To fix with a `resolver` in Phase 8.
- Customers can still see a ticket's `due_at` (Phase 3 behaviour); decide what the portal shows in Phase 7.
- SMS/WhatsApp channels arrive with integrations (Phase 7); notification digests aren't built.
- MSW's WebSocket handlers don't match under Vitest (two module copies), so real-time tests use
  a controllable fake socket instead.
- No visual check in a real browser in this environment.

### Follow-up: live AI provider (2026-11-12)
- Configured the NVIDIA API catalog through `openai_compatible`. The requested
  `qwen/qwen3.5-122b-a10b` was retired on 2026-07-20 (410), so I evaluated the account's other
  models with the app's exact structured-output request. `nvidia/nemotron-3-ultra-550b-a55b`
  returned valid JSON in 3 s; Mistral Large 4 worked but took 18 s; Nemotron 3.5 Lightning used its
  whole budget on hidden reasoning; Kimi K2.6 and Nemotron 3 Super aren't enabled for the
  account (404); gpt-oss-20b and DeepSeek V4.1 Flash timed out.
- Live end to end through the worker: classification (Refrigeration, 0.99), priority (Critical,
  0.95), routing, summary, reply draft and the knowledge assistant (which correctly said the
  knowledge base had no answer instead of inventing one). All valid on the first attempt, 6–25 s each.
- Fixed: the OpenAI-compatible provider now reports truncation (`finish_reason: length`), refusals
  (`refusal`, `content_filter`) and empty content precisely, and includes the provider's reason
  in HTTP errors (e.g. "model reached its end of life"). Reply drafts no longer open with "Dear the
  customer," when the ticket has no contact (`response-v2`).
- Known: the assistant lists retrieved sources even when it says they don't answer the question.

## Phase 7 — Integrations, analytics, portal ✅ (2026-11-12)

### Completed

**Backend: `apps.integrations`**
- Registry of connectors (`@register` per `(kind, provider)`): outbound webhooks, inbound webhook
  (tickets), SMS via Twilio, SMS console (dev log), WhatsApp Business Cloud API (template messages).
  Each connector declares its settings and secrets so the API validates them and the UI renders the form.
- Credentials are Fernet-encrypted (`MultiFernet` key rotation) and write-only: responses show
  `configured` and at most the last 4 characters. Generated signing secrets are shown once. All changes
  (never values) are audited.
- Egress guard (`net.py`): public https only, DNS-checked and IP-pinned against rebinding, no
  redirects, capped responses. Used by every outbound call.
- Outbound webhooks: ticket, work-order and SLA events → signed envelope with a stable event id →
  Celery `webhooks` queue; retries at 1 m, 5 m, 30 m, 2 h, 12 h then failed; manual redeliver; a sweep
  every 5 minutes re-queues retries lost by a broker restart. Internal notes are never sent.
- Inbound webhook: signed, replay-protected, size-limited, throttled, idempotent. Messages become
  tickets (matched to the customer contact by email, else an optional default customer), or a reply
  when they mention a ticket reference: a public reply when the sender has a portal account, an
  internal note otherwise. Tickets are created on behalf of the admin who set up the integration
  (checked on every message).
- Integration logs (summaries only, phone numbers masked), health from last success/error, test connection.

**Backend: analytics and portal**
- Seven reports (`ticket_volume`, `tickets_by_category`, `agent_performance`, `sla_compliance`,
  `field_service`, `customer_satisfaction`, `ai_accuracy`) as columns + rows, whole days in the org time
  zone, up to a year; CSV export with formula neutralisation, UTF-8 BOM, audit entry and throttle.
- `apps.portal`: customer-only API (own accounts, public replies, customer-worded statuses, no internal
  fields), create with category/own asset, confirm / reopen with reason, `CustomerFeedback` (1–5, once per
  person, resolved tickets or completed work orders).
- Dev email: `EMAIL_REDIRECT_TO` sends all dev mail to one inbox (demo users have made-up addresses).

**Frontend**
- Integrations: catalog-driven add flow, password inputs for credentials, show-once secret dialog with
  copy, detail page with settings, enable toggle, test connection, test message, inbound URL + example
  signed `curl` + rotate, endpoints (events, active, rotate, delete), deliveries with retry now, received
  messages linked to their tickets, activity log.
- Analytics: report tabs, date range with presets (in the URL, so links are shareable), formatted tables, CSV export.
- Customer portal ("My requests"): list by state with search, new request with validation, request page with
  chat-style conversation, "We need a reply from you", confirm / reopen with reason, star rating. Customers land
  on it; staff screens are hidden from them (`hiddenFor`). Every navigation item is now implemented (tested).

### Tests executed

| Suite | Result |
|-------|--------|
| Backend pytest | **310 passed**. New: encryption and key rotation; write-only credentials; validation, permissions and isolation; SSRF (loopback, RFC 1918, link-local/metadata, IPv6 and mapped, 0.0.0.0, DNS answer pointing inside, URL shape); signed delivery to a real local server; internal notes never sent; retry schedule → failed → redeliver with a stable event id; redirects not followed; disabled endpoint; sweep; ping and health; inbound create once, signature/replay/size/unknown, secret rotation, reply by reference (public vs internal), unknown sender, creator losing access; Twilio request shape and masked logs; WhatsApp template rule; console SMS; portal (own tickets only, hidden fields, internal notes hidden, confirm/reopen/rate, feedback rules, staff refused); reports (org-timezone days, agent figures, satisfaction, every report renders, CSV injection and audit, validation and permissions); dev mail redirect |
| Frontend Vitest | **100 passed**. New: integration add flow (credentials sent, never shown), show-once inbound secret, test connection and retry; analytics report switch and CSV export with dates; portal list by state, validated new request, conversation and reply, confirm, reopen reason, rating; customers' navigation and landing; every nav item implemented |
| Lint / type-check / build | clean |
| Live stack | inbound signed message → ticket TCK-000046 via the worker; replay = duplicate; forged = 401; metadata URL refused; report + CSV; portal as the demo customer; real email through Gmail SMTP (redirected) |

### Known gaps carried forward
- ~~SMS/WhatsApp not notification channels~~ WhatsApp done (follow-up below); SMS waits for a paid sender.
- ~~Email-to-ticket~~ done (follow-up below).
- `PUBLIC_API_URL` should be set so inbound URLs shown in the UI are reachable from outside (falls back to `FRONTEND_URL`).
- Webhook delivery holds a row lock during the HTTP call (≤10 s); fine at this scale, revisit with a "sending" state if volume grows.
- ~~Demo data is old~~ fixed with `reset_demo` (follow-up below).
- No visual check in a real browser in this environment.

### Follow-up: email to ticket and fresh demo data (2026-11-12)
- **Email to ticket** (`email/imap` connector, beat every 2 min): only mail sent to a dedicated address
  (`only_to`, e.g. a Gmail plus-address), received after set-up, opened read-only with `BODY.PEEK` (nothing
  marked read, moved or deleted), automatic mail skipped (`Auto-Submitted`, bulk/list, our own
  `X-ATT-Notification`, now set on every notification email so they can never loop), one ticket per
  `Message-ID`, quoted history stripped from replies, IMAP host through the SSRF guard with IP pinning.
  Verified live with Gmail: a test email became a ticket; the next poll saw it as a duplicate.
  Fixed during the live run: a `Date` header without a time zone crashed the comparison.
- **`reset_demo`**: rebuilds the demo org's activity around today with events muted (no email, webhooks or AI
  calls): ticket timelines drawn against the real SLA targets in working time, history and replies dated to
  match, SLA clocks rebuilt from the timeline (`sla.services.restamp`), work orders, 25 customer ratings and
  in-app notifications. Result: 70 % resolution compliance instead of 0 %. Re-runs are repeatable (assets are
  now get-or-create).
- `events.muted()` context manager for bulk operations.

### Follow-up: WhatsApp notifications and Twilio API keys (2026-11-12)
- **WhatsApp as a notification channel**: `whatsapp` joins In-app and Email in preferences (off by default),
  offered only when the organization has an enabled WhatsApp integration with a `notification_template`
  (an approved Meta template with body variables {{1}} = what happened, {{2}} = link). Sent to the phone on the
  user's profile (normalised to E.164), as a retried task; recipient/template errors (Meta `#131xxx`) fail
  without pointless retries. Verified live on Meta's free test number: `hello_world` delivered to a verified
  phone; template `att_notification` submitted through the API (pending Meta review at the time of writing).
- **Twilio SMS with API keys** (`SK…` + secret, revocable on their own) as well as the auth token; the
  connection test now checks that the From number belongs to the account and can send SMS (API keys may not
  read the account resource). Verified live: the key signs in. Twilio's 2026 free trial only sends Twilio's
  predefined templates and has a $0 balance, so app SMS needs an upgraded account; the integration is saved,
  ready for a number.
- Known: one dashboard component test flaked once under full-suite load (passes alone and on re-run).

## Phase 8 — Hardening (next)

Security audit against `security.md`, `check --deploy`, dependency audit; drf-spectacular
warnings; Nginx `resolver` for container restarts; coverage gaps; end-to-end workflow tests;
performance (query counts, indexes, caching); production images and deployment guide.
