import { afterEach, describe, expect, it, vi } from "vitest";
import type { APIResponse } from "@playwright/test";
import { diagnosticProblem, diagnosticRequestId, diagnosticRoute, diagnosticTransport } from "../../../tests/e2e/support/prod-failure-diagnostics";
import { createPatentApplicationWithEvidence } from "../../../tests/e2e/support/prod-api-response-evidence";

describe("production failure metadata minimization", () => {
  it("categorizes authorized paths without retaining identifiers or queries", () => {
    expect(diagnosticRoute("https://api.caseops.ai/api/matters/private-client/attachments?token=secret", ["https://api.caseops.ai"]))
      .toBe("matter/attachment");
    expect(diagnosticRoute("https://caseops.ai/app/matters/private-client?email=private", ["https://caseops.ai"]))
      .toBe("web/app-navigation");
    expect(diagnosticRoute("https://accounts.google.com/sign-in?code=secret", ["https://caseops.ai"]))
      .toBeNull();
    expect(diagnosticRoute("https://api.caseops.ai/api/calendar/google/callback?code=secret", ["https://api.caseops.ai"]))
      .toBeNull();
    expect(diagnosticRoute("not a URL", ["https://caseops.ai"])).toBeNull();
    expect(diagnosticRoute("https://api.caseops.ai/api/ip/patents/applications?private=secret", ["https://api.caseops.ai"]))
      .toBe("ip/application");
    expect(diagnosticRoute("https://api.caseops.ai/api/ip/patents/applications/private-record", ["https://api.caseops.ai"]))
      .toBeNull();
  });
  it("retains only fixed problem types and validated request IDs", () => {
    const id = "5a5b40a1d7454dedb456398600bce991";
    expect(diagnosticProblem({ type: "database_lock_timeout", request_id: id, detail: "private legal content", instance: "/secret", token: "credential" }))
      .toEqual({ problemType: "database_lock_timeout", requestId: id });
    expect(diagnosticProblem({ type: "private legal content", request_id: "secret" }))
      .toEqual({ problemType: null, requestId: null });
    expect(diagnosticProblem(null)).toEqual({ problemType: null, requestId: null });
    expect(diagnosticRequestId("12345678-1234-1234-1234-123456789abc")).not.toBeNull();
    expect(diagnosticRequestId(`${id}\nprivate`)).toBeNull();
    expect(diagnosticRequestId(`${id}\n`)).toBeNull();
  });
  it("does not serialize arbitrary transport errors", () => {
    expect(diagnosticTransport("net::ERR_CONNECTION_RESET")).toBe("net::ERR_CONNECTION_RESET");
    expect(diagnosticTransport("request failed for https://private/?token=secret")).toBe("unclassified_transport_failure");
  });
});

