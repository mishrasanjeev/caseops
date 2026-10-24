import { test, expect } from '@playwright/test';

// Browser-only local UI contract. API mocks do not prove native authentication.
const state = 'b'.repeat(64);
const query = new URLSearchParams({ code_challenge: 'a'.repeat(43), state, platform: 'android', redirect_uri: 'caseops://oauth/callback' });
const identity = { user: { id: 'person-fixture', full_name: 'Example Person', email: 'person@example.test' }, company: { id: 'company-fixture', name: 'Example Legal', slug: 'fixture-legal' }, membership: { id: 'member-fixture', role: 'owner' }, capabilities: [] };

test.beforeEach(async ({ page, baseURL }) => {
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  await page.route('**/api/auth/**', async route => {
    const request = route.request();
    expect(new URL(request.url()).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
    const headers = { 'Access-Control-Allow-Origin': baseURL!, 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': request.headers()['access-control-request-headers'] || 'content-type,x-caseops-automated-test', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' };
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return; }
    expect(request.headers()['x-caseops-automated-test']).toBe('no-paid-providers');
    if (new URL(request.url()).pathname === '/api/auth/me') {
      await route.fulfill({ json: identity, headers }); return;
    }
    if (new URL(request.url()).pathname === '/api/auth/native/authorize') {
      await route.fulfill({ json: { code: 'c'.repeat(43), state, redirect_uri: 'https://attacker.invalid' }, headers }); return;
    }
    throw new Error('Unexpected local authentication route');
  });
});

test('MOB-WEB-01 malformed native request is noindex and exposes no account', async ({ page }) => {
  let reads = 0;
  page.on('request', request => { if (request.url().endsWith('/api/auth/me')) reads++; });
  await page.goto('/native/sign-in?state=incomplete');
  await expect(page.getByRole('main').getByRole('alert')).toHaveText(/invalid or incomplete/);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
  await expect(page.locator('meta[name="referrer"]')).toHaveAttribute('content', 'no-referrer');
  await expect(page.getByRole('button', { name: 'Connect app' })).toHaveCount(0);
  expect(reads).toBe(0);
});

test('MOB-WEB-02 names the exact account and workspace before explicit consent', async ({ page }) => {
  let authorizations = 0;
  page.on('request', request => { if (request.url().endsWith('/api/auth/native/authorize')) authorizations++; });
  await page.goto(`/native/sign-in?${query}`);
  await expect(page.getByText('person@example.test', { exact: true })).toBeVisible();
  await expect(page.getByText('Example Legal / fixture-legal', { exact: true })).toBeVisible();
  const connect = page.getByRole('button', { name: 'Connect app', exact: true });
  await expect(connect).toBeEnabled();
  expect(authorizations).toBe(0);
  const size = await connect.boundingBox();
  expect(size!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const approval = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/auth/native/authorize'));
  await connect.click();
  expect((await approval).postDataJSON()).toEqual({ code_challenge: 'a'.repeat(43), state, platform: 'android', redirect_uri: 'caseops://oauth/callback' });
  await expect(page.getByRole('main').getByRole('alert')).toHaveText(/could not be completed/);
  expect(authorizations).toBe(1);
  expect(new URL(page.url()).hostname).toBe('127.0.0.1');
});

test('MOB-WEB-03 anonymous handoff preserves the exact bounded login return', async ({ page, baseURL }) => {
  await page.route('**/api/auth/me', route => {
    const headers = { 'Access-Control-Allow-Origin': baseURL!, 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': route.request().headers()['access-control-request-headers'] || 'content-type,x-caseops-automated-test', 'Access-Control-Allow-Methods': 'GET,OPTIONS' };
    return route.request().method() === 'OPTIONS' ? route.fulfill({ status: 204, headers }) : route.fulfill({ status: 401, json: { detail: 'Sign in.' }, headers });
  });
  await page.goto(`/native/sign-in?${query}`);
  await page.waitForURL(url => url.pathname === '/sign-in');
  expect(new URL(page.url()).searchParams.get('next')).toBe(`/native/sign-in?${query}`);
  await expect(page.getByRole('button', { name: 'Connect app' })).toHaveCount(0);
});
