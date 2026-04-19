import { createHash } from "node:crypto";

import { NextResponse } from "next/server";

type DemoRequestPayload = {
  name?: string;
  email?: string;
  company?: string;
  role?: string;
};

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

// Codex's 2026-04-19 cybersecurity review (finding #10) flagged that
// this public endpoint logged raw PII (name + email + company + role)
// and had no anti-automation. Replaced with: (a) PII-redacted
// structured logging — only field presence + a stable email hash for
// dedupe diagnostics, (b) per-IP token-bucket rate limit. The actual
// demo request still gets handled (logged + acked) but the audit
// trail no longer carries plain-text PII.

const RATE_LIMIT_PER_IP = 5; // requests per window
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour
type Bucket = { count: number; resetAt: number };
const buckets = new Map<string, Bucket>();

function clientIp(request: Request): string {
  // Standard proxy header order. Trust whichever the platform sets
  // first; Cloud Run forwards via X-Forwarded-For.
  const xff = request.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0].trim();
  const real = request.headers.get("x-real-ip");
  if (real) return real;
  return "unknown";
}

function rateLimitOk(ip: string): boolean {
  const now = Date.now();
  const existing = buckets.get(ip);
  if (!existing || existing.resetAt < now) {
    buckets.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return true;
  }
  if (existing.count >= RATE_LIMIT_PER_IP) return false;
  existing.count += 1;
  return true;
}

function emailHashForDedupe(email: string): string {
  // Truncated SHA-256 — enough to dedupe in logs, not enough to
  // reverse the email.
  return createHash("sha256").update(email.toLowerCase()).digest("hex").slice(0, 12);
}

export async function POST(request: Request) {
  const ip = clientIp(request);
  if (!rateLimitOk(ip)) {
    return NextResponse.json(
      { error: "Too many requests. Try again later." },
      { status: 429, headers: { "Retry-After": "3600" } },
    );
  }

  let body: DemoRequestPayload;
  try {
    body = (await request.json()) as DemoRequestPayload;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const name = (body.name ?? "").toString().trim();
  const email = (body.email ?? "").toString().trim();
  const company = (body.company ?? "").toString().trim();
  const role = (body.role ?? "").toString().trim();

  if (!name || !email || !company || !role) {
    return NextResponse.json({ error: "All fields are required." }, { status: 400 });
  }
  if (!isValidEmail(email)) {
    return NextResponse.json({ error: "Please provide a valid work email." }, { status: 400 });
  }
  if (name.length > 200 || email.length > 200 || company.length > 200 || role.length > 200) {
    return NextResponse.json({ error: "Field too long." }, { status: 400 });
  }

  // PII-redacted log line. Email hash lets ops correlate a dupe-burst
  // without reversing identity.
  console.log(
    JSON.stringify({
      event: "demo_request",
      name_present: name.length > 0,
      email_hash: emailHashForDedupe(email),
      company_present: company.length > 0,
      role_present: role.length > 0,
      at: new Date().toISOString(),
    }),
  );

  return NextResponse.json({ accepted: true }, { status: 202 });
}
