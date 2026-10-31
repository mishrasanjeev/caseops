import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { GET, dynamic } from './route';

describe('native record link browser fallback', () => {
  it('returns static anonymous guidance without redirecting or issuing authority', async () => {
    const response = GET();
    expect(response.status).toBe(200);
    expect(dynamic).toBe('force-dynamic');
    expect(response.headers.get('location')).toBeNull();
    expect(response.headers.get('set-cookie')).toBeNull();
    const html = await response.text();
    expect(html).toContain('sign in to the matching workspace');
    expect(html).not.toMatch(/fetch\(|XMLHttpRequest|https?:\/\/|caseops:\/\//);
  });

  it('scrubs the URL with one fixed hash-authorized script without reading it', async () => {
    const response = GET();
    const html = await response.text();
    const scripts = [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('script')];
    expect(scripts).toHaveLength(1);
    expect(scripts[0].textContent).toBe("window.history.replaceState(null,'','/native/open');");
    const hash = createHash('sha256').update(scripts[0].textContent || '').digest('base64');
    expect(response.headers.get('content-security-policy')).toBe(`default-src 'none'; script-src 'sha256-${hash}'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`);
    expect(html).not.toMatch(/location\.|document\.|URLSearchParams|innerHTML|eval\(/);
  });

  it('prevents storage, framing, referrers and indexing', () => {
    const response = GET();
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(response.headers.get('referrer-policy')).toBe('no-referrer');
    expect(response.headers.get('x-robots-tag')).toBe('noindex, nofollow');
    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
  });
});
