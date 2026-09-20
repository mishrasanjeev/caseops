const DEFAULT_API_BASE_URL = "http://localhost:8000";
const DEFAULT_APP_URL = "http://localhost:3000";

type ContentSecurityPolicyInput = {
  nonce: string;
  apiBaseUrl?: string;
  appUrl?: string;
};

function loopbackConnectSources(apiBaseUrl: string): string[] {
  const sources = [apiBaseUrl];
  try {
    const parsed = new URL(apiBaseUrl);
    if (parsed.protocol !== "http:") return sources;
    if (parsed.hostname === "localhost") {
      parsed.hostname = "127.0.0.1";
      sources.push(parsed.toString().replace(/\/$/, ""));
    } else if (parsed.hostname === "127.0.0.1") {
      parsed.hostname = "localhost";
      sources.push(parsed.toString().replace(/\/$/, ""));
    }
  } catch {
    return sources;
  }
  return Array.from(new Set(sources));
}

export function buildContentSecurityPolicy({
  nonce,
  apiBaseUrl = DEFAULT_API_BASE_URL,
  appUrl = DEFAULT_APP_URL,
}: ContentSecurityPolicyInput): string {
  const apiConnectSources = loopbackConnectSources(apiBaseUrl).join(" ");
  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "style-src 'self' 'unsafe-inline'",
    `script-src 'self' 'nonce-${nonce}' https://www.googletagmanager.com`,
    "img-src 'self' data: blob: https://www.googletagmanager.com https://api.indiankanoon.org",
    "font-src 'self' data:",
    `connect-src 'self' ${apiConnectSources} ${appUrl} https://www.google-analytics.com https://analytics.google.com`,
    "worker-src 'self' blob:",
    "media-src 'self'",
    "manifest-src 'self'",
  ];

  if (apiBaseUrl.startsWith("https://") && appUrl.startsWith("https://")) {
    directives.push("upgrade-insecure-requests");
  }

  return directives.join("; ");
}
