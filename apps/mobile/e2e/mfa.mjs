import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';

// Matches services/security.py: RFC 6238 SHA-1, 30 seconds, six digits.
export function totp(secret, now = Date.now()) {
  assert.match(secret || '', /^[A-Z2-7]{16,128}$/, 'SYNTHETIC_TOTP_SECRET_REQUIRED');
  assert.ok(Number.isSafeInteger(now) && now >= 0, 'TOTP_CLOCK_REQUIRED');
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567', bytes = [];
  let bits = 0, count = 0;
  for (const character of secret) {
    bits = (bits << 5) | alphabet.indexOf(character); count += 5;
    if (count >= 8) { count -= 8; bytes.push((bits >>> count) & 255); bits &= (1 << count) - 1; }
  }
  assert.equal(bits, 0, 'TOTP_BASE32_PADDING_INVALID');
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30000)));
  const digest = createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  const offset = digest.at(-1) & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
}
export function fixtureMfaCode(auth, environment = process.env) {
  assert.match(auth.totpSecretEnv || '', /^CASEOPS_MOBILE_[A-Z0-9_]+$/, 'MFA_ENV_NAME_REQUIRED');
  return totp(environment[auth.totpSecretEnv]);
}
