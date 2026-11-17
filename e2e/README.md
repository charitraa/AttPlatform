# Browser tests (Playwright)

Real Chromium, driving the running app through nginx the way a person would: landing page,
sign-in and sign-out for each role, the customer ↔ staff conversation in two browsers side by
side (with live updates), every admin page, CSV export, the technician's phone view, and the AI
autopilot end to end.

They run against a stack that is already up with the demo data (`make seed` / `seed_demo`):

```bash
docker compose up -d
# all tests, including the real-AI one (~1-3 min, uses AI API calls):
docker run --rm --network host --ipc=host -v "$PWD/e2e:/e2e" -w /e2e \
  mcr.microsoft.com/playwright:v1.49.1-noble sh -c "npm ci && npx playwright test"
# everything except the AI test:
docker run ... sh -c "npm ci && npx playwright test --grep-invert @ai"
```

- `E2E_BASE_URL` (default `http://localhost:8080`) points them at another deployment.
- Failures keep a trace, screenshot and video in `e2e/test-results/`; the HTML report is in
  `e2e/playwright-report/` (`npx playwright show-report`).
- Tests create tickets titled `[E2E …]` in the demo organization. Clean them up afterwards (quietly: no
  notifications, SLA alerts stop, their work orders are cancelled):
  `docker compose exec backend python manage.py archive_test_tickets --org acme`
- Sign-in is rate limited (5 per minute per account): wait a minute between back-to-back full runs.
