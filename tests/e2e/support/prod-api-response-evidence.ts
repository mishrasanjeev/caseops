import { expect, type APIRequestContext, type APIResponse, type TestInfo } from "@playwright/test";
import { noPaidProviderHeaders } from "./cost-controls";
import { diagnosticRequestId } from "./prod-failure-diagnostics";

type PostOptions = NonNullable<Parameters<APIRequestContext["post"]>[1]>;

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
    // Response bodies are decoded buffers; Content-Length cannot bound their allocation.
    const responseHeaders = response.headers();
    await testInfo.attach("sanitized-network-evidence", {
      contentType: "application/json",
      body: Buffer.from(JSON.stringify({ schemaVersion: 1, drainTimedOut: false, omitted: 0, records: [{
        route: "ip/application", method: "POST", startedAt, finishedAt, outcome: "response_completed", status,
        requestId: diagnosticRequestId(responseHeaders["x-request-id"]), problemType: null,
      }] })),
    });
  }
  expect(status, "Patent application creation must return HTTP 201.").toBe(201);
  return response;
}
