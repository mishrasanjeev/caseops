import assert from 'node:assert/strict';

const keys = new Set(['sign-in', 'browser-context', 'firefox-context', 'ios-consent', 'handoff', 'login-result', 'identity', 'native-return',
  'urlOpen', 'urlValue', 'urlClose', 'urlEditor', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace',
  'connect', 'appOpen', 'mfaCode', 'mfaSubmit', 'mfaVerified', 'useAnotherAccount', 'signInLink',
  'prepare-0', 'prepare-1', 'prepare-2', 'afterConnect-0', 'afterConnect-1']);
const actions = new Set(['find', 'check', 'wait', 'click', 'fill', 'read', 'dismiss', 'switch-context']);

export function browserStep(context, key, action) {
  assert.ok(keys.has(key) && actions.has(action), 'SAFE_BROWSER_STEP_NAME_REQUIRED');
  context.record?.({ type: 'browser_step', key, action });
}
