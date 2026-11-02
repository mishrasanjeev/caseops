import { createHash } from 'node:crypto';

export const dynamic = 'force-dynamic';
const scrub = "window.history.replaceState(null,'','/native/open');";
const scriptHash = createHash('sha256').update(scrub).digest('base64');

// This anonymous fallback neither reads nor reflects the record locator. The
// app must authenticate and revalidate the exact record before displaying it.
export function GET(): Response {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Open CaseOps</title><script>${scrub}</script></head><body><h1>Open this record in CaseOps</h1><p>Return to the CaseOps app and sign in to the matching workspace. If the app did not open, check that the latest version is installed, then open the original link again.</p></body></html>`, {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'private, no-store',
      'Referrer-Policy': 'no-referrer',
      'X-Robots-Tag': 'noindex, nofollow',
      'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': `default-src 'none'; script-src 'sha256-${scriptHash}'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`,
    },
  });
}
