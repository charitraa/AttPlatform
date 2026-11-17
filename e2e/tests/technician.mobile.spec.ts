import { expect, test } from '@playwright/test'
import { signIn, watchForErrors } from './helpers'

test('a technician uses My jobs on a phone', async ({ page }) => {
  const problems = watchForErrors(page)
  await signIn(page, 'tech')
  await page.goto('/my-jobs')
  await expect(page.getByRole('heading', { name: 'My jobs' })).toBeVisible()
  // Fits the phone screen: no sideways scrolling.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  // A job, if any, opens its work order.
  const job = page.getByRole('link', { name: /WO-\d+/ }).first()
  if (await job.count()) {
    await job.click()
    await expect(page).toHaveURL(/\/work-orders\//)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  }
  expect(problems).toEqual([])
})

test('the landing page fits a phone screen', async ({ page }) => {
  await page.goto('/welcome')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
