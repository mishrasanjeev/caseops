import { expect, type APIRequestContext, type APIResponse, type TestInfo } from "@playwright/test";
import { noPaidProviderHeaders } from "./cost-controls";
import { diagnosticProblem, diagnosticRequestId } from "./prod-failure-diagnostics";

type PostOptions = NonNullable<Parameters<APIRequestContext["post"]>[1]>;
const problemBodyLimit = 16_384;

export async function createPatentApplicationWithEvidence(
  api: Pick<APIRequestContext, "post">,
  testInfo: Pick<TestInfo, "attach">,
  apiBaseUrl: string,
  options: PostOptions,
): Promise<APIResponse> {
  const headers = Object.fromEntries(Object.entries(options.headers ?? {})
    .filter(([name]) => name.toLowerCase() !== "x-caseops-automated-test"));
  const startedAt = new Date().toISOString();
  const response = await api.post(`${apiBaseUrl}/api/ip/patents/applications`, {
    ...options, headers: { ...headers, ...noPaidProviderHeaders }, maxRetries: 0, failOnStatusCode: false,
  });
  const finishedAt = new Date().toISOString();
  const status = response.status();
  if (status !== 201) {
    const responseHeaders = response.headers();
    let problem = { requestId: null as string | null, problemType: null as string | null };
    const length = responseHeaders["content-length"];
    if (status >= 400 && /^application\/problem\+json(?:\s*;|$)/i.test(responseHeaders["content-type"] ?? "")
      && /^[1-9]\d{0,4}$/.test(length ?? "") && String(Number(length)) === length
      && Number(length) <= problemBodyLimit) {
      try {
        const body = await response.body();
        const text = body.toString("utf8");
        if (body.byteLength <= problemBodyLimit && Buffer.from(text, "utf8").equals(body)) {
          problem = diagnosticProblem(JSON.parse(text));
        }
      } catch { /* Status survives missing or unreadable diagnostic bodies. */ }
    }
    await testInfo.attach("sanitized-network-evidence", {
      contentType: "application/json",
      body: Buffer.from(JSON.stringify({ schemaVersion: 1, drainTimedOut: false, omitted: 0, records: [{
        route: "ip/application", method: "POST", startedAt, finishedAt, outcome: "response_completed", status,
        requestId: diagnosticRequestId(responseHeaders["x-request-id"]) ?? problem.requestId,
        problemType: problem.problemType,
      }] })),
    });
  }
  expect(status, "Patent application creation must return HTTP 201.").toBe(201);
  return response;
}
