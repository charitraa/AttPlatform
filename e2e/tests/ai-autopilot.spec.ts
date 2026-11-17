import { expect, test } from '@playwright/test'
import { marker, sessionFor } from './helpers'

/**
 * Uses the real AI provider configured on the server (slow, costs API calls). Skip with
 * `npm run test:fast`. Needs the demo organization's autopilot switches on.
 */
test('@ai the autopilot categorises, assigns, dispatches and replies to an urgent request', async ({ browser }) => {
  test.setTimeout(240_000)
  const title = `${marker()} Cold room alarm: temperature rising`
  const customer = await sessionFor(browser, 'customer')
  const c = customer.page
  await c.goto('/portal/new')
  await c.getByLabel("What's the problem?").fill(title)
  await c.getByLabel('Details').fill(
    'The walk-in cold room is at 9C and rising, the compressor keeps restarting. 800 kg of fish inside. Urgent, please send someone.',
  )
  await c.getByRole('button', { name: 'Send request' }).click()
  await expect(c).toHaveURL(/\/portal\/tickets\//)

  // The customer receives the automatic reply (no reload needed).
  await expect(c.getByText(/automated assistant/)).toBeVisible({ timeout: 180_000 })
  await expect(c.getByText(/^Automated assistant ·/)).toBeVisible()
  await expect(c.getByText(/knowledge articles? (were|was) (not )?(used|referenced)/i)).toHaveCount(0)

  // Staff see what the AI did, labelled as AI.
  const staff = await sessionFor(browser, 'ops')
  const s = staff.page
  await s.goto('/tickets')
  await s.getByRole('link', { name: title }).click()
  await expect(s.getByText('AI assistant').first()).toBeVisible()
  await expect(s.getByText('Refrigeration').first()).toBeVisible()
  await expect(s.getByRole('link', { name: /^WO-\d+$/ })).toBeVisible()  // the Work orders card
  await expect(s.getByText(/^\[[^\]]+\]$/)).toHaveCount(0)  // no "[Your Name]" style placeholders
  await customer.context.close()
  await staff.context.close()
})
