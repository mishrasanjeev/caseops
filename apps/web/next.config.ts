import type { NextConfig } from "next";

// Codex's 2026-04-19 cybersecurity review (finding #6) flagged the
// missing browser hardening headers. With session tokens currently
// in localStorage (finding #5 — HttpOnly cookie migration tracked
// separately), CSP is doubly important: the browser must contain any
// future XSS sink long enough that a token can't be silently
// exfiltrated. Default-deny everything; allow-list what we actually
// need:
//   - script-src 'self' + 'unsafe-inline' for the JSON-LD script
//     blocks app/layout.tsx ships in <head>
//   - connect-src 'self' + the configured API origin (Cloud Run URL
//     in prod) + Pine Labs payment endpoints + Google Storage for
//     document downloads + sonner toast telemetry (none today)
//   - img-src 'self' + data: + the public app URL (OG image)
//   - style-src 'self' + 'unsafe-inline' (Tailwind + sonner inject
//     dynamic styles; restricting to nonces would force a wider
//     refactor of every component)
//   - font-src 'self' + data: — fonts are bundled (@fontsource), no
//     external CDN
//   - frame-ancestors 'none' = same as X-Frame-Options DENY
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

const cspDirectives: string[] = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  // Tailwind / sonner / Radix inject runtime styles; nonce-based CSP
  // would require a wider refactor. 'unsafe-inline' for styles only —
  // scripts stay locked down to the static inline JSON-LD blocks.
  "style-src 'self' 'unsafe-inline'",
  // 'unsafe-inline' here is needed for the two app/layout.tsx
  // JSON-LD script blocks (Organization + SoftwareApplication
  // schema). Move them to <link rel="alternate"> if we ever need
  // to drop 'unsafe-inline' on script-src.
  "script-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  // The browser uses fetch() to talk to the API. The Pine Labs
  // payment redirect happens via top-level navigation, not fetch,
  // so we don't need to allow it here.
  `connect-src 'self' ${apiBaseUrl} ${appUrl}`,
  "worker-src 'self' blob:",
  "media-src 'self'",
  "manifest-src 'self'",
  "upgrade-insecure-requests",
];

const securityHeaders = [
  // Strict-Transport-Security only meaningful over HTTPS; harmless
  // on HTTP. 1-year max-age + includeSubDomains is the standard
  // safe default once a domain is HTTPS-only in production.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  // CSP. See cspDirectives above for rationale on each directive.
  { key: "Content-Security-Policy", value: cspDirectives.join("; ") },
  // X-Content-Type-Options nosniff prevents content-type smuggling
  // attacks (browser ignores Content-Type guess and uses what the
  // server sent).
  { key: "X-Content-Type-Options", value: "nosniff" },
  // X-Frame-Options DENY is redundant with frame-ancestors 'none'
  // above but kept for older browser compatibility.
  { key: "X-Frame-Options", value: "DENY" },
  // Referrer-Policy: strict-origin-when-cross-origin avoids leaking
  // /app/matters/{id} URLs to external links (e.g. clicking a
  // recommendation citation that opens an external court site).
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Permissions-Policy: opt out of every browser API we don't use,
  // matching the legal-tech threat model (no camera/mic/geo/USB
  // surface needed for the app).
  {
    key: "Permissions-Policy",
    value: [
      "camera=()",
      "microphone=()",
      "geolocation=()",
      "interest-cohort=()",
      "payment=()",
      "usb=()",
      "magnetometer=()",
      "gyroscope=()",
      "accelerometer=()",
    ].join(", "),
  },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        // All routes get the same headers. /app gets stricter
        // referrer downstream if the marketing OG-card sharing
        // surface ever needs looser referrer for image previews.
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
  // Sprint 6 BG-017: /legacy is removed. Existing bookmarks and any
  // stray external links resolve into the new app shell instead of
  // 404ing. Permanent (308) so the browser updates its cache.
  async redirects() {
    return [
      {
        source: "/legacy",
        destination: "/app",
        permanent: true,
      },
      {
        source: "/legacy/:path*",
        destination: "/app",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
