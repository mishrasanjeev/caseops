'use strict';

const LOCAL_REDIRECT = 'caseops://oauth/callback';
const CALLBACK_PATH = '/native/oauth/callback';
const RECORD_PATH_PREFIX = '/native/open/';
const DISABLED_NATIVE_LINK_POLICY = Object.freeze({ mode: 'disabled' });
const LOCAL_NATIVE_LINK_POLICY = Object.freeze({ mode: 'local', redirectUri: LOCAL_REDIRECT });
function requireValue(ok, message) { if (!ok) throw new Error(message); }
function keys(value, expected) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...expected].sort().join(',');
}
function httpsCallback(value) {
  if (typeof value !== 'string' || value.length > 512) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.pathname === CALLBACK_PATH
      && value === `${url.origin}${CALLBACK_PATH}` && !url.port
      && !url.username && !url.password && !url.search && !url.hash
      && url.hostname.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
      && url.hostname.includes('.') && !/^[\d.]+$/.test(url.hostname)
      && !url.hostname.endsWith('.localhost') && !url.hostname.includes('..');
  } catch { return false; }
}
function validateNativeLinkConfig(value) {
  requireValue(keys(value, ['schemaVersion', 'kind', 'syntheticDataOnly', 'redirectUri', 'ios', 'android'])
    && value.schemaVersion === 1 && value.kind === 'caseops-native-links'
    && typeof value.syntheticDataOnly === 'boolean', 'NATIVE_LINK_CONFIG_SCHEMA_REQUIRED');
  requireValue(httpsCallback(value.redirectUri), 'EXACT_HTTPS_NATIVE_CALLBACK_REQUIRED');
  requireValue(keys(value.ios, ['bundleIdentifier', 'applicationIdentifierPrefix'])
    && typeof value.ios.bundleIdentifier === 'string' && typeof value.ios.applicationIdentifierPrefix === 'string'
    && /^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+){2,}$/.test(value.ios.bundleIdentifier)
    && /^[A-Z0-9]{10}$/.test(value.ios.applicationIdentifierPrefix), 'EXACT_IOS_APPLICATION_ID_REQUIRED');
  requireValue(keys(value.android, ['packageName', 'signingCertificateSha256'])
    && typeof value.android.packageName === 'string'
    && /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}$/.test(value.android.packageName)
    && Array.isArray(value.android.signingCertificateSha256)
    && value.android.signingCertificateSha256.length >= 1 && value.android.signingCertificateSha256.length <= 4
    && value.android.signingCertificateSha256.every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))
    && new Set(value.android.signingCertificateSha256).size === value.android.signingCertificateSha256.length,
  'EXACT_ANDROID_SIGNING_IDENTITIES_REQUIRED');
  if (!value.syntheticDataOnly) {
    const host = new URL(value.redirectUri).hostname;
    requireValue(!/(?:^|\.)(?:invalid|test|example|localhost)$/.test(host)
      && !/(?:^|\.)example\.(?:com|net|org)$/.test(host)
      && !/(?:^|\.)(?:dev|localacceptance|simulatoracceptance)(?:\.|$)/i.test(value.ios.bundleIdentifier)
      && !/(?:^|\.)(?:dev|localacceptance|simulatoracceptance)(?:\.|$)/i.test(value.android.packageName)
      && !/^(.)\1+$/.test(value.ios.applicationIdentifierPrefix)
      && !['ABCDE12345', 'FAKETEAMID', 'TEAMID12345'].includes(value.ios.applicationIdentifierPrefix)
      && value.android.signingCertificateSha256.every(hash => !/^(.)\1+$/.test(hash)), 'PLACEHOLDER_PRODUCTION_LINK_CONFIG_FORBIDDEN');
  }
  return value;
}
function nativeLinkPolicy(config, sha256) {
  validateNativeLinkConfig(config);
  requireValue(typeof sha256 === 'string' && /^[a-f0-9]{64}$/.test(sha256), 'NATIVE_LINK_CONFIG_HASH_REQUIRED');
  return Object.freeze({ mode: 'https', redirectUri: config.redirectUri, configSha256: sha256 });
}
function allowsNativeRedirect(uri, policy) {
  if (policy?.mode === 'local') return keys(policy, ['mode', 'redirectUri']) && policy.redirectUri === LOCAL_REDIRECT && uri === LOCAL_REDIRECT;
  return policy?.mode === 'https' && keys(policy, ['mode', 'redirectUri', 'configSha256'])
    && typeof policy.configSha256 === 'string' && /^[a-f0-9]{64}$/.test(policy.configSha256) && httpsCallback(policy.redirectUri) && uri === policy.redirectUri;
}
function nativeLinkProjections(config, sha256) {
  const policy = nativeLinkPolicy(config, sha256), url = new URL(config.redirectUri);
  const appId = `${config.ios.applicationIdentifierPrefix}.${config.ios.bundleIdentifier}`;
  return {
    schemaVersion: 1, configSha256: sha256, syntheticDataOnly: config.syntheticDataOnly,
    policy,
    mobile: { ios: { bundleIdentifier: config.ios.bundleIdentifier, associatedDomains: [`applinks:${url.hostname}`] },
      android: { package: config.android.packageName, intentFilters: [{ action: 'VIEW', autoVerify: true,
        category: ['BROWSABLE', 'DEFAULT'], data: [{ scheme: 'https', host: url.hostname, path: CALLBACK_PATH },
          { scheme: 'https', host: url.hostname, pathPrefix: RECORD_PATH_PREFIX }] }] } },
    apiEnvironment: { CASEOPS_NATIVE_REDIRECT_URIS: JSON.stringify([config.redirectUri]) },
    appleAppSiteAssociation: { applinks: { details: [{ appIDs: [appId], components: [{ '/': CALLBACK_PATH }, { '/': `${RECORD_PATH_PREFIX}*` }] }] } },
    assetlinks: [{ relation: ['delegate_permission/common.handle_all_urls'], target: { namespace: 'android_app',
      package_name: config.android.packageName, sha256_cert_fingerprints: config.android.signingCertificateSha256.map(hash => hash.toUpperCase().match(/../g).join(':')) } }],
  };
}
module.exports = { CALLBACK_PATH, RECORD_PATH_PREFIX, DISABLED_NATIVE_LINK_POLICY, LOCAL_NATIVE_LINK_POLICY,
  validateNativeLinkConfig, nativeLinkPolicy, allowsNativeRedirect, nativeLinkProjections };
