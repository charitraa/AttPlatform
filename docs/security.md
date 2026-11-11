# ATT Platform — Security

## 1. Authentication

- Passwords hashed with **Argon2id** (`argon2-cffi`), PBKDF2 kept as fallback for
  migration. Django password validators enforced (min length 10, common-password,
  similarity, numeric).
- **JWT** via `djangorestframework-simplejwt`:
  - Access token: 15 minutes, held **in memory** by the SPA.
  - Refresh token: 7 days, rotated on every refresh, old token blacklisted.
  - Production option: refresh token in an `HttpOnly; Secure; SameSite=Strict`
    cookie scoped to `/api/v1/auth/` (removes XSS access to the long-lived token).
    Development defaults to the same cookie approach so dev mirrors prod.
- Logout blacklists the refresh token. Password change/reset revokes all of the
  user's outstanding refresh tokens.
- Forgot-password always returns 202 regardless of whether the email exists.
- Login is throttled per IP and per email; failed logins are audit-logged.

## 2. Authorization

- RBAC with six system roles; permissions are `<resource>.<action>` codes.
- Checked at the API layer (DRF permission classes) **and** in services for
  critical operations (assign, override AI, change roles, manage integrations).
- **Never trust client-supplied organization IDs, role IDs or permissions.**
  The organization is resolved from the user's membership; `organization` is
  read-only on every serializer; role changes are validated against the actor's
  own role (an Org Admin cannot grant Super Admin).
- Cross-tenant access returns **404**, not 403, to avoid leaking existence.
- Object rules: customers see only their account's tickets and only `public`
  comments/attachments; technicians see only their assigned work orders.
- Every isolation rule has a test (`tests/test_isolation.py` per app).

### Hardening option: PostgreSQL Row Level Security

Application-level scoping is the primary control. RLS policies keyed on a
`app.current_org` session variable can be added later as a second layer.

## 3. Input & file handling

- All input validated by DRF serializers; services re-validate invariants.
- ORM only — no raw SQL with string interpolation.
- Uploads: size limit (default 20 MB, enforced in Nginx **and** Django), extension
  + MIME allowlist validated by content sniffing (`python-magic`), random storage
  names (UUID), originals stored only as metadata, SHA-256 recorded, served via
  authenticated, permission-checked download endpoints (or short-lived signed URLs
  with S3) — never from a public bucket. Images re-encoded to strip EXIF GPS data
  for customer-visible evidence (technician location is captured separately and
  permission-gated).
- Rich text rendered as sanitised Markdown on the frontend; React escaping by default.

## 4. Transport & browser

- HTTPS only in production; HSTS, `SECURE_SSL_REDIRECT`, secure cookies.
- CORS: explicit allowlist from `CORS_ALLOWED_ORIGINS`; credentials only for listed
  origins.
- CSRF: JWT bearer API calls are not CSRF-susceptible; the refresh-cookie endpoint
  and Django admin keep CSRF protection.
- Security headers via Nginx + Django: `Content-Security-Policy`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`,
  `Permissions-Policy` (geolocation only for the technician app origin).

## 5. Rate limiting

DRF throttles backed by Redis: anon, user, login, password-reset, AI, upload scopes.
Nginx `limit_req` as an outer layer in production.

## 6. Secrets

- All secrets come from the environment; `.env` is git-ignored; `.env.example`
  contains placeholders only.
- Tenant integration credentials are encrypted at rest with Fernet
  (`FIELD_ENCRYPTION_KEY`, supports key rotation via `MultiFernet`), are write-only
  through the API (responses show `"configured": true` and the last 4 chars at
  most), and are never logged.
- AI provider keys live only in backend/worker environment; the frontend never
  receives them.
- Production: inject via Docker secrets / the orchestrator's secret store.

## 7. Webhooks

- Outbound: HMAC-SHA256 signature header with timestamp; receivers can verify.
- Inbound: signature verification per provider, timestamp tolerance (replay
  protection), idempotency on `(integration, external_id)`, payload size limits,
  processed asynchronously.
- SSRF protection for user-configured outbound URLs: HTTPS only in prod, block
  private/link-local/loopback ranges after DNS resolution.

## 8. Audit logging

Append-only `AuditLog` for: auth events, role/permission changes, user
(de)activation, ticket create/update/assign/archive, AI overrides, SLA policy
changes, integration config/credential changes, exports. Includes actor, IP, user
agent, request ID. No secrets or passwords in `changes`.

## 9. Privacy

- Technician location tracking requires opt-in (`location_sharing_enabled`), is only
  recorded during active jobs, is visible only to dispatch roles, and is purged after
  the retention period.
- Data minimisation for AI providers (see `ai-engine.md`).

## 10. Dependency & deployment hygiene

- Pinned dependencies; `pip-audit` and `npm audit` in CI.
- Containers run as non-root users; production images contain no dev tools.
- `DEBUG=False` enforced by `prod` settings with startup checks
  (`manage.py check --deploy` in CI).
