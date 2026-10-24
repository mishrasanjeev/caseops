import { defineConfig } from '@playwright/test';

const runDirectory = `outputs/mobile-web-auth/${new Date().toISOString().replace(/[:.]/g, '-')}`;

export default defineConfig({
  testDir: './tests/mobile-web-auth',
  testMatch: '**/*.spec.ts',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  webServer: {
    command: 'node ../../node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3107',
    cwd: 'apps/web',
    url: 'http://127.0.0.1:3107/native/sign-in',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  outputDir: `${runDirectory}/artifacts`,
  reporter: [['list'], ['json', { outputFile: `${runDirectory}/results.json` }]],
  use: {
    baseURL: 'http://127.0.0.1:3107',
    extraHTTPHeaders: { 'X-CaseOps-Automated-Test': 'no-paid-providers' },
    trace: 'off',
  },
  projects: [
    { name: 'handoff-phone-browser', use: { viewport: { width: 390, height: 844 } } },
    { name: 'handoff-desktop-browser', use: { viewport: { width: 1280, height: 900 } } },
  ],
});
