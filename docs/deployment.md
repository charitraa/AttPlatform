# ATT Platform — Deployment guide (single host, Docker Compose)

This runs the whole platform on one Linux server: PostgreSQL, Redis, the Django ASGI
backend (HTTP + WebSockets), Celery worker and beat, and an Nginx edge that terminates TLS,
serves the built frontend and proxies the API. Verified end to end on 2026-11-13 (see
`progress.md`, Phase 8).

```
Internet ──443──▶ web (Nginx: TLS, SPA, CSP/HSTS, rate limits)
                    ├─ /api, /ws, /admin, /static ──▶ backend (Daphne, Django)
                    └─ everything else ──▶ built SPA (index.html for client-side routes)
backend, worker, beat ──▶ db (PostgreSQL 16) · redis (broker, cache, channels)
```

## 1. Prerequisites

- A Linux server with Docker Engine 24+ and the Compose plugin; 2 vCPU / 4 GB RAM is enough to start.
- A DNS name pointing at the server (below: `att.example.com`), ports 80 and 443 open.
- An SMTP account for email (notifications, password resets).

## 2. Configure

```bash
git clone <your repo> att-platform && cd att-platform
cp .env.prod.example .env.prod
```

Fill in **every** value in `.env.prod`. Generate secrets with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                                 # DJANGO_SECRET_KEY, POSTGRES_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # FIELD_ENCRYPTION_KEYS
```

The backend **refuses to start** with a weak `DJANGO_SECRET_KEY` or without
`FIELD_ENCRYPTION_KEYS`. Store `FIELD_ENCRYPTION_KEYS` in your password manager: without it,
stored integration credentials (WhatsApp, Twilio, mailbox passwords) can't be decrypted.

## 3. TLS certificates

The edge expects `fullchain.pem` and `privkey.pem` in `CERTS_DIR` (default `./certs`).
With Let's Encrypt, before the first start:

```bash
mkdir -p certs certbot
sudo certbot certonly --standalone -d att.example.com
sudo cp /etc/letsencrypt/live/att.example.com/{fullchain,privkey}.pem certs/
```

Renewals can use the webroot the edge already serves (`/.well-known/acme-challenge/` → `./certbot`):

```bash
sudo certbot renew --webroot -w ./certbot --deploy-hook \
  "cp /etc/letsencrypt/live/att.example.com/*.pem $(pwd)/certs/ && docker compose -f $(pwd)/docker-compose.prod.yml exec web nginx -s reload"
```

## 4. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

The one-off `migrate` service applies database migrations (and syncs roles and
permissions) and exits; `backend`, `worker` and `beat` start after it succeeds.
`https://att.example.com/api/v1/health/ready/` should report database and Redis `ok`.

## 5. First organization and admin

The UI has no public sign-up page. Create the first organization through the API:

1. Set `REGISTRATION_ENABLED=true` in `.env.prod` and run the `up -d` command again.
2. Register:
   ```bash
   curl -X POST https://att.example.com/api/v1/auth/register/ -H 'Content-Type: application/json' \
     -d '{"organization_name":"Your Company","first_name":"Ada","last_name":"Admin","email":"ada@yourco.com","password":"<a strong password>"}'
   ```
   The new organization gets its default SLA policy and working hours automatically.
3. Set `REGISTRATION_ENABLED=false` again and re-run `up -d`.
4. Sign in at `https://att.example.com` and invite everyone else from **Users**.

## 6. Configure the organization (in the app)

- **Organization settings**: name, time zone (drives SLA working hours and report days).
- **SLA**: adjust working hours, holidays and targets.
- **Integrations**: WhatsApp (Meta Cloud API — use a *system user* token that never expires),
  email-to-ticket (IMAP; use a dedicated address), outbound webhooks. Credentials are stored encrypted.
- **AI**: set `AI_PROVIDER`/`AI_MODEL`/`AI_API_KEY`/`AI_BASE_URL` in `.env.prod` (see `ai-engine.md`).

## 7. Backups

Back up three things: the database, uploaded files, and the encryption keys.

```bash
# Database (daily, keep several days off-host)
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U att -Fc att > backup-$(date +%F).dump
# Uploaded files (evidence photos, attachments)
docker run --rm -v att-prod_media:/media -v "$PWD":/out alpine tar czf /out/media-$(date +%F).tgz -C /media .
```

Restore: `pg_restore -U att -d att --clean --if-exists < backup.dump` inside the `db` container,
and untar into the `media` volume. Test a restore before you need one.

## 8. Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Migrations run automatically before the new backend starts. Take a database backup first.
Nginx re-resolves the backend's address, so recreating containers doesn't cause 502s.

## 9. Operations

| What | How |
|------|-----|
| Health | `GET /api/v1/health/` (liveness), `/api/v1/health/ready/` (DB + Redis); container healthchecks use them |
| Logs | `docker compose -f docker-compose.prod.yml logs -f backend worker` — JSON lines with request IDs (`X-Request-ID` header on every response) |
| Errors | Set `SENTRY_DSN` to report exceptions (no personal data is sent) |
| Scheduled jobs | Celery beat: SLA monitor (1 min), mailbox polling (2 min), webhook retry sweep (5 min), daily AI insights, location purge |
| Scaling | Add worker concurrency (`CELERY_CONCURRENCY`) first; for more web capacity run more `backend` replicas behind the edge |
| Rotate the encryption key | Prepend a new key to `FIELD_ENCRYPTION_KEYS` (comma-separated, newest first), restart; old values still decrypt |
| Rate limits | Edge: 10/min per IP on login/register/password, 20 req/s per IP on the API; Django throttles behind it |

## 10. Security checklist

- [ ] `.env.prod` is only readable by the deploy user and never committed.
- [ ] `REGISTRATION_ENABLED=false` after the first admin exists.
- [ ] Only ports 80/443 are open (PostgreSQL and Redis are not published).
- [ ] Backups run and a restore has been tested; `FIELD_ENCRYPTION_KEYS` is stored safely.
- [ ] Integration tokens were entered in the app (not shared in chat/email) and are least-privilege.
- [ ] `python manage.py check --deploy --settings=config.settings.prod` is clean (it is in CI-style runs today).
