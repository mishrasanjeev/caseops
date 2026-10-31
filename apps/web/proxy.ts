import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { buildContentSecurityPolicy } from "@/lib/security-headers";
import { platformPrivacyHeaders } from "@/lib/platform/privacy";
import { isNativeCallbackDocument, NATIVE_CALLBACK_RESPONSE_HEADERS } from '@/lib/native-callback-headers';

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function proxy(request: NextRequest) {
  if (isNativeCallbackDocument(request.nextUrl.pathname, request.method)) {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.delete('x-nonce');
    requestHeaders.set('Content-Security-Policy', NATIVE_CALLBACK_RESPONSE_HEADERS['Content-Security-Policy']);
    const response = NextResponse.next({ request: { headers: requestHeaders } });
    // Next preserves headers already installed by routing/proxy when sending a
    // Route Handler Response. Set the exact same restricted policy at both layers.
    for (const [name, value] of Object.entries(NATIVE_CALLBACK_RESPONSE_HEADERS)) response.headers.set(name, value);
    return response;
  }
  const nonce = createNonce();
  const contentSecurityPolicy = buildContentSecurityPolicy({
    nonce,
    apiBaseUrl,
    appUrl,
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", contentSecurityPolicy);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
  response.headers.set("Content-Security-Policy", contentSecurityPolicy);
  for (const [name, value] of Object.entries(platformPrivacyHeaders(request.nextUrl.pathname))) {
    response.headers.set(name, value);
  }
  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
