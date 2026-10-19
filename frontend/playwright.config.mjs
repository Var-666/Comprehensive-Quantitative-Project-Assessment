import { defineConfig } from '@playwright/test';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';

process.env.ACCEPTANCE_PASSWORD ||= crypto.randomBytes(24).toString('base64url');

const dbPath = path.join(os.tmpdir(), `project-eval-e2e-${process.pid}.db`);
export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 45000,
  use: { baseURL: process.env.EXTERNAL_UI_URL || 'http://127.0.0.1:5174', channel: 'chrome', headless: true, viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure' },
  webServer: process.env.EXTERNAL_UI_URL ? undefined : [
    {
      command: 'cd ../backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m app.acceptance_seed && ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011',
      url: 'http://127.0.0.1:8011/api/v1/health',
      env: { DATABASE_URL: process.env.E2E_DATABASE_URL || `sqlite:///${dbPath}`, APP_ENV: 'test', DEMO_MODE: 'true', ACCEPTANCE_PASSWORD: process.env.ACCEPTANCE_PASSWORD, COOKIE_SECURE:'false', ALLOWED_ORIGINS:'http://127.0.0.1:5174,http://127.0.0.1:8011' },
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --port 5174',
      url: 'http://127.0.0.1:5174',
      env: { API_PROXY_TARGET: 'http://127.0.0.1:8011' },
      reuseExistingServer: false,
    },
  ],
});
