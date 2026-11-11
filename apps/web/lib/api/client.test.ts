import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./config";
import {
  apiBlobRequest,
  apiBlobDataRequest,
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

describe("apiBlobDataRequest", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(async () => {
    vi.useRealTimers();
    await new Promise((resolve) => setTimeout(resolve, 0));
    vi.unstubAllGlobals();
  });

  it("consumes a private authenticated body and retains headers without browser caching", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("%PDF-source", { headers: { "content-type": "application/pdf" } }));
    const result = await apiBlobDataRequest("/api/private/source", { headers: { Accept: "application/pdf" } });
    expect(await result.blob.text()).toBe("%PDF-source");
    expect(result.headers.get("content-type")).toBe("application/pdf");
    expect(result.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith("http://localhost:8000/api/private/source", expect.objectContaining({
      credentials: "include", cache: "no-store", headers: expect.objectContaining({ Accept: "application/pdf" }),
    }));
  });

  it("times out and cancels a stalled body after headers arrived", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ cancel });
    vi.mocked(fetch).mockResolvedValue(new Response(stream));
    const operation = apiBlobDataRequest("/api/private/stalled", { timeoutMs: 2_000 });
    const assertion = expect(operation).rejects.toMatchObject({ name: "NetworkError", message: expect.stringContaining("2 seconds") });
    await vi.advanceTimersByTimeAsync(2_000);
    await assertion;
    expect(cancel).toHaveBeenCalled();
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("preserves unmount cancellation throughout body consumption", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    let begin!: () => void;
    const started = new Promise<void>((resolve) => { begin = resolve; });
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream<Uint8Array>({ pull: begin, cancel })));
    const operation = apiBlobDataRequest("/api/private/cancelled", { signal: controller.signal });
    await started;
    controller.abort(new DOMException("Viewer unmounted", "AbortError"));
    await expect(operation).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([403, 404, 422])("never refreshes or retries a typed %i denial", async (status) => {
    window.localStorage.setItem("caseops.session.context", "{}");
    vi.mocked(fetch).mockResolvedValue(response({ type: "source_denied", detail: "Source is unavailable" }, status, "application/problem+json"));
    await expect(apiBlobDataRequest("/api/private/denied")).rejects.toMatchObject({ status, detail: "Source is unavailable" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([true, false])("enforces the byte cap with declared length %s", async (declared) => {
    vi.mocked(fetch).mockResolvedValue(new Response("too many source bytes", { headers: declared ? { "content-length": "21" } : {} }));
    await expect(apiBlobDataRequest("/api/private/oversized", { maxBytes: 4 })).rejects.toMatchObject({ name: "NetworkError", message: expect.stringContaining("allowed size") });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("keeps one total deadline while the shared authentication refresh is pending", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem("caseops.session.context", "{}");
    let finishRefresh!: (response: Response) => void;
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ type: "invalid_token", detail: "Expired" }, 401, "application/problem+json"))
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    const operation = apiBlobDataRequest("/api/private/refresh", { timeoutMs: 1_000 });
    const assertion = expect(operation).rejects.toMatchObject({ name: "NetworkError" });
    await vi.advanceTimersByTimeAsync(1_000);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(2);
    finishRefresh(response({ access_token: "refreshed", token_type: "bearer", company: {}, user: {}, membership: {} }, 200));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])("retains original cookie-signin intent after refresh, explicit token %s", async (explicit) => {
    const localStorage = window.localStorage;
    localStorage.setItem("caseops.session.context", "{}");
    const assign = vi.fn();
    vi.stubGlobal("window", { localStorage, dispatchEvent: vi.fn(), location: {
      origin: "http://localhost:3000", pathname: "/app/contracts/source", search: "", assign,
    } });
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ type: "invalid_token", detail: "Expired" }, 401))
      .mockResolvedValueOnce(response({ access_token: "refreshed", token_type: "bearer", company: {}, user: {}, membership: {} }, 200))
      .mockResolvedValueOnce(response({ type: "invalid_token", detail: "Still invalid" }, 401));
    await expect(apiBlobDataRequest("/api/private/source", explicit ? { token: "explicit" } : {}))
      .rejects.toMatchObject({ status: 401 });
    expect(fetch).toHaveBeenCalledTimes(3);
    if (explicit) expect(assign).not.toHaveBeenCalled();
    else expect(assign).toHaveBeenCalledWith("/sign-in?next=%2Fapp%2Fcontracts%2Fsource");
  });
});
