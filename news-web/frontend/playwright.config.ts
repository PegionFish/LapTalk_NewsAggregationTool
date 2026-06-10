import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 1,
  use: {
    baseURL: 'http://localhost:8080',
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'cd ../backend && python -m uvicorn main:app --host 0.0.0.0 --port 8080',
    port: 8080,
    timeout: 15000,
    reuseExistingServer: true,
  },
});
