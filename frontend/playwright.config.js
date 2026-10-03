import { defineConfig } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

const root = path.resolve('..');
const python =
  process.env.EMBY_TEST_PYTHON ||
  (process.platform === 'win32'
    ? path.join(root, '.venv/Scripts/python.exe')
    : path.join(root, '.venv/bin/python'));
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 45000,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:18767',
    headless: true,
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_EXECUTABLE_PATH || (fs.existsSync(edge) ? edge : undefined),
      args: ['--enable-unsafe-swiftshader'],
    },
    viewport: { width: 1440, height: 960 },
  },
  webServer: {
    command: `"${python}" tests/fixture.py`,
    url: 'http://127.0.0.1:18767/healthz',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
