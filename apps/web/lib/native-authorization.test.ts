import { describe, expect, it } from 'vitest';
import { parseNativeAuthorization } from './native-authorization';

const query = new URLSearchParams({ code_challenge: 'a'.repeat(43), state: 'b'.repeat(64), platform: 'android', redirect_uri: 'caseops://oauth/callback' }).toString();
describe('native browser authorization admission', () => {
  it('preserves only the bounded native parameters', () => {
    expect(parseNativeAuthorization(query)).toMatchObject({ platform: 'android', state: 'b'.repeat(64) });
  });
  it.each(['code_challenge=short', 'state=short', 'platform=portal', 'redirect_uri=https://attacker.test', 'state=extra', 'return_to=https://attacker.test'])('rejects malformed or duplicate %s', suffix => {
    expect(parseNativeAuthorization(`${query}&${suffix}`)).toBeNull();
  });
  it('rejects an incomplete request', () => { expect(parseNativeAuthorization('')).toBeNull(); });
});
