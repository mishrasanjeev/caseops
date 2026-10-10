import { test as base, type Request, type Response } from "@playwright/test";
import { diagnosticRequestId, diagnosticRoute, diagnosticTransport } from "./prod-failure-diagnostics";
import { BoundedNetworkEvidence } from "./bounded-network-evidence";

export { expect, request } from "@playwright/test";

type SafeSnapshot = { omitted: number; records: Array<Record<string, unknown>> };

export const test = base.extend<{ safeNetworkEvidence: { snapshot: () => SafeSnapshot } }>({
  safeNetworkEvidence: [async ({ page, baseURL }, use, testInfo) => {
    const origins = [baseURL, process.env.PROD_BASE_URL, process.env.PROD_API_BASE_URL,
      process.env.CASEOPS_WEB_BASE_URL, process.env.CASEOPS_API_BASE_URL,
      process.env.CASEOPS_E2E_API_PORT ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT}` : null,
      "https://caseops.ai", "https://api.caseops.ai"]
      .filter((value): value is string => Boolean(value))
      .map((value) => new URL(value).origin);
    const evidence = new BoundedNetworkEvidence<Request>();
    const started = (request: Request) => {
      const route = diagnosticRoute(request.url(), origins);
      if (!route) return;
      const method = request.method();
      if (!/^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(method)) return;
      evidence.start(request, { route, method, startedAt: new Date().toISOString() });
    };
    const received = (response: Response) => {
      // Playwright body() cannot bound decoded allocation. Retain only the
      // fixed status and validated request identity, with no asynchronous work.
      evidence.received(response.request(), response.status(),
        diagnosticRequestId(response.headers()["x-request-id"]));
    };
    const finished = (request: Request) => evidence.finish(request, new Date().toISOString());
    const failed = (request: Request) => evidence.fail(request, new Date().toISOString(),
      diagnosticTransport(request.failure()?.errorText));
    page.on("request", started);
    page.on("response", received);
    page.on("requestfinished", finished);
    page.on("requestfailed", failed);
    try { await use({ snapshot: () => evidence.snapshot() }); }
    finally {
      page.off("request", started);
      page.off("response", received);
      page.off("requestfinished", finished);
      page.off("requestfailed", failed);
      if (testInfo.status !== testInfo.expectedStatus) {
        evidence.retainPending();
        await testInfo.attach("sanitized-network-evidence", {
          body: Buffer.from(JSON.stringify({ schemaVersion: 1, drainTimedOut: false, ...evidence.snapshot() })),
          contentType: "application/json",
        });
      }
    }
  }, { auto: true }],
});
