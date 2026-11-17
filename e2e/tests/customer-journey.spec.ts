import { expect, test } from '@playwright/test'
import { marker, sessionFor } from './helpers'

/**
 * The core loop, with two real browser sessions side by side: a customer raises a request in the
 * portal, staff see it and reply, and the customer reads the reply and answers back.
 */
test('customer request → staff reply → customer answer, live in both browsers', async ({ browser }) => {
  const tag = marker()
  const title = `${tag} Office printer jams on every page`
  const customer = await sessionFor(browser, 'customer')
  const staff = await sessionFor(browser, 'ops')

  // Customer raises the request.
  const c = customer.page
  await c.getByText('New request', { exact: true }).first().click()
  await c.getByLabel("What's the problem?").fill(title)
  await c.getByLabel('Details').fill('Since this morning the second-floor printer jams on every page. Not urgent.')
  await c.getByRole('button', { name: 'Send request' }).click()
  await expect(c).toHaveURL(/\/portal\/tickets\//)
  await expect(c.getByRole('heading', { name: title })).toBeVisible()

  // Staff find it in the ticket list without reloading (pushed over the WebSocket).
  const s = staff.page
  await s.goto('/tickets')
  await expect(s.getByRole('link', { name: title })).toBeVisible({ timeout: 15_000 })
  await s.getByRole('link', { name: title }).click()
  await expect(s.getByRole('heading', { name: title })).toBeVisible()

  // An internal note stays internal; a public reply reaches the customer.
  await s.getByRole('radio', { name: 'Internal note' }).click()
  await s.getByLabel('Internal note').fill(`${tag} internal: probably the fuser`)
  await s.getByRole('button', { name: 'Add note' }).click()
  await expect(s.getByText(`${tag} internal: probably the fuser`)).toBeVisible()
  await s.getByRole('radio', { name: 'Reply to customer' }).click()
  await s.getByLabel('Reply', { exact: true }).fill(`${tag} Thanks! Could you send a photo of the error screen?`)
  await s.getByRole('button', { name: 'Send reply' }).click()
  await expect(s.getByText(`${tag} Thanks! Could you send a photo`)).toBeVisible()

  // The customer sees the reply live, and never the internal note.
  await expect(c.getByText(`${tag} Thanks! Could you send a photo`)).toBeVisible({ timeout: 15_000 })
  await expect(c.getByText(`${tag} internal`)).toHaveCount(0)

  // The customer answers; staff see it arrive without reloading.
  await c.locator('#reply').fill(`${tag} It says "Paper jam in tray 2".`)
  await c.getByRole('button', { name: 'Send' }).click()
  await expect(c.getByText(`${tag} It says "Paper jam in tray 2".`)).toBeVisible()
  await expect(s.getByText(`${tag} It says "Paper jam in tray 2".`)).toBeVisible({ timeout: 15_000 })

  // After a reload everything is still there (it was saved, not just shown).
  await c.reload()
  await expect(c.getByText(`${tag} Thanks! Could you send a photo`)).toBeVisible()
  await customer.context.close()
  await staff.context.close()
})

test('a customer typing staff URLs never sees staff screens', async ({ browser }) => {
  const { page, context } = await sessionFor(browser, 'customer')
  // Staff ticket screens send them to the portal (no assignees, SLA deadlines or escalations).
  for (const [path, landsOn] of [['/tickets', /\/portal$/], ['/tickets/new', /\/portal\/new$/], ['/settings/organization', /\/portal$/]] as const) {
    await page.goto(path)
    await expect(page).toHaveURL(landsOn)
    await expect(page.getByRole('columnheader', { name: 'Assignee' })).toHaveCount(0)
  }
  // Admin-only screens say no.
  for (const path of ['/settings/users', '/analytics', '/integrations']) {
    await page.goto(path)
    await expect(page.getByText("You don't have access to this page")).toBeVisible()
  }
  await context.close()
})
