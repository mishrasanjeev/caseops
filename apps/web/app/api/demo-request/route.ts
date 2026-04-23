import { createHash } from "node:crypto";

import { NextResponse } from "next/server";
import nodemailer from "nodemailer";

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

// Forward demo requests to the founder inbox. Uses Gmail SMTP via
// nodemailer. Env vars:
//   CASEOPS_SMTP_HOST       — default smtp.gmail.com
//   CASEOPS_SMTP_PORT       — default 465 (implicit TLS); 587 for STARTTLS
//   CASEOPS_SMTP_USER       — the Gmail address that will send (required)
//   CASEOPS_SMTP_PASSWORD   — Gmail **app password** (16 chars), not the
//                             account password. Generated at
//                             https://myaccount.google.com/apppasswords
//                             with 2FA enabled.
//   CASEOPS_DEMO_NOTIFY_TO   — recipient (default mishra.sanjeev@gmail.com)
//   CASEOPS_DEMO_NOTIFY_FROM — From header (default: "CaseOps <SMTP_USER>")
// When SMTP_USER or SMTP_PASSWORD is missing (local dev), the function
// silently returns — the request is still acked to the client and logged.
async function notifyFounder(payload: {
  name: string;
  email: string;
  company: string;
  role: string;
}): Promise<void> {
  const user = process.env.CASEOPS_SMTP_USER;
  const pass = process.env.CASEOPS_SMTP_PASSWORD;
  if (!user || !pass) return;

  const host = process.env.CASEOPS_SMTP_HOST ?? "smtp.gmail.com";
  const port = Number(process.env.CASEOPS_SMTP_PORT ?? "465");
  const secure = port === 465;
  const to = process.env.CASEOPS_DEMO_NOTIFY_TO ?? "mishra.sanjeev@gmail.com";
  const from = process.env.CASEOPS_DEMO_NOTIFY_FROM ?? `CaseOps <${user}>`;
  const subject = `New demo request — ${payload.company}`;
  const escape = (s: string) =>
    s.replace(/[&<>"']/g, (c) =>
      c === "&" ? "&amp;" :
      c === "<" ? "&lt;" :
      c === ">" ? "&gt;" :
      c === "\"" ? "&quot;" : "&#39;",
    );
  const html =
    `<p>A new demo request came in on caseops.ai.</p>` +
    `<table cellpadding="6" style="border-collapse:collapse;font-family:system-ui,sans-serif;font-size:14px">` +
    `<tr><td><strong>Name</strong></td><td>${escape(payload.name)}</td></tr>` +
    `<tr><td><strong>Email</strong></td><td><a href="mailto:${escape(payload.email)}">${escape(payload.email)}</a></td></tr>` +
    `<tr><td><strong>Firm / company</strong></td><td>${escape(payload.company)}</td></tr>` +
    `<tr><td><strong>Role</strong></td><td>${escape(payload.role)}</td></tr>` +
    `</table>` +
    `<p style="color:#666;font-size:12px">Sent ${new Date().toISOString()} from the CaseOps landing page.</p>`;
  const text =
    `New demo request on caseops.ai\n\n` +
    `Name: ${payload.name}\n` +
    `Email: ${payload.email}\n` +
    `Firm / company: ${payload.company}\n` +
    `Role: ${payload.role}\n\n` +
    `Sent ${new Date().toISOString()}.`;

  try {
    const transporter = nodemailer.createTransport({
      host,
      port,
      secure,
      auth: { user, pass },
    });
    await transporter.sendMail({
      from,
      to,
      replyTo: payload.email,
      subject,
      html,
      text,
    });
  } catch (err) {
    // Surface in logs but do not fail the user — the PII-redacted
    // log line still records the request hash for reconciliation.
    console.warn(
      JSON.stringify({
        event: "demo_request_notify_error",
        reason: err instanceof Error ? err.message : "unknown",
        email_hash: emailHashForDedupe(payload.email),
      }),
    );
  }
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

  // Notify the founder inbox. Fire-and-forget so a slow mail provider
  // never blocks the client's 202. The log line above still records
  // that the request arrived even if Resend is misconfigured.
  void notifyFounder({ name, email, company, role });

  return NextResponse.json({ accepted: true }, { status: 202 });
}
