import type { NativeLinkConfig, nativeLinkProjections } from './native-link-policy.cjs';
export function readNativeLinkConfig(env: Record<string, string | undefined>, options?: { allowSynthetic?: boolean }): { config: NativeLinkConfig; sha256: string; bytes: Buffer; projections: ReturnType<typeof nativeLinkProjections> };
