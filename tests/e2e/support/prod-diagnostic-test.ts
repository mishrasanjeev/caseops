import { test as base, type Request } from "@playwright/test";
import { diagnosticProblem, diagnosticRequestId, diagnosticRoute, diagnosticTransport } from "./prod-failure-diagnostics";

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
    const pending = new Map<Request, { route: string; method: string; startedAt: string }>();
    const records: Array<Record<string, unknown>> = [];
    const completions = new Set<Promise<void>>();
    let accepting = true;
    let observed = 0;
    let omitted = 0;
    const started = (request: Request) => {
      const route = diagnosticRoute(request.url(), origins);
      if (!route) return;
      if (observed++ >= 64) { omitted++; return; }
      const method = request.method();
      if (!/^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(method)) return;
      pending.set(request, { route, method, startedAt: new Date().toISOString() });
    };
    const finished = (request: Request) => {
      const entry = pending.get(request);
      if (!entry) return;
      pending.delete(request);
      const finishedAt = new Date().toISOString();
      const completion = (async () => {
        const response = await request.response();
        if (!response) { if (accepting) records.push({ ...entry, finishedAt, outcome: "response_unavailable" }); return; }
        const headers = response.headers();
        let problem = { requestId: null as string | null, problemType: null as string | null };
        const length = Number(headers["content-length"]);
        if (response.status() >= 400 && headers["content-type"]?.startsWith("application/problem+json")
          && Number.isInteger(length) && length > 0 && length <= 16_384) {
          const body = await response.body();
          if (body.byteLength <= 16_384) {
            try { problem = diagnosticProblem(JSON.parse(body.toString("utf8"))); } catch { /* No raw body in evidence. */ }
          }
        }
        if (accepting) records.push({ ...entry, finishedAt, outcome: "response_completed", status: response.status(),
          requestId: diagnosticRequestId(headers["x-request-id"]) ?? problem.requestId,
          problemType: problem.problemType });
      })().catch(() => { if (accepting) records.push({ ...entry, finishedAt, outcome: "diagnostic_unavailable" }); });
      completions.add(completion);
      void completion.finally(() => completions.delete(completion));
    };
    const failed = (request: Request) => {
      const entry = pending.get(request);
      if (!entry) return;
      pending.delete(request);
      records.push({ ...entry, finishedAt: new Date().toISOString(), outcome: "transport_failed",
        failureCode: diagnosticTransport(request.failure()?.errorText) });
    };
    page.on("request", started);
    page.on("requestfinished", finished);
    page.on("requestfailed", failed);
    try { await use({ snapshot: () => ({ omitted, records: records.map((row) => ({ ...row })) }) }); }
    finally {
      page.off("request", started);
      page.off("requestfinished", finished);
      page.off("requestfailed", failed);
      let timer: ReturnType<typeof setTimeout> | undefined;
      let drainTimedOut = false;
      try {
        await Promise.race([
          Promise.allSettled([...completions]),
          new Promise<void>((resolve) => { timer = setTimeout(() => { drainTimedOut = true; resolve(); }, 5_000); }),
        ]);
      } finally {
        if (timer) clearTimeout(timer);
        accepting = false;
      }
      if (testInfo.status !== testInfo.expectedStatus) {
        for (const entry of pending.values()) records.push({ ...entry, finishedAt: null, outcome: "pending_at_test_end" });
        await testInfo.attach("sanitized-network-evidence", {
          body: Buffer.from(JSON.stringify({ schemaVersion: 1, drainTimedOut, omitted, records })),
          contentType: "application/json",
        });
      }
    }
  }, { auto: true }],
});
