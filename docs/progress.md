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
- Bundle is a single 697 kB chunk. Route-level code splitting will come with Phase 2 pages.
- No authentication yet: the user menu, login and protected routes are Phase 2.
- Global search input is shown disabled until the search API exists (Phase 3).
- Upload content sniffing (`python-magic`) is in the image (`libmagic1`) but not wired yet (Phase 3).

## Phase 2 — Identity & tenancy (next)

Custom email-based `User`, `Organization`, `Membership`, `Role`/`Permission` with
the six system roles, `Invitation`, `AuditLog`; JWT login/refresh/logout with an
HttpOnly refresh cookie; forgot/reset password; RBAC permission classes and an
organization-scoped base viewset; isolation tests; seed command with demo users
for every role. Frontend: login, forgot/reset password, auth store with silent
refresh, protected and role-aware routes, user menu, profile, user management and
organization settings pages.
