const DEFAULT_API_BASE_URL = "http://localhost:8000";
const DEFAULT_APP_URL = "http://localhost:3000";

type ContentSecurityPolicyInput = {
  nonce: string;
  apiBaseUrl?: string;
  appUrl?: string;
};

export function buildContentSecurityPolicy({
  nonce,
  apiBaseUrl = DEFAULT_API_BASE_URL,
  appUrl = DEFAULT_APP_URL,
}: ContentSecurityPolicyInput): string {
  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "style-src 'self' 'unsafe-inline'",
    `script-src 'self' 'nonce-${nonce}' https://www.googletagmanager.com`,
    "img-src 'self' data: blob: https://www.googletagmanager.com",
    "font-src 'self' data:",
    `connect-src 'self' ${apiBaseUrl} ${appUrl} https://www.google-analytics.com https://analytics.google.com`,
    "worker-src 'self' blob:",
    "media-src 'self'",
    "manifest-src 'self'",
  ];

  if (apiBaseUrl.startsWith("https://") && appUrl.startsWith("https://")) {
    directives.push("upgrade-insecure-requests");
  }

  return directives.join("; ");
}
