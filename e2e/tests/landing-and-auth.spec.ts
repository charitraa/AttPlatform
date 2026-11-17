import { expect, test } from '@playwright/test'
import { PASSWORD, USERS, signIn } from './helpers'

test('visitors see the landing page and can go to sign-in', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/welcome$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Every job')
  await page.getByRole('link', { name: 'Sign in' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
})

test('a wrong password is rejected with a message', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(USERS.agent)
  await page.getByLabel('Password').fill('definitely-wrong')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

const homes = [
  { role: 'admin', sees: 'Welcome back', nav: ['Analytics', 'Integrations', 'Users', 'Organization'] },
  { role: 'ops', sees: 'Welcome back', nav: ['Tickets', 'Work orders', 'Schedule'] },
  { role: 'agent', sees: 'Welcome back', nav: ['Tickets', 'Customers'] },
  { role: 'customer', sees: 'Hello, ', nav: ['My requests'] },  // portal home
] as const

for (const { role, sees, nav } of homes) {
  test(`${role} signs in, sees their home and menu, and signs out`, async ({ page }) => {
    await signIn(page, role)
    await expect(page.getByRole('heading', { level: 1 })).toContainText(sees)
    const menu = page.getByRole('navigation').first()
    for (const item of nav) await expect(menu.getByRole('link', { name: item, exact: true })).toBeVisible()
    if (role === 'customer') {
      for (const staffOnly of ['Tickets', 'Dashboard', 'Organization']) {
        await expect(menu.getByRole('link', { name: staffOnly, exact: true })).toHaveCount(0)
      }
    }

    // The session survives a reload (refresh cookie), then sign out ends it.
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toContainText(sees)
    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/(login|welcome)/)
    await page.goto('/tickets')
    await expect(page).toHaveURL(/\/(login|welcome)/)
  })
}

test('the password field is not sent anywhere but the login API', async ({ page }) => {
  const sent: string[] = []
  page.on('request', (r) => {
    if ((r.postData() ?? '').includes(PASSWORD)) sent.push(r.url())
  })
  await signIn(page, 'agent')
  expect(sent.every((u) => u.endsWith('/api/v1/auth/login/'))).toBe(true)
})
