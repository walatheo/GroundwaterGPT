import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('renders inline comparison chart and downloads chart CSV', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('button', { name: /AI Assistant/i })).toBeVisible()
  await page.getByRole('button', { name: /AI Assistant/i }).click()

  const chatInput = page.getByPlaceholder(/Ask about groundwater levels, aquifers/i)
  await expect(chatInput).toBeVisible()
  await chatInput.fill('Compare G-3336 and G-5004')
  await chatInput.press('Enter')

  await expect(page.getByText(/Monthly Groundwater Levels/i)).toBeVisible()
  await expect(page.locator('.recharts-responsive-container')).toBeVisible()
  await expect(page.getByText(/Chart Insights/i)).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Monthly CSV$/ }).click()
  const download = await downloadPromise

  expect(download.suggestedFilename()).toMatch(/\.csv$/)

  const outputPath = test.info().outputPath(download.suggestedFilename())
  await download.saveAs(outputPath)

  const csv = readFileSync(outputPath, 'utf8')
  expect(csv).toContain('date')
  expect(csv).toContain('Miami-Dade G-3336')
  expect(csv).toContain('Miami-Dade G-5004')
  expect(csv).toContain('Cohort Average')
})

test('renders Estero cohort chart with insights for trend query', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('button', { name: /AI Assistant/i })).toBeVisible()
  await page.getByRole('button', { name: /AI Assistant/i }).click()

  const chatInput = page.getByPlaceholder(/Ask about groundwater levels, aquifers/i)
  await expect(chatInput).toBeVisible()
  await chatInput.fill('Estero trends')
  await chatInput.press('Enter')

  await expect(page.getByText(/Monthly Groundwater Levels/i).first()).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.recharts-responsive-container').first()).toBeVisible()
  await expect(page.getByText(/Chart Insights/i).first()).toBeVisible()
})
