import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:3002',
    headless: true,
  },
  webServer: [
    {
      command: 'cd .. && GROUNDWATERGPT_SKIP_AGENT_INIT=1 uvicorn api.main:app --host 127.0.0.1 --port 8010',
      url: 'http://127.0.0.1:8010/api/chat/status',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev -- --host 127.0.0.1 --port 3002',
      url: 'http://127.0.0.1:3002',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
