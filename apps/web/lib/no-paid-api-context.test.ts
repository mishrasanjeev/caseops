import { createServer, type IncomingHttpHeaders } from "node:http";

import { request, type APIRequestContext } from "@playwright/test";
import { expect, test } from "vitest";

import { createNoPaidApiContext } from "../../../tests/e2e/support/cost-controls";

type Received = { method: string; path: string; headers: IncomingHttpHeaders; body: string };

async function withReceiver(
  run: (origin: string, received: Received[], contexts: APIRequestContext[]) => Promise<void>,
) {
  const received: Received[] = [];
  const contexts: APIRequestContext[] = [];
  const failures: unknown[] = [];
  const server = createServer(async (request, response) => {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(Buffer.from(chunk));
    received.push({ method: request.method!, path: request.url!, headers: request.headers,
      body: Buffer.concat(chunks).toString("utf8") });
    response.setHeader("Content-Type", "application/json");
    const firstTransientRead = request.url === "/transient"
      && received.filter(row => row.path === "/transient").length === 1;
    response.writeHead(firstTransientRead ? 500 : 200);
    response.end('{"received":true}');
  });
  try {
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Owned loopback receiver did not listen");
    await run(`http://127.0.0.1:${address.port}`, received, contexts);
  } catch (error) { failures.push(error); }
  finally {
    const disposed = await Promise.allSettled(contexts.map(context => context.dispose()));
    for (const result of disposed) if (result.status === "rejected") failures.push(result.reason);
    if (server.listening) {
      try { await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
      catch (error) { failures.push(error); }
    }
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) throw new AggregateError(failures, "API context assertion and independent cleanup failures");
}

test("standalone API contexts send the real marker and retain payload and explicit authority headers", async () => {
  await withReceiver(async (origin, received, contexts) => {
    // The original constructor is exercised only against this owned offline
    // receiver, retaining the missing-marker baseline alongside the repair.
    const original = await request.newContext(); contexts.push(original);
    const baseline = await original.get(`${origin}/unmarked-control`, { maxRetries: 0, timeout: 1000 });
    expect(baseline.status()).toBe(200);
    expect(received).toHaveLength(1);
    expect(received[0].headers["x-caseops-automated-test"]).toBeUndefined();
    const first = await createNoPaidApiContext(origin); contexts.push(first);
    const admitted = await first.post(`${origin}/admit`, { data: { note: "owned offline probe" },
      headers: { Authorization: "Bearer owned-fixture-token", Cookie: "owned_probe=only-this-request" },
      maxRetries: 0, timeout: 1000 });
    expect(admitted.status()).toBe(200);
    const read = await first.get(`${origin}/read`, { maxRetries: 0, timeout: 1000 });
    expect(read.status()).toBe(200);
    const second = await createNoPaidApiContext(origin); contexts.push(second);
    const independent = await second.get(`${origin}/independent`, { maxRetries: 0, timeout: 1000 });
    expect(independent.status()).toBe(200);
    expect(second).not.toBe(first);
    expect(received.map(row => [row.method, row.path])).toEqual([
      ["GET", "/unmarked-control"], ["POST", "/admit"], ["GET", "/read"], ["GET", "/independent"],
    ]);
    expect(JSON.parse(received[1].body)).toEqual({ note: "owned offline probe" });
    expect(received[1].headers.authorization).toBe("Bearer owned-fixture-token");
    expect(received[1].headers.cookie).toBe("owned_probe=only-this-request");
    expect(received[2].headers.cookie).toBeUndefined();
    expect(received[2].headers.authorization).toBeUndefined();
    expect(received[3].headers.cookie).toBeUndefined();
    for (const row of received.slice(1)) {
      expect(row.headers["x-caseops-automated-test"]).toBe("no-paid-providers");
      expect(row.headers.connection).toBe("close");
    }
  });
});

test("a failed read and its explicit retry retain the marker without an automatic retry", async () => {
  await withReceiver(async (origin, received, contexts) => {
    const context = await createNoPaidApiContext(origin); contexts.push(context);
    const failed = await context.get(`${origin}/transient`, { maxRetries: 0, timeout: 1000 });
    expect(failed.status()).toBe(500);
    expect(received).toHaveLength(1);
    const rechecked = await context.get(`${origin}/transient`, { maxRetries: 0, timeout: 1000 });
    expect(rechecked.status()).toBe(200);
    expect(received.map(row => row.path)).toEqual(["/transient", "/transient"]);
    for (const row of received) {
      expect(row.headers["x-caseops-automated-test"]).toBe("no-paid-providers");
      expect(row.headers.connection).toBe("close");
    }
  });
});
