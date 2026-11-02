import { createRequire } from 'node:module';
import { describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '../proxy';
import nextConfig from '../next.config';
import { GET } from '../app/native/oauth/callback/route';

const require = createRequire(import.meta.url);
const { sendResponse } = require('next/dist/server/send-response.js');
const pathname = '/native/oauth/callback';

async function outboundHeaders(requestPath: string, method: string) {
  const output = new Headers();
  for (const rule of await nextConfig.headers!()) {
    if (rule.source === '/:path*' || rule.source === requestPath)
      for (const { key, value } of rule.headers) output.set(key, value);
  }
  const middleware = proxy(new NextRequest(`https://caseops.ai${requestPath}?code=synthetic-private-code&state=synthetic-private-state`, { method }));
  for (const key of ['Content-Security-Policy', 'Referrer-Policy', 'Cache-Control', 'X-Robots-Tag']) {
    const value = middleware.headers.get(key); if (value !== null) output.set(key, value);
  }
  return output;
}

describe('effective native callback headers through pinned Next sendResponse', () => {
  it.each(['GET', 'HEAD'])('preserves the exact static-script hash and privacy policy for %s after global routing/proxy headers', async method => {
    const output = await outboundHeaders(pathname, method), route = GET();
    const response = { statusCode: 0, statusMessage: '', getHeader: (key: string) => output.has(key) ? output.get(key) : undefined,
      appendHeader: (key: string, value: string) => output.append(key, value), originalResponse: { end: vi.fn() } };
    // Execute the installed framework's real existing-header precedence. HEAD
    // exercises that code without a fake streaming server or private request IO.
    await sendResponse({ method: 'HEAD' }, response, route);
    for (const key of ['Content-Security-Policy', 'Referrer-Policy', 'Cache-Control', 'X-Robots-Tag'])
      expect(output.get(key), key).toBe(route.headers.get(key));
    expect(output.get('Content-Security-Policy')).toContain("script-src 'sha256-");
    expect(output.get('Content-Security-Policy')).not.toMatch(/nonce-|unsafe-inline|unsafe-eval/);
    expect([...output.values()].join('\n')).not.toMatch(/synthetic-private-code|synthetic-private-state/);
    expect(response.originalResponse.end).toHaveBeenCalledExactlyOnceWith();
  });

  it('keeps nonce CSP and global hardening on every other native/public route and unsupported callback method', async () => {
    for (const [requestPath, method] of [['/native/sign-in', 'GET'], ['/pricing', 'GET'], [`${pathname}/other`, 'GET'], [`${pathname}/`, 'GET'], [pathname, 'POST']]) {
      const output = await outboundHeaders(requestPath, method);
      expect(output.get('Content-Security-Policy')).toMatch(/script-src 'self' 'nonce-[^']+'/);
      expect(output.get('Content-Security-Policy')).not.toContain("script-src 'sha256-");
      expect(output.get('X-Frame-Options')).toBe('DENY');
      expect(output.get('X-Content-Type-Options')).toBe('nosniff');
      if (requestPath !== pathname) expect(output.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin');
    }
  });
});
