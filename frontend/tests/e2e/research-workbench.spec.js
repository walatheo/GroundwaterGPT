import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('opens assistant wells in the research workbench and exports methods metadata', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: /AI Assistant/i }).click()

  const chatInput = page.getByPlaceholder(/Ask about groundwater, irrigation, crops/i)
  await expect(chatInput).toBeVisible()
  await chatInput.fill('Compare G-3336 and G-5004')
  await chatInput.press('Enter')

  await expect(page.getByRole('button', { name: /Open in Workbench/i })).toBeVisible()
  await page.getByRole('button', { name: /Open in Workbench/i }).click()

  await expect(page.getByText(/Research Workbench/i).first()).toBeVisible()
  await expect(page.getByText(/Miami-Dade G-3336/i).first()).toBeVisible()
  await expect(page.getByText(/Miami-Dade G-5004/i).first()).toBeVisible()

  await page.getByLabel(/Aggregation/i).selectOption('quarterly')
  await expect(page.getByText(/Quarterly Groundwater Comparison/i)).toBeVisible()

  const metricsDownloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Metrics CSV$/ }).click()
  const metricsDownload = await metricsDownloadPromise
  const metricsPath = test.info().outputPath(metricsDownload.suggestedFilename())
  await metricsDownload.saveAs(metricsPath)

  const metricsCsv = readFileSync(metricsPath, 'utf8')
  expect(metricsCsv).toContain('annual_change_ft_yr')
  expect(metricsCsv).toContain('Miami-Dade G-3336')

  const methodsDownloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Methods JSON$/ }).click()
  const methodsDownload = await methodsDownloadPromise
  const methodsPath = test.info().outputPath(methodsDownload.suggestedFilename())
  await methodsDownload.saveAs(methodsPath)

  const methodsJson = readFileSync(methodsPath, 'utf8')
  expect(methodsJson).toContain('"normalization_applies_to_chart_only": true')
  expect(methodsJson).toContain('"aggregation": "quarterly"')
})
