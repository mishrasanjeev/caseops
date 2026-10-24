export type NativeAuthorization = {
  code_challenge: string;
  state: string;
  platform: 'android' | 'ios';
  redirect_uri: string;
};

export function parseNativeAuthorization(query: string): NativeAuthorization | null {
  const values = new URLSearchParams(query);
  const allowed = ['code_challenge', 'state', 'platform', 'redirect_uri'];
  if ([...values.keys()].some(key => !allowed.includes(key)) || allowed.some(key => values.getAll(key).length !== 1)) return null;
  const challenge = values.get('code_challenge') || '';
  const state = values.get('state') || '';
  const platform = values.get('platform');
  const redirect = values.get('redirect_uri');
  if (!/^[A-Za-z0-9_-]{43}$/.test(challenge) || !/^[A-Za-z0-9_-]{32,128}$/.test(state)
    || !['android', 'ios'].includes(platform || '') || redirect !== 'caseops://oauth/callback') return null;
  return { code_challenge: challenge, state, platform: platform as 'android' | 'ios', redirect_uri: redirect };
}
