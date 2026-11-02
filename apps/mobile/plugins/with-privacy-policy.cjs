'use strict';
const { withInfoPlist, withAndroidManifest } = require('@expo/config-plugins');
const { policyUrl } = require('./privacy-policy.cjs');
const IOS = ['CaseOpsPrivacyPolicyURL', 'CaseOpsPrivacyPolicyVersion', 'CaseOpsPrivacyPolicySHA256'];
const ANDROID = ['ai.caseops.mobile.PRIVACY_POLICY_URL', 'ai.caseops.mobile.PRIVACY_POLICY_VERSION', 'ai.caseops.mobile.PRIVACY_POLICY_SHA256'];
function policyValues(policy) {
  if (policy === null) return null;
  let origin;
  try { origin = new URL(policy?.url).origin; } catch { throw Error('PRIVACY_POLICY_PROJECTION_REQUIRED'); }
  if (!policy || Object.keys(policy).sort().join(',') !== 'sha256,url,version'
    || !policyUrl(policy.url, origin) || typeof policy.version !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(policy.version)
    || typeof policy.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(policy.sha256)) throw Error('PRIVACY_POLICY_PROJECTION_REQUIRED');
  return [policy.url, policy.version, policy.sha256];
}
function projectIosPrivacyPolicy(info, policy) {
  const values = policyValues(policy);
  for (const key of IOS) delete info[key];
  if (values) IOS.forEach((key, i) => { info[key] = values[i]; });
  return info;
}
function projectAndroidPrivacyPolicy(manifest, policy) {
  const values = policyValues(policy), apps = manifest.manifest?.application;
  if (!Array.isArray(apps) || apps.length !== 1) throw Error('EXACT_ANDROID_APPLICATION_REQUIRED');
  const app = apps[0], prior = app['meta-data'] || [];
  app['meta-data'] = prior.filter(row => !ANDROID.includes(row.$?.['android:name']));
  if (values) ANDROID.forEach((key, i) => app['meta-data'].push({ $: { 'android:name': key, 'android:value': values[i] } }));
  return manifest;
}
function withPrivacyPolicy(config, options = { configured: false }) {
  if (!options || typeof options.configured !== 'boolean'
    || Object.keys(options).sort().join(',') !== (options.configured ? 'configured,policy' : 'configured')) throw Error('PRIVACY_POLICY_PLUGIN_OPTIONS_REQUIRED');
  const policy = options.configured ? options.policy : null;
  policyValues(policy);
  config = withInfoPlist(config, mod => { mod.modResults = projectIosPrivacyPolicy(mod.modResults, policy); return mod; });
  return withAndroidManifest(config, mod => { mod.modResults = projectAndroidPrivacyPolicy(mod.modResults, policy); return mod; });
}
module.exports = withPrivacyPolicy;
module.exports.projectIosPrivacyPolicy = projectIosPrivacyPolicy;
module.exports.projectAndroidPrivacyPolicy = projectAndroidPrivacyPolicy;
