# ATT Platform

AI-driven ticketing and field service management platform: a modular-monolith
Django backend, a React + TypeScript frontend, PostgreSQL, Redis, Celery,
Django Channels, and a provider-independent AI engine.

> **Status:** Phase 2 (identity, organizations, RBAC) complete. See [`docs/progress.md`](docs/progress.md)
> and [`docs/development-roadmap.md`](docs/development-roadmap.md).

## Repository layout

```text
att-platform/
├── backend/            Django 5.2 LTS · DRF · Channels · Celery   (independently runnable)
│   ├── config/         settings (base/dev/test/prod), urls, asgi, celery, ws routing
│   └── apps/           one Django app per domain (core today; more per phase)
├── frontend/           React 19 · Vite · TS · Tailwind v4 · shadcn/ui (independently runnable)
│   └── src/            app/ components/ features/ lib/ stores/ pages/ test/
├── docs/               architecture, database, API, AI, security, integrations, roadmap
├── infrastructure/     nginx and postgres configuration
├── docker-compose.yml  full development stack
└── .env.example        every configuration key, documented
```

## Quick start (Docker, recommended)

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

| URL | What |
|-----|------|
| http://localhost:8080 | App, through Nginx (SPA + API + WebSocket on one origin) |
| http://localhost:8080/api/v1/docs/ | Swagger UI |
| http://localhost:8080/api/v1/health/ready/ | Readiness (database + Redis) |
| http://localhost:8080/system | System status page (live health, WebSocket state) |
| http://localhost:5173 / :8000 | Vite dev server / Django directly |

Services: `db` (PostgreSQL 16), `redis`, `backend` (Django ASGI, auto-migrates on
start), `worker` (Celery), `beat` (Celery beat), `frontend` (Vite with HMR), `nginx`.
Source is mounted into the containers, so edits reload live.

```bash
docker compose exec backend python manage.py seed_demo      # demo organizations + one user per role
docker compose exec backend pytest
docker compose logs -f worker
docker compose down          # stop (data kept in volumes)
docker compose down -v       # stop and delete database/redis volumes
```

PostgreSQL and Redis aren't published to the host, so they can't clash with local
installs. Uncomment the `ports` line in `docker-compose.yml` if you need host access.

## Local development (without Docker)

Requirements: Python 3.13 ([uv](https://docs.astral.sh/uv/) recommended),
Node 22+ with pnpm, and local PostgreSQL 16+ and Redis 7+.

```bash
cp .env.example .env    # DATABASE_URL / REDIS_URL point at localhost
```

**Backend**

```bash
# one-time database setup (CREATEDB lets pytest create its test database)
psql -U postgres -c "CREATE ROLE att LOGIN PASSWORD 'att_dev_password' CREATEDB;"
psql -U postgres -c "CREATE DATABASE att OWNER att;"

cd backend
uv venv --python 3.13 .venv && uv pip install -r requirements/dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver            # http://localhost:8000 (ASGI via daphne)
.venv/bin/python manage.py seed_demo            # demo users (see below)
.venv/bin/celery -A config worker -l info -Q default,ai,notifications,webhooks,sla   # separate terminal
.venv/bin/celery -A config beat -l info         # separate terminal
```

**Frontend**

```bash
cd frontend
pnpm install
pnpm dev        # http://localhost:5173; proxies /api and /ws to localhost:8000
```

## Demo accounts

`python manage.py seed_demo` creates two organizations and one user per role
(password `Demo!Pass2026`, or pass `--password`). It refuses to run when
`ENVIRONMENT=production`.

| Email | Organization | Role |
|-------|--------------|------|
| superadmin@att.local | Acme Facilities | Super Admin (also Django admin) |
| admin@acme.test | Acme Facilities | Organization Admin |
| ops@acme.test | Acme Facilities | Operations Manager |
| agent@acme.test | Acme Facilities | Support Agent |
| tech@acme.test | Acme Facilities | Field Technician |
| customer@acme.test | Acme Facilities | Customer |
| admin@globex.test | Globex Services | Organization Admin (second tenant, for isolation checks) |

In development, emails (invitations, password resets) are printed to the
**worker** log: `docker compose logs -f worker`.

## Testing

```bash
# Backend: pytest against real PostgreSQL; Celery runs eagerly, in-memory channel layer
cd backend && .venv/bin/pytest
.venv/bin/pytest --cov                 # with coverage
.venv/bin/ruff check .                 # lint

# Frontend: Vitest + Testing Library + MSW
cd frontend && pnpm test
pnpm typecheck && pnpm lint && pnpm build
```

## Configuration

All configuration comes from environment variables; see [`.env.example`](.env.example).
Key points:

- `DJANGO_SETTINGS_MODULE` picks `config.settings.dev | test | prod`. `prod` refuses
  to start with a weak `DJANGO_SECRET_KEY`.
- `AI_PROVIDER=mock` (default) uses the offline, deterministic mock provider. Its
  output is always flagged as demo output in the API and UI. Set `anthropic` or
  `openai_compatible` together with `AI_API_KEY` to use a real model (Phase 4).
- `NUM_PROXIES` is the number of trusted reverse proxies in front of Django (1 in
  Docker Compose, behind Nginx). Rate limiting identifies clients through
  `X-Forwarded-For` only when this is set correctly. Never set it higher than
  the real number of proxies, or clients can spoof their address.
- `REGISTRATION_ENABLED=false` (default) disables self-service organization
  sign-up; users join by invitation.
- `VITE_*` variables are bundled into the browser. Only public values go there,
  never keys.

## Documentation

| Document | Contents |
|----------|----------|
| [architecture.md](docs/architecture.md) | System architecture, modules, communication, tenancy |
| [database-design.md](docs/database-design.md) | Entities, relationships, conventions, decisions |
| [api-documentation.md](docs/api-documentation.md) | API conventions, error envelope, endpoint map |
| [ai-engine.md](docs/ai-engine.md) | Provider abstraction, capabilities, human-in-the-loop, mock provider |
| [security.md](docs/security.md) | Auth, RBAC, isolation, uploads, secrets, webhooks |
| [integration-roadmap.md](docs/integration-roadmap.md) | Connector framework and channel plan |
| [development-roadmap.md](docs/development-roadmap.md) | Phases 1–8 |
| [progress.md](docs/progress.md) | What's done, test results, next steps |
