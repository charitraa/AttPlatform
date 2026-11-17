import { type Browser, type Page, expect } from '@playwright/test'

export const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo!Pass2026'
export const USERS = {
  admin: 'admin@acme.test',
  ops: 'ops@acme.test',
  agent: 'agent@acme.test',
  tech: 'tech@acme.test',
  customer: 'customer@acme.test',
} as const
export type Role = keyof typeof USERS

/** A unique, recognisable marker so test data is easy to find (and never collides between runs). */
export const marker = () => `[E2E ${Date.now().toString(36)}]`

/** Sign in through the real login form. */
export async function signIn(page: Page, role: Role) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(USERS[role])
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

/** A separate browser session (its own cookies), e.g. the customer and the agent side by side. */
export async function sessionFor(browser: Browser, role: Role) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await signIn(page, role)
  return { context, page }
}

/** Collects uncaught page errors and failed API calls (5xx) so a test can assert there were none. */
export function watchForErrors(page: Page) {
  const problems: string[] = []
  page.on('pageerror', (e) => problems.push(`page error: ${e.message}`))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 500) problems.push(`${r.status()} ${r.request().method()} ${r.url()}`)
  })
  return problems
}
