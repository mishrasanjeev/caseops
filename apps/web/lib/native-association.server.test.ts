import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { nativeAssociationResponse } from './native-association.server';

const folders: string[] = [];
afterEach(() => { for (const folder of folders.splice(0)) rmSync(folder, { recursive: true, force: true }); });

function configured(overrides: Record<string, unknown> = {}) {
  const folder = mkdtempSync(path.join(os.tmpdir(), 'caseops-association-'));
  folders.push(folder);
  const file = path.join(folder, 'production.json');
  const bytes = JSON.stringify({
    schemaVersion: 1, kind: 'caseops-native-links', syntheticDataOnly: false,
    redirectUri: 'https://caseops.ai/native/oauth/callback',
    ios: { bundleIdentifier: 'ai.caseops.mobile', applicationIdentifierPrefix: 'X9Y8Z7W6V5' },
    android: { packageName: 'ai.caseops.mobile',
      signingCertificateSha256: ['ebf387aaef4a5bf0de29d82bac7f6267988895bc48f63a518d23b1fb4690ec8f'] },
    ...overrides,
  });
  writeFileSync(file, bytes);
  return { CASEOPS_NATIVE_LINK_CONFIG_FILE: file,
    CASEOPS_NATIVE_LINK_CONFIG_SHA256: createHash('sha256').update(bytes).digest('hex') };
}

describe('native association files', () => {
  it('publish nothing without a configured input or in local acceptance', async () => {
    for (const kind of ['assetlinks', 'appleAppSiteAssociation'] as const) {
      const absent = nativeAssociationResponse(kind, {});
      expect(absent.status).toBe(404);
      expect(absent.headers.get('Cache-Control')).toBe('no-store');
      const local = nativeAssociationResponse(kind, { ...configured(), NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE: '1' });
      expect(local.status).toBe(404);
    }
  });

  it('serve the exact Digital Asset Links projection', async () => {
    const response = nativeAssociationResponse('assetlinks', configured());
    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('application/json');
    expect(await response.json()).toEqual([{
      relation: ['delegate_permission/common.handle_all_urls'],
      target: { namespace: 'android_app', package_name: 'ai.caseops.mobile',
        sha256_cert_fingerprints: ['EB:F3:87:AA:EF:4A:5B:F0:DE:29:D8:2B:AC:7F:62:67:98:88:95:BC:48:F6:3A:51:8D:23:B1:FB:46:90:EC:8F'] },
    }]);
  });

  it('serve the exact apple-app-site-association projection', async () => {
    const response = nativeAssociationResponse('appleAppSiteAssociation', configured());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ applinks: { details: [{
      appIDs: ['X9Y8Z7W6V5.ai.caseops.mobile'],
      components: [{ '/': '/native/oauth/callback' }, { '/': '/native/open/*' }],
    }] } });
  });

  it('fail closed for a tampered, partial or synthetic input', () => {
    const env = configured();
    expect(() => nativeAssociationResponse('assetlinks', { ...env, CASEOPS_NATIVE_LINK_CONFIG_SHA256: '0'.repeat(64) }))
      .toThrow(/HASH_MISMATCH/);
    expect(() => nativeAssociationResponse('assetlinks', { CASEOPS_NATIVE_LINK_CONFIG_FILE: env.CASEOPS_NATIVE_LINK_CONFIG_FILE }))
      .toThrow(/IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED/);
    expect(() => nativeAssociationResponse('assetlinks', configured({ syntheticDataOnly: true })))
      .toThrow(/SYNTHETIC_NATIVE_LINK_CONFIG_FORBIDDEN/);
  });
});
