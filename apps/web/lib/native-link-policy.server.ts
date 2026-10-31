import { readNativeLinkConfig } from './native-link-config.cjs';
import { DISABLED_NATIVE_LINK_POLICY, LOCAL_NATIVE_LINK_POLICY, type NativeLinkPolicy } from './native-link-policy.cjs';

export function loadNativeLinkPolicy(): NativeLinkPolicy {
  const local = process.env.NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE === '1';
  const configured = !!(process.env.CASEOPS_NATIVE_LINK_CONFIG_FILE || process.env.CASEOPS_NATIVE_LINK_CONFIG_SHA256);
  if (local) {
    const origin = new URL(process.env.NEXT_PUBLIC_APP_URL || '');
    if (configured || origin.protocol !== 'https:' || !['127.0.0.1', 'localhost', '10.0.2.2'].includes(origin.hostname)
      || origin.href !== `${origin.origin}/` || Number(origin.port) < 1024 || Number(origin.port) > 65535) throw new Error('ISOLATED_LOCAL_NATIVE_POLICY_REQUIRED');
    return LOCAL_NATIVE_LINK_POLICY;
  }
  return configured ? readNativeLinkConfig(process.env).projections.policy : DISABLED_NATIVE_LINK_POLICY;
}
