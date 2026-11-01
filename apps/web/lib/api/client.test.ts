import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./config";
import {
  apiBlobRequest,
  apiRequest,
  fetchJsonWithTimeout,
  fetchWithTimeout,
  getCsrfHeaders,
} from "./client";

function response(
  body: unknown,
  status: number,
  contentType = "application/json",
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": contentType },
  });
}

describe("apiRequest", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.cookie = "caseops_csrf=; Max-Age=0; Path=/";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(async () => {
    vi.useRealTimers();
    await new Promise((resolve) => setTimeout(resolve, 0));
    vi.unstubAllGlobals();
    window.localStorage.clear();
    document.cookie = "caseops_csrf=; Max-Age=0; Path=/";
  });

  it("serializes JSON-looking strings as literal values without interpreting them", async () => {
    const literal = '{"source":"literal text"}';
    vi.mocked(fetch).mockResolvedValue(response({ ok: true }, 200));
    await expect(apiRequest("/api/fixture-literal", { method: "POST", body: literal }))
      .resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(1);
    const init = vi.mocked(fetch).mock.calls[0][1]!;
    expect(JSON.parse(init.body as string)).toBe(literal);
  });

  it("preserves RFC 7807 detail and type from application/problem+json", async () => {
    const problem = {
      type: "validation_error",
      title: "Validation failed",
      status: 422,
      detail: "The filing date must be in the past.",
    };
    vi.mocked(fetch).mockResolvedValue(
      response(problem, 422, "application/problem+json"),
    );

    await expect(apiRequest("/api/filings", { method: "POST" })).rejects.toMatchObject({
      status: 422,
      detail: problem.detail,
      problemType: problem.type,
      data: problem,
    } satisfies Partial<ApiError>);
  });

  it("names the failing field in a validation problem whatever the API detail says", async () => {
    // An older API joined only the messages; the toast then named no field.
    vi.mocked(fetch).mockResolvedValue(response({
      type: "https://httpstatuses.com/422",
      title: "Unprocessable content",
      status: 422,
      detail: "List should have at least 1 item after validation, not 0; Input should be a valid list",
      errors: [
        {
          loc: ["body", "publications", 0, "class_numbers"],
          msg: "List should have at least 1 item after validation, not 0",
          type: "too_short",
        },
        {
          loc: ["body", "publications", 0, "goods_services", "45"],
          msg: "Input should be a valid list",
          type: "list_type",
        },
      ],
    }, 422, "application/problem+json"));

    await expect(apiRequest("/api/ip/watch/journal-ingestions", { method: "POST" })).rejects.toMatchObject({
      status: 422,
      detail: "Publications \u203a Class numbers: List should have at least 1 item after validation, not 0; "
        + "Publications \u203a Goods services \u203a 45: Input should be a valid list",
    });
  });

  it("words a bare FastAPI validation list with its fields", async () => {
    vi.mocked(fetch).mockResolvedValue(response({
      detail: [{ loc: ["body", "source_url"], msg: "Value error, Use an https URL.", type: "value_error" }],
    }, 422));

    await expect(apiRequest("/api/x", { method: "POST" })).rejects.toMatchObject({
      detail: "Source URL: Use an https URL.",
    });
  });

  it("renders a structured conflict instead of its bare status title", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({
      type: "https://httpstatuses.com/409",
      title: "Conflict",
      status: 409,
      detail: "Conflict",
      code: "ip_opposition_opponent_not_ready",
      gaps: ["forum_required", "grounds_required"],
    }, 409, "application/problem+json"));
    await expect(apiRequest("/api/ip/opposition", { method: "POST" })).rejects.toMatchObject({
      status: 409,
      detail: "IP opposition opponent not ready. Missing: forum; grounds.",
    });

    // The same refusal from a handler outside the problem envelope.
    vi.mocked(fetch).mockResolvedValueOnce(response({
      detail: { code: "ip_document_locked", document_id: "doc-1" },
    }, 409));
    await expect(apiRequest("/api/ip/documents/doc-1", { method: "PATCH" })).rejects.toMatchObject({
      detail: "IP document locked.",
    });

    vi.mocked(fetch).mockResolvedValueOnce(response({
      detail: { message: "Reload this workspace.", code: "ip_document_state_conflict" },
    }, 409));
    await expect(apiRequest("/api/ip/documents/doc-1", { method: "PATCH" })).rejects.toMatchObject({
      detail: "Reload this workspace.",
    });
  });

  it("refreshes and retries after a problem+json invalid-token response", async () => {
    window.localStorage.setItem("caseops.session.context", "{}");
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response(
          {
            type: "invalid_token",
            status: 401,
            detail: "Session token expired.",
          },
          401,
          "application/problem+json",
        ),
      )
      .mockResolvedValueOnce(
        response(
          {
            access_token: "fresh-token",
            token_type: "bearer",
            company: {},
            user: {},
            membership: {},
          },
          200,
        ),
      )
      .mockResolvedValueOnce(response({ ok: true }, 200));

    await expect(
      apiRequest<{ ok: boolean }>("/api/secure", { token: "stale-token" }),
    ).resolves.toEqual({ ok: true });

    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetch).mock.calls[1]?.[0]).toBe(
      "http://localhost:8000/api/auth/refresh",
    );
    expect(vi.mocked(fetch).mock.calls[2]?.[1]).toMatchObject({
      credentials: "include",
      headers: expect.objectContaining({
        Authorization: "Bearer fresh-token",
      }),
    });
  });

  it("refreshes and retries an authenticated binary download after a 401", async () => {
    window.localStorage.setItem("caseops.session.context", "{}");
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response(
          {
            type: "expired_token",
            status: 401,
            detail: "Session token expired.",
          },
          401,
          "application/problem+json",
        ),
      )
      .mockResolvedValueOnce(
        response(
          {
            access_token: "fresh-download-token",
            token_type: "bearer",
            company: {},
            user: {},
            membership: {},
          },
          200,
        ),
      )
      .mockResolvedValueOnce(
        new Response("notice bytes", {
          status: 200,
          headers: {
            "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="notice.txt"',
          },
        }),
      );

    const result = await apiBlobRequest("/api/notices/notice-1/download", {
      token: "stale-download-token",
    });

    await expect(result.text()).resolves.toBe("notice bytes");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetch).mock.calls[1]?.[0]).toBe(
      "http://localhost:8000/api/auth/refresh",
    );
    expect(vi.mocked(fetch).mock.calls[2]?.[1]).toMatchObject({
      credentials: "include",
      headers: expect.objectContaining({
        Accept: "*/*",
        Authorization: "Bearer fresh-download-token",
      }),
    });
  });

  it("keeps portal 401s inside the portal auth boundary", async () => {
    const localStorage = window.localStorage;
    localStorage.setItem("caseops.session.context", "{}");
    const assign = vi.fn();
    vi.stubGlobal("window", {
      dispatchEvent: vi.fn(),
      localStorage,
      location: {
        assign,
        pathname: "/portal/matters",
        search: "?tab=open",
      },
    });
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response(
          {
            type: "invalid_token",
            status: 401,
            detail: "Portal session expired.",
          },
          401,
          "application/problem+json",
        ),
      )
      .mockResolvedValueOnce(
        response(
          {
            access_token: "employee-token",
            token_type: "bearer",
            company: {},
            user: {},
            membership: {},
          },
          200,
        ),
      )
      .mockResolvedValueOnce(
        response(
          {
            type: "invalid_token",
            status: 401,
            detail: "Portal session expired.",
          },
          401,
          "application/problem+json",
        ),
      );

    await expect(apiRequest("/api/portal/me")).rejects.toMatchObject({
      status: 401,
      detail: "Portal session expired.",
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(
      vi.mocked(fetch).mock.calls.some(([url]) =>
        String(url).endsWith("/api/auth/refresh"),
      ),
    ).toBe(false);
    expect(assign).toHaveBeenCalledWith("/portal/sign-in");
    expect(assign).not.toHaveBeenCalledWith(
      expect.stringContaining("/sign-in?next="),
    );
  });

  it("sends cookie credentials and the CSRF token on logout", async () => {
    document.cookie = "caseops_csrf=logout-token; Path=/";
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await apiRequest<void>("/api/auth/logout", { method: "POST" });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({
          Accept: "application/json",
          "X-CSRF-Token": "logout-token",
        }),
      }),
    );
  });

  it("exposes the cookie CSRF header for direct fetch call sites", () => {
    expect(getCsrfHeaders()).toEqual({});

    document.cookie = "caseops_csrf=reusable-token; Path=/";

    expect(getCsrfHeaders()).toEqual({
      "X-CSRF-Token": "reusable-token",
    });
  });

  it("aborts API work at the configured deadline with an actionable error", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation((_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      }),
    );

    const result = apiRequest("/api/slow", { timeoutMs: 2_000 });
    const assertion = expect(result).rejects.toMatchObject({
      name: "NetworkError",
      message: expect.stringContaining("2 seconds"),
    });
    await vi.advanceTimersByTimeAsync(2_000);
    await assertion;
  });

  it("preserves caller cancellation instead of reporting it as a timeout", async () => {
    const caller = new AbortController();
    vi.mocked(fetch).mockImplementation((_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      }),
    );

    const result = fetchWithTimeout("/api/cancelled", { signal: caller.signal }, 5_000);
    caller.abort(new DOMException("Cancelled by caller.", "AbortError"));

    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });

  it("keeps the JSON body under the original deadline after headers arrive", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(async (_input, init) => ({
      ok: true, status: 200,
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      }),
    } as Response));
    const result = fetchJsonWithTimeout("/api/stalled-body", {}, 2_000);
    const assertion = expect(result).rejects.toMatchObject({ name: "NetworkError" });
    await vi.advanceTimersByTimeAsync(2_000);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("forwards caller cancellation while consuming JSON without a false timeout", async () => {
    const caller = new AbortController();
    let bodyStarted!: () => void;
    const consuming = new Promise<void>((resolve) => { bodyStarted = resolve; });
    vi.mocked(fetch).mockImplementation(async (_input, init) => ({
      ok: true, status: 200,
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        bodyStarted();
      }),
    } as Response));
    const result = fetchJsonWithTimeout("/api/cancelled-body", { signal: caller.signal }, 5_000);
    await consuming;
    caller.abort(new DOMException("Caller left the page.", "AbortError"));
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });

  it("retains HTTP status and parses JSON without changing request credentials", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ reason: "unavailable" }, 503));
    await expect(fetchJsonWithTimeout("/api/public", { credentials: "omit" }, 5_000))
      .resolves.toEqual({ ok: false, status: 503, data: { reason: "unavailable" } });
    expect(fetch).toHaveBeenCalledWith("/api/public", expect.objectContaining({ credentials: "omit" }));
  });
});
