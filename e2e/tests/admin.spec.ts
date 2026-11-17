import { type Page, expect, test } from '@playwright/test'
import { signIn, watchForErrors } from './helpers'

// One admin session for the whole file (sign-in is rate limited per account).
test.describe.configure({ mode: 'serial' })
let page: Page
let problems: string[]
test.beforeAll(async ({ browser }) => {
  page = await browser.newPage()
  problems = watchForErrors(page)
  await signIn(page, 'admin')
})
test.afterAll(async () => page.close())

const PAGES = [
  ['/', 'Dashboard'], ['/analytics', 'Analytics'], ['/tickets', 'Tickets'], ['/customers', 'Customers'],
  ['/assets', 'Assets'], ['/sla', 'SLA'], ['/ai/assistant', 'AI Assistant'], ['/ai/insights', 'AI Insights'],
  ['/work-orders', 'Work orders'], ['/technicians', 'Technicians'], ['/schedule', 'Schedule'],
  ['/notifications', 'Notifications'], ['/integrations', 'Integrations'], ['/settings/users', 'Users'],
  ['/settings/organization', 'Organization'], ['/system', 'System status'],
] as const

test('every admin page opens without errors', async () => {
  for (const [path, name] of PAGES) {
    await page.getByRole('navigation').first().getByRole('link', { name, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${path === '/' ? '/$' : path}`))
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText('Something went wrong.')).toHaveCount(0)
    await page.waitForLoadState('networkidle')
  }
  expect(problems).toEqual([])
})

test('system status shows every service healthy', async () => {
  await page.goto('/system')
  for (const service of ['API', 'PostgreSQL', 'Redis', 'Real-time (WebSocket)']) {
    await expect(page.getByText(service, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('Operational', { exact: true })).toHaveCount(4)
  expect(problems).toEqual([])
})

test('the AI autopilot switches are on the organization settings page', async () => {
  await page.goto('/settings/organization')
  await expect(page.getByText('AI autopilot')).toBeVisible()
  for (const label of ['Set category and priority', 'Reply to the customer', 'Dispatch a technician']) {
    await expect(page.getByLabel(label)).toBeVisible()
  }
  await expect(page.getByLabel('Ticket routing')).toBeVisible()
})

test('an analytics report downloads as CSV', async () => {
  await page.goto('/analytics')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /export|csv/i }).first().click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)
})
