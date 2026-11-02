import { NATIVE_CALLBACK_SCRUB_SCRIPT, NATIVE_CALLBACK_RESPONSE_HEADERS } from '@/lib/native-callback-headers';
export const dynamic = 'force-dynamic';
// A browser fallback receives no credential from this endpoint. Do not reflect,
// exchange, redirect, or log the query's short-lived authorization code/state.
export function GET(): Response {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>Sign-in not completed</title><script>${NATIVE_CALLBACK_SCRUB_SCRIPT}</script></head><body><p>The app did not receive this sign-in. Return to CaseOps and start sign-in again.</p></body></html>`, {
    status: 200,
    headers: NATIVE_CALLBACK_RESPONSE_HEADERS,
  });
}
