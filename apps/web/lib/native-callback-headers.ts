import { createHash } from 'node:crypto';

export const NATIVE_CALLBACK_PATH = '/native/oauth/callback';
export const NATIVE_CALLBACK_SCRUB_SCRIPT = 'history.replaceState(null,"","/native/oauth/callback");';
const scriptHash = createHash('sha256').update(NATIVE_CALLBACK_SCRUB_SCRIPT).digest('base64');
export const NATIVE_CALLBACK_RESPONSE_HEADERS = Object.freeze({
  'Content-Type': 'text/html; charset=utf-8',
  'Cache-Control': 'no-store',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex, nofollow',
  'Content-Security-Policy': `default-src 'none'; script-src 'sha256-${scriptHash}'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`,
});

export function isNativeCallbackDocument(pathname: string, method: string): boolean {
  return pathname === NATIVE_CALLBACK_PATH && (method === 'GET' || method === 'HEAD');
}
