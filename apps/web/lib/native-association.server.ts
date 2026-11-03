import { readNativeLinkConfig } from './native-link-config.cjs';

export type NativeAssociationKind = 'assetlinks' | 'appleAppSiteAssociation';

// Serves the platform association file projected from the same immutable
// native-link input the sign-in policy reads. Unconfigured and local-acceptance
// runtimes publish nothing; a configured but invalid input fails closed.
export function nativeAssociationResponse(
  kind: NativeAssociationKind,
  env: Record<string, string | undefined> = process.env,
): Response {
  const configured = !!(env.CASEOPS_NATIVE_LINK_CONFIG_FILE || env.CASEOPS_NATIVE_LINK_CONFIG_SHA256);
  if (env.NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE === '1' || !configured) {
    return new Response('Not found', { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }
  const { projections } = readNativeLinkConfig(env);
  // An Android-only input has no iOS application, so no AASA is published.
  if (projections[kind] === null) {
    return new Response('Not found', { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }
  return new Response(JSON.stringify(projections[kind]), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
  });
}
