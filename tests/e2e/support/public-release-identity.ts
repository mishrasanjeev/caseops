import { request } from "@playwright/test";
import { localTransportHeaders } from "./cost-controls";

/** Public reads have no actor credentials. PW still shares its HTTP socket pool. */
export async function assertPublicReleaseIdentity(endpoints: readonly [string, string], expectedSha: string) {
  if (!/^[a-f0-9]{40}$/.test(expectedSha)) throw new Error("Public release identity requires an exact 40-hex SHA.");
  if (endpoints.length !== 2) throw new Error("Public release identity requires the API/web endpoint pair.");
  const paths = ["/api/build", "/api/release-identity"];
  const urls = endpoints.map((endpoint, index) => {
    let url: URL;
    try { url = new URL(endpoint); }
    catch { throw new Error("Invalid public release identity endpoint."); }
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password
      || url.search || url.hash || url.pathname !== paths[index]) {
      throw new Error("Invalid public release identity endpoint.");
    }
    return url.href;
  });
  for (const [index, url] of urls.entries()) {
    const kind = index === 0 ? "API" : "web";
    let stage = "context";
    let failure: string | undefined;
    let api: Awaited<ReturnType<typeof request.newContext>> | undefined;
    try {
      // Per-endpoint jars also prevent a public Set-Cookie crossing to its peer.
      api = await request.newContext({
        storageState: { cookies: [], origins: [] }, httpCredentials: undefined,
        extraHTTPHeaders: localTransportHeaders(url), clientCertificates: [],
      });
      stage = "transport";
      const response = await api.get(url, {
        headers: localTransportHeaders(url), maxRetries: 0, maxRedirects: 0,
      });
      stage = "status";
      if (response.status() !== 200) throw new Error("Unexpected status.");
      stage = "JSON";
      const identity: unknown = await response.json();
      stage = "SHA";
      if (!identity || typeof identity !== "object" || Array.isArray(identity)
        || !("release_sha" in identity) || identity.release_sha !== expectedSha) {
        throw new Error("Unexpected release identity.");
      }
    } catch {
      failure = stage;
    } finally {
      try { await api?.dispose(); }
      catch { failure ??= "cleanup"; }
    }
    // Never propagate PW's request-header call log or a private response body.
    if (failure) throw new Error(`Public ${kind} release identity ${failure} failed; private details omitted.`);
  }
}
