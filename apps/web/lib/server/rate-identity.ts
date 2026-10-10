import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { isIP } from "node:net";

export const DEMO_TARGET = "/api/billing/enrollments/demo-request";
export const READINESS_TARGET = "/api/health/rate-identity";
const HEX = /^[0-9a-f]{64}$/;
const FORWARD_NAMES = ["x-caseops-rate-client-ip", "x-caseops-rate-timestamp", "x-caseops-rate-signature"];

export class InvalidRateIdentity extends Error {
  constructor() { super("Verified rate identity is unavailable."); }
}

function key(): string | undefined {
  const value = process.env.CASEOPS_RATE_IDENTITY_EDGE_SECRET;
  if (value !== undefined && !HEX.test(value)) throw new InvalidRateIdentity();
  return value;
}

function strictIP(value: string): string {
  if (!value || value.length > 45 || value !== value.trim() || value.includes("%") || !isIP(value)) {
    throw new InvalidRateIdentity();
  }
  if (isIP(value) === 4) return value;
  const canonical = new URL(`http://[${value}]/`).hostname.slice(1, -1);
  const mapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(canonical);
  if (mapped) {
    const high = parseInt(mapped[1], 16), low = parseInt(mapped[2], 16);
    return [high >>> 8, high & 255, low >>> 8, low & 255].join(".");
  }
  return canonical;
}

export function verifiedEdgeIP(headers: Headers): string | undefined {
  if (FORWARD_NAMES.some((name) => headers.has(name))) throw new InvalidRateIdentity();
  const secret = key();
  const ip = headers.get("x-caseops-edge-client-ip");
  const token = headers.get("x-caseops-edge-attestation");
  const required = process.env.CASEOPS_RATE_IDENTITY_REQUIRED === "true";
  if (required && (process.env.CASEOPS_RATE_IDENTITY_EDGE_HTTPS !== "true" || !secret)) {
    throw new InvalidRateIdentity();
  }
  if (ip === null && token === null && !required) return undefined;
  // Headers joins duplicate values with a comma, rejected by strict IP/hex parsing.
  if (!secret || ip === null || token === null || !HEX.test(token)
      || !timingSafeEqual(Buffer.from(token, "ascii"), Buffer.from(secret, "ascii"))) {
    throw new InvalidRateIdentity();
  }
  return strictIP(ip);
}

export function forwardedRateHeaders(headers: Headers, method: string, path: string): Record<string, string> {
  if (!((method === "POST" && path === DEMO_TARGET) || (method === "GET" && path === READINESS_TARGET))) {
    throw new InvalidRateIdentity();
  }
  const ip = verifiedEdgeIP(headers);
  if (ip === undefined) return {};
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const message = `caseops-rate-v1\n${method}\n${path}\n${ip}\n${timestamp}`;
  return {
    "x-caseops-rate-client-ip": ip,
    "x-caseops-rate-timestamp": timestamp,
    "x-caseops-rate-signature": createHmac("sha256", key()!).update(message, "ascii").digest("hex"),
  };
}
