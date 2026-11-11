# ATT Platform — Development Roadmap

Each phase ends with: working features, migrations, tests passing, docs updated, and
an entry in [`progress.md`](progress.md).

## Phase 1 — Foundation
- Repository structure, docs (architecture, database, API, AI, security, integrations)
- Docker Compose: PostgreSQL, Redis, backend (Daphne), Celery worker, Celery beat,
  frontend (Vite), Nginx
- Django project: split settings, env config, DRF, OpenAPI, CORS, Channels, Celery,
  logging with request IDs, central exception handler, pagination, health/readiness
- `core` app: base models (UUID, timestamps, org-scoped), event bus skeleton
- React app: Vite + TS + Tailwind + shadcn/ui, router, TanStack Query, Zustand,
  API client, theming (light/dark), app shell (collapsible sidebar, top bar),
  system status page wired to real health API
- Test harness: pytest (backend), Vitest + Testing Library (frontend)

## Phase 2 — Identity & tenancy
- Custom User (email login), Organization, Membership, Role, Permission, Invitation
- JWT login/refresh/logout, registration, invitation acceptance, forgot/reset password
- RBAC permission classes, org-scoped base viewset, audit log service
- Frontend: login, forgot/reset password, auth store, protected routes, role-aware
  navigation, profile settings, user management, organization settings
- Seed command: demo organization with users for every role

## Phase 3 — Ticketing engine
- Customers, contacts, assets (base), categories, tickets, comments/internal notes,
  attachments (secure upload), history, assignments, state machine, archive
- Search/filter/sort/paginate, dashboard metrics from real data
- Frontend: tickets table, ticket details with timeline, create ticket form,
  customers pages, dashboard charts

## Phase 4 — AI engine
- Provider abstraction, mock + Anthropic + OpenAI-compatible providers
- AIAnalysis/AIRecommendation, Celery AI queue, classification, priority,
  summarisation, hybrid routing, response suggestions, knowledge base + assistant,
  knowledge extraction review flow, insights
- Frontend: AI panel on ticket, recommendation accept/override, AI Assistant page,
  AI Insights page

## Phase 5 — Field service
- Technicians, skills, certifications, availability, service areas, location
- Work orders + state machine, evidence uploads, appointments, completion report,
  customer confirmation
- Frontend: technicians list/details, work orders list/details, scheduling calendar,
  mobile technician interface

## Phase 6 — SLA, notifications, real-time
- Business hours, SLA policies/targets, SLA instances, monitor task, warnings,
  breaches, escalation
- Notifications (in-app, email), preferences, WebSocket push, client cache
  invalidation
- Frontend: SLA management, notifications page/center, live countdowns

## Phase 7 — Integrations, analytics, portal
- Integration framework, encrypted credentials, outbound/inbound webhooks, retries,
  logs; SMS/WhatsApp adapters (architecture)
- Analytics reports with date filters and CSV export
- Customer portal: ticket creation, tracking, feedback
- Frontend: integrations, analytics, portal routes

## Phase 8 — Hardening
- Security audit against `security.md`, `check --deploy`, dependency audit
- Coverage gaps, workflow end-to-end tests, performance (query counts, indexes,
  caching), production Docker images, deployment guide
