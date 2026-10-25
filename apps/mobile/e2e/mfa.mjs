import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';

export const CONSENT_MFA_VERIFIED = 'Code verified. Select Connect app to continue.';

export function mfaStage(auth) {
  assert.ok(auth.mfaRequired === undefined || typeof auth.mfaRequired === 'boolean', 'EXPLICIT_MFA_REQUIREMENT_REQUIRED');
  if (auth.mfaRequired === true) {
    assert.ok(['login', 'consent'].includes(auth.mfaStage), 'EXPLICIT_MFA_STAGE_REQUIRED');
    return auth.mfaStage;
  }
  assert.equal(auth.mfaStage, undefined, 'MFA_STAGE_REQUIRES_MFA');
  return 'none';
}

export function validateAuthorizationTraffic(requests, auth, { single = false } = {}) {
  const stage = mfaStage(auth);
  const attempts = requests.filter(({ method, route }) => method === 'POST'
    && ['/api/auth/native/authorize', '/api/auth/native/token'].includes(route));
  const expected = [
    ...(stage === 'consent' ? [{ route: '/api/auth/native/authorize', status: 403 }] : []),
    { route: '/api/auth/native/authorize', status: 200 },
    { route: '/api/auth/native/token', status: 200 },
  ];
  assert.ok(attempts.length > 0 && attempts.length % expected.length === 0, 'EXACT_BROWSER_AUTHORIZATION_SEQUENCE_REQUIRED');
  if (single) assert.equal(attempts.length, expected.length, 'REAL_BROWSER_AUTHORIZATION_NOT_ONCE');
  for (let index = 0; index < attempts.length; index++) {
    assert.deepEqual({ route: attempts[index].route, status: attempts[index].status }, expected[index % expected.length],
      'BROWSER_MFA_ATTEMPT_GRANT_OR_TOKEN_SEQUENCE_MISMATCH');
    if (stage === 'consent' && index % expected.length === 0) {
      const window = requests.slice(requests.indexOf(attempts[index]) + 1, requests.indexOf(attempts[index + 1]));
      const verification = window.filter(({ method, route }) => method === 'POST' && route === '/api/auth/mfa/step-up');
      const identity = window.filter(({ method, route }) => method === 'GET' && route === '/api/auth/me');
      assert.equal(verification.length, 1, 'CONSENT_MFA_VERIFICATION_NOT_ONCE');
      assert.equal(verification[0].status, 200, 'CONSENT_MFA_NOT_ACKNOWLEDGED');
      assert.equal(identity.length, 1, 'CONSENT_MFA_FRESH_IDENTITY_NOT_ONCE');
      assert.equal(identity[0].status, 200, 'CONSENT_MFA_FRESH_IDENTITY_NOT_ACKNOWLEDGED');
      assert.ok(window.indexOf(identity[0]) > window.indexOf(verification[0]), 'CONSENT_MFA_IDENTITY_READ_BEFORE_VERIFICATION');
    }
  }
}

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
