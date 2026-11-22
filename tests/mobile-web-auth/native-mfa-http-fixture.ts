import assert from "node:assert/strict";
import http from "node:http";

// This is an explicit loopback-only UI transport fixture, never authentication
// evidence. The built browser client receives real HTTP problem responses.
export const mfaFixtureIdentity = {
  user: { id: "person-fixture", full_name: "Example Person", email: "person@example.test" },
  company: { id: "company-fixture", name: "Example Legal", slug: "fixture-legal" },
  membership: { id: "member-fixture", role: "owner" },
  capabilities: [],
};
export const mfaFixtureQuery = new URLSearchParams({
  code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "android",
  redirect_uri: "caseops://oauth/callback",
}).toString();

export type MfaFixtureMode = "verified" | "rejected-code" | "expired-session";
type RequestRow = {
  method: string; route: string; status: number; markerVerified: boolean;
  authorizationHeaderPresent: boolean;
};

export async function startNativeMfaHttpFixture(apiOrigin: string, appOrigin: string, mode: MfaFixtureMode) {
  const api = new URL(apiOrigin), app = new URL(appOrigin);
  assert.ok(api.protocol === "http:" && api.hostname === "127.0.0.1" &&
    Number(api.port) >= 1024 && api.pathname === "/" && !api.search && !api.hash &&
    !api.username && !api.password, "SYNTHETIC_LOOPBACK_API_REQUIRED");
  assert.ok(app.protocol === "http:" && app.hostname === "127.0.0.1" &&
    Number(app.port) >= 1024 && !app.username && !app.password, "SYNTHETIC_LOOPBACK_APP_REQUIRED");
  const requests: RequestRow[] = [];
  const failures: string[] = [];
  let verified = false, identityReadAfterVerification = false, authorizations = 0;
  const deadline = performance.now() + 30_000;
  const check = () => assert.ok(performance.now() < deadline, "MFA_FIXTURE_ORIGINAL_30S_BOUND");
  const server = http.createServer(async (request, response) => {
    const cors = {
      "Access-Control-Allow-Origin": app.origin,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Headers": "content-type,x-caseops-automated-test,x-csrf-token",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Cache-Control": "no-store",
    };
    try {
      check();
      assert.equal(request.socket.remoteAddress, "127.0.0.1");
      const url = new URL(request.url || "", api);
      assert.equal(url.origin, api.origin);
      assert.equal(url.search, "");
      assert.equal(request.headers.origin, app.origin);
      assert.ok(["/api/auth/me", "/api/auth/native/authorize", "/api/auth/mfa/step-up", "/api/auth/refresh"].includes(url.pathname));
      if (request.method === "OPTIONS") {
        // Browser CORS preflight carries the requested header names, never an
        // authentication operation. Every actual API call must have the marker.
        response.writeHead(204, cors); response.end(); return;
      }
      assert.equal(request.headers["x-caseops-automated-test"], "no-paid-providers");
      assert.equal(request.headers.authorization, undefined, "COOKIE_ONLY_NATIVE_AUTH_REQUIRED");
      let status = 200;
      let value: unknown;
      if (request.method === "GET" && url.pathname === "/api/auth/me") {
        if (verified) identityReadAfterVerification = true;
        value = mfaFixtureIdentity;
      } else {
        assert.equal(request.method, "POST");
        let bytes = 0; const chunks: Buffer[] = [];
        for await (const piece of request) {
          check(); bytes += piece.length; assert.ok(bytes <= 4096); chunks.push(piece);
        }
        check();
        const payload = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : null;
        if (url.pathname === "/api/auth/native/authorize") {
          assert.deepEqual(payload, { code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "android", redirect_uri: "caseops://oauth/callback" });
          authorizations++;
          if (mode === "expired-session") {
            status = 401; value = { type: "invalid_token", status, detail: "Session expired. Sign in again." };
          } else if (!verified) {
            status = 403; value = { type: "native_mfa_required", status, detail: "Complete MFA in this browser session before native sign-in." };
          } else {
            assert.equal(identityReadAfterVerification, true);
            assert.equal(authorizations, 2, "ONE_AUTHORIZE_AFTER_EXPLICIT_VERIFICATION");
            value = { code: "c".repeat(43), state: "b".repeat(64), redirect_uri: "caseops://oauth/callback", expires_in: 60 };
          }
        } else if (url.pathname === "/api/auth/mfa/step-up") {
          assert.deepEqual(payload, { code: "123456", purpose: "step_up", method: "totp" });
          if (mode === "rejected-code") {
            status = 403; value = { type: "forbidden", status, detail: "The code was not accepted." };
          } else {
            verified = true; value = { status: "verified", expires_at: new Date(Date.now() + 300_000).toISOString() };
          }
        } else {
          // The expired-session regression must catch even an attempted refresh
          // before any possible bearer replay, without providing a real token.
          status = 503; value = { detail: "Unexpected native authorization refresh." };
        }
      }
      check();
      requests.push({ method: request.method!, route: url.pathname, status, markerVerified: true, authorizationHeaderPresent: false });
      const body = JSON.stringify(value);
      response.writeHead(status, { ...cors, "Content-Type": status >= 400 ? "application/problem+json" : "application/json", "Content-Length": Buffer.byteLength(body) });
      response.end(body);
    } catch {
      failures.push("SYNTHETIC_MFA_HTTP_CONTRACT_REFUSED");
      response.writeHead(500, { ...cors, "Content-Type": "application/json" });
      response.end('{"detail":"Synthetic MFA fixture refused."}');
    }
  });
  server.requestTimeout = 5000;
  server.headersTimeout = 5000;
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject); server.listen(Number(api.port), "127.0.0.1", resolve);
  });
  return {
    requests, failures,
    async stop() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("OWNED_MFA_HTTP_CLOSE_BOUND")), 2000);
        server.close(error => { clearTimeout(timer); if (error) reject(error); else resolve(); });
      });
    },
  };
}
