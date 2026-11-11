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

## Phase 4 — AI engine (next)

Provider abstraction (mock, Anthropic, OpenAI-compatible) with retries, timeouts,
schema validation and a circuit breaker; `AIAnalysis` / `AIRecommendation` storage
with confidence and reasoning; Celery `ai` queue triggered by `ticket.created`;
classification, priority prediction, summarisation, hybrid routing (deterministic
scoring + LLM explanation), response suggestions, knowledge base with review flow
and assistant, insights. Frontend: AI panel on the ticket (accept/override),
AI Assistant and AI Insights pages, clear "Demo AI" labelling in mock mode.