describe("API application assertion evidence", () => {
  const id = "5a5b40a1d7454dedb456398600bce991";
  const privateValue = "PRIVATE-LEGAL-AUTH-SENTINEL";
  afterEach(() => vi.useRealTimers());

  function fixture(status: number, headers: Record<string, string> = {}, bytes = Buffer.alloc(0)) {
    const body = vi.fn(async () => bytes);
    const response = { status: () => status, headers: () => headers, body,
      text: () => { throw new Error("Raw text must not be accessed"); },
      url: () => { throw new Error("Private URL must not be accessed"); } } as unknown as APIResponse;
    const api = { post: vi.fn(async () => response) };
    const attach = vi.fn(async () => {});
    const run = () => createPatentApplicationWithEvidence(api, { attach }, "https://api.example.invalid", {
      headers: { Authorization: privateValue, "Idempotency-Key": privateValue }, data: { source: privateValue },
    });
    const snapshot = () => {
      expect(attach).toHaveBeenCalledTimes(1);
      const [name, attachment] = attach.mock.calls[0] as unknown as [string, { body: Buffer; contentType: string }];
      expect(name).toBe("sanitized-network-evidence");
      expect(attachment.contentType).toBe("application/json");
      expect(attachment.body.byteLength).toBeLessThan(1024);
      const serialized = attachment.body.toString("utf8");
      expect(serialized).not.toContain(privateValue);
      expect(serialized).not.toContain("https://");
      return JSON.parse(serialized);
    };
    return { run, snapshot, api, attach, response, body };
  }

  it("retains a 200 empty-body mismatch before the unchanged 201 assertion fails", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-10T08:56:27.000Z"));
    const f = fixture(200);
    f.api.post.mockImplementation(async () => {
      vi.setSystemTime(new Date("2026-10-10T08:56:32.000Z"));
      return f.response;
    });
    await expect(f.run()).rejects.toThrow("Patent application creation must return HTTP 201.");
    expect(f.body).not.toHaveBeenCalled();
    expect(f.snapshot()).toEqual({ schemaVersion: 1, drainTimedOut: false, omitted: 0, records: [{
      route: "ip/application", method: "POST", startedAt: "2026-10-10T08:56:27.000Z",
      finishedAt: "2026-10-10T08:56:32.000Z", outcome: "response_completed", status: 200,
      requestId: null, problemType: null,
    }] });
  });

  it("extracts only fixed 503 problem metadata and prefers a validated header request ID", async () => {
    const bytes = Buffer.from(JSON.stringify({ type: "urn:caseops:database_lock_timeout", request_id: id,
      detail: privateValue, instance: `/private?token=${privateValue}`, tenant_id: privateValue }));
    const headerId = "12345678-1234-1234-1234-123456789abc";
    const f = fixture(503, { "content-type": "application/problem+json; charset=utf-8",
      "content-length": String(bytes.length), "x-request-id": headerId }, bytes);
    await expect(f.run()).rejects.toThrow();
    expect(f.snapshot().records[0]).toMatchObject({ status: 503, requestId: headerId, problemType: "database_lock_timeout" });
    expect(f.body).toHaveBeenCalledTimes(1);
    expect(f.api.post).toHaveBeenCalledTimes(1);
  });

  it("rejects unknown problem text and invalid header IDs while allowing a validated body ID", async () => {
    const bytes = Buffer.from(JSON.stringify({ type: privateValue, request_id: id, detail: privateValue }));
    const f = fixture(503, { "content-type": "application/problem+json", "content-length": String(bytes.length),
      "x-request-id": `${id}\n${privateValue}` }, bytes);
    await expect(f.run()).rejects.toThrow();
    expect(f.snapshot().records[0]).toMatchObject({ requestId: id, problemType: null });
  });

  it.each([
    [{}, 0],
    [{ "content-type": "application/problem+json" }, 0],
    [{ "content-type": "application/json", "content-length": "2" }, 0],
    [{ "content-type": "application/problem+json-private", "content-length": "2" }, 0],
    [{ "content-type": "application/problem+json", "content-length": "16385" }, 0],
    [{ "content-type": "application/problem+json", "content-length": "-2" }, 0],
    [{ "content-type": "application/problem+json", "content-length": "2e2" }, 0],
    [{ "content-type": "application/problem+json", "content-length": "2\n" }, 0],
  ] as const)("fails closed without a bounded approved body header: %j", async (headers, reads) => {
    const f = fixture(503, headers, Buffer.from(privateValue));
    await expect(f.run()).rejects.toThrow();
    expect(f.body).toHaveBeenCalledTimes(reads);
    expect(f.snapshot().records[0]).toMatchObject({ status: 503, requestId: null, problemType: null });
  });

  it.each([Buffer.alloc(16_385, "x"), Buffer.from([0xff]), Buffer.from("not JSON"), Buffer.alloc(0)])(
    "retains status but no body metadata for oversized, invalid UTF8/JSON or empty bodies %#", async (bytes) => {
      const f = fixture(503, { "content-type": "application/problem+json", "content-length": "1" }, bytes);
      await expect(f.run()).rejects.toThrow();
      expect(f.snapshot().records[0]).toMatchObject({ status: 503, requestId: null, problemType: null });
    },
  );

  it("admits an exactly 16-KiB safe problem body without retaining its private fields", async () => {
    const bytes = Buffer.from(JSON.stringify({ type: "database_lock_timeout", request_id: id, detail: privateValue }).padEnd(16_384));
    const f = fixture(503, { "content-type": "application/problem+json", "content-length": "16384" }, bytes);
    await expect(f.run()).rejects.toThrow();
    expect(f.snapshot().records[0]).toMatchObject({ requestId: id, problemType: "database_lock_timeout" });
  });

  it("preserves status evidence when problem body access fails", async () => {
    const f = fixture(503, { "content-type": "application/problem+json", "content-length": "2" });
    f.body.mockRejectedValue(new Error(privateValue));
    await expect(f.run()).rejects.toThrow("Patent application creation must return HTTP 201.");
    expect(f.snapshot().records[0]).toMatchObject({ status: 503, requestId: null, problemType: null });
  });

  it("does not inspect or attach successful 201 bodies", async () => {
    const f = fixture(201);
    expect(await f.run()).toBe(f.response);
    expect(f.attach).not.toHaveBeenCalled();
    expect(f.body).not.toHaveBeenCalled();
  });

  it("makes exactly one original request with an authoritative no-paid marker and zero retries", async () => {
    const f = fixture(201);
    const data = { source: privateValue };
    await createPatentApplicationWithEvidence(f.api, { attach: f.attach }, "https://api.example.invalid", {
      headers: { "x-caseops-automated-test": "paid", Authorization: privateValue }, data, maxRetries: 3, failOnStatusCode: true,
    });
    expect(f.api.post).toHaveBeenCalledExactlyOnceWith("https://api.example.invalid/api/ip/patents/applications", {
      headers: { Authorization: privateValue, "X-CaseOps-Automated-Test": "no-paid-providers" }, data,
      maxRetries: 0, failOnStatusCode: false,
    });
  });

  it("does not retry or attach arbitrary transport errors", async () => {
    const f = fixture(503);
    f.api.post.mockRejectedValue(new Error(privateValue));
    await expect(f.run()).rejects.toThrow(privateValue);
    expect(f.api.post).toHaveBeenCalledTimes(1);
    expect(f.attach).not.toHaveBeenCalled();
  });

  it("does not hide an evidence attachment failure", async () => {
    const f = fixture(503);
    f.attach.mockRejectedValue(new Error("Evidence storage unavailable"));
    await expect(f.run()).rejects.toThrow("Evidence storage unavailable");
    expect(f.api.post).toHaveBeenCalledTimes(1);
  });
});
