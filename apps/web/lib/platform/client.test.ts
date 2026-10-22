import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as transport from "@/lib/api/client";

import { ConsoleError, PLATFORM_SESSION_INVALIDATED, advancePlatformSessionEpoch, consoleErrorMessage, platformApi } from "./client";

const admin = { id: "report-admin", email: "manager@example.invalid", full_name: "Report manager", role: "manager" };
const auth = { state: "authenticated", admin, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("independent platform client", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    document.cookie = "caseops_console_csrf=; Max-Age=0; Path=/";
    document.cookie = "caseops_csrf=tenant-csrf; Path=/";
  });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = "caseops_console_csrf=; Max-Age=0; Path=/"; });
  it("uses the canonical response-consumption deadline without adopting tenant authentication", async () => {
    const boundary = vi.spyOn(transport, "consumeResponseWithTimeout");
    fetcher.mockResolvedValue(response(auth));
    await platformApi.login({ email: admin.email, password: "ephemeral-input" });
    expect(boundary).toHaveBeenCalledTimes(1);
    expect(boundary).toHaveBeenCalledWith(expect.stringMatching(/\/api\/platform-console\/auth\/login$/), expect.objectContaining({
      method: "POST", credentials: "include", cache: "no-store", referrerPolicy: "no-referrer",
    }), 30_000, expect.any(Function));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("Authorization");
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("X-CSRF-Token");
  });
  it("aborts an unfinished successful response body at the unchanged 30-second deadline without replay", async () => {
    vi.useFakeTimers();
    let signal!: AbortSignal;
    let reading!: () => void;
    const started = new Promise<void>((resolve) => { reading = resolve; });
    fetcher.mockImplementation((_url, init) => {
      signal = init.signal;
      const body = new ReadableStream<Uint8Array>({ start(controller) {
        signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
      }, pull() { reading(); } }, { highWaterMark: 0 });
      return Promise.resolve(new Response(body, { status: 200 }));
    });
    const outcome = platformApi.session().catch((error: unknown) => error);
    await started;
    await vi.advanceTimersByTimeAsync(29_999);
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await outcome).toMatchObject({ name: "AbortError" });
    expect(signal.aborted).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("keeps external cancellation connected after headers while the response body is unread", async () => {
    const external = new AbortController();
    let signal!: AbortSignal;
    let reading!: () => void;
    const started = new Promise<void>((resolve) => { reading = resolve; });
    fetcher.mockImplementation((_url, init) => {
      signal = init.signal;
      const body = new ReadableStream<Uint8Array>({ start(controller) {
        signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
      }, pull() { reading(); } }, { highWaterMark: 0 });
      return Promise.resolve(new Response(body, { status: 200 }));
    });
    const outcome = platformApi.session(external.signal).catch((error: unknown) => error);
    await started;
    external.abort();
    expect(await outcome).toMatchObject({ name: "AbortError" });
    expect(signal.aborted).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("posts login only to the independent namespace without a tenant field or bearer token", async () => {
    fetcher.mockResolvedValue(response(auth));
    await platformApi.login({ email: admin.email, password: "ephemeral-input" });
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toMatch(/\/api\/platform-console\/auth\/login$/);
    expect(options).toMatchObject({ method: "POST", credentials: "include", cache: "no-store", referrerPolicy: "no-referrer" });
    expect(JSON.parse(options.body)).toEqual({ email: admin.email, password: "ephemeral-input" });
    expect(options.headers).not.toHaveProperty("Authorization");
    expect(options.headers).not.toHaveProperty("X-CSRF-Token");
  });
  it("requires its own CSRF cookie and never substitutes the tenant cookie", async () => {
    await expect(platformApi.verify({ code: "123456" })).rejects.toMatchObject({ kind: "csrf" });
    expect(fetcher).not.toHaveBeenCalled();
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    fetcher.mockResolvedValue(response(auth));
    await platformApi.verify({ code: "123456" });
    expect(fetcher.mock.calls[0][1].headers).toMatchObject({ "X-Console-CSRF-Token": "console-proof" });
  });
  it("invalidates only platform state on 401 and does not refresh or replay", async () => {
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    fetcher.mockResolvedValue(response({ detail: "sensitive-response-must-not-escape" }, 401));
    await expect(platformApi.session()).rejects.toMatchObject({ status: 401, kind: "unauthorized" });
    expect(fetcher).toHaveBeenCalledTimes(1); expect(invalidated).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).not.toContain("/api/auth/");
    window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
  });
  it("does not retry a forbidden invitation or render arbitrary server detail", async () => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    fetcher.mockResolvedValue(response({ detail: "token-or-password-payload" }, 403));
    const error = await platformApi.invite({ email: admin.email, full_name: admin.full_name }).catch((value: unknown) => value);
    expect(consoleErrorMessage(error)).not.toContain("token-or-password-payload");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects a tenant session DTO even when HTTP status is successful", async () => {
    fetcher.mockResolvedValue(response({ access_token: "unwanted", company: { id: "tenant" }, membership: { role: "owner" } }));
    await expect(platformApi.session()).rejects.toMatchObject({ kind: "contract" });
  });
  it.each(["mfa_enrollment_required", "mfa_challenge_required"])("accepts null identity before MFA: %s", async (state) => {
    fetcher.mockResolvedValue(response({ ...auth, state, admin: null }));
    expect((await platformApi.session()).state).toBe(state);
  });
  it("does not interpret malformed successful JSON as a usable session", async () => {
    fetcher.mockResolvedValue(new Response("not-json", { status: 200 }));
    await expect(platformApi.session()).rejects.toBeInstanceOf(ConsoleError);
  });
  it("encodes a bounded directory cursor without changing the route", async () => {
    fetcher.mockResolvedValue(response({ items: [], next_cursor: null }));
    await platformApi.admins("one&two=three");
    const url = new URL(fetcher.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/platform-console/admins");
    expect(url.searchParams.get("cursor")).toBe("one&two=three");
    expect(url.searchParams.get("two")).toBeNull();
  });
  const managed = { ...admin, role: "viewer", status: "pending", created_at: "2026-10-22T00:00:00Z", version: 4, removed_at: null, can_manage: true };
  it("reads versioned administrator actions from a separate strict management route", async () => {
    fetcher.mockResolvedValue(response({ items: [managed], next_cursor: null }));
    expect((await platformApi.managedAdmins("one&two=three")).items).toEqual([managed]);
    const url = new URL(fetcher.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/platform-console/admins/manage");
    expect(url.searchParams.get("cursor")).toBe("one&two=three");
    expect(url.searchParams.get("two")).toBeNull();
  });
  it.each([
    { ...managed, version: undefined }, { ...managed, version: 0 }, { ...managed, version: "4" },
    { ...managed, removed_at: undefined }, { ...managed, removed_at: "not-a-timestamp" },
    { ...managed, can_manage: undefined }, { ...managed, can_manage: "true" },
    { ...managed, unreviewed_authority: true },
  ])("refuses an unverified administrator management contract %#", async (record) => {
    fetcher.mockResolvedValue(response({ items: [record], next_cursor: null }));
    await expect(platformApi.managedAdmins()).rejects.toMatchObject({ kind: "contract" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not silently widen the legacy administrator record contract", async () => {
    fetcher.mockResolvedValue(response({ items: [managed], next_cursor: null }));
    await expect(platformApi.admins()).rejects.toMatchObject({ kind: "contract" });
  });
  it.each(["resend", "remove", "revoke"] as const)("binds %s to the observed grant version and own CSRF without retry", async (command) => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    const legacy = { ...admin, role: "viewer", status: "pending", created_at: "2026-10-22T00:00:00Z" };
    fetcher.mockResolvedValue(response(command === "resend" ? { admin: legacy, delivery_status: "accepted" } : legacy));
    if (command === "resend") await platformApi.resendAdminInvitation("viewer+id", 4);
    else if (command === "remove") await platformApi.removeAdmin("viewer+id", "Explicit report-only removal", 4);
    else await platformApi.revoke("viewer+id", "Explicit report-only revocation", 4);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, options] = fetcher.mock.calls[0];
    expect(new URL(url).pathname).toBe(`/api/platform-console/admins/viewer%2Bid/${command === "resend" ? "invitations/resend" : command}`);
    expect(options).toMatchObject({ method: "POST", credentials: "include", referrerPolicy: "no-referrer" });
    expect(options.headers).toMatchObject({ "X-Console-CSRF-Token": "console-proof" });
    expect(options.headers).not.toHaveProperty("Authorization");
    expect(options.headers).not.toHaveProperty("X-CSRF-Token");
    expect(JSON.parse(options.body)).toEqual(command === "resend" ? { expected_version: 4 }
      : { reason: command === "remove" ? "Explicit report-only removal" : "Explicit report-only revocation", expected_version: 4 });
  });
  const warning = {
    type: "case_refresh_cost_guardrail", severity: "warning", category: "case_refresh", provider: "case_tracking",
    unit_amount_minor: 37, message: "Actual tracked-case refresh cost is INR 0.10 or more. Pause public high-volume fixed-price bundles or require founder quote review.",
  };
  const overview = {
    generated_at: "2026-10-20T10:00:00Z", coverage: "recorded_rollups", rollup_count: 1,
    mrr_minor: 1200, arr_minor: 14400, active_subscriptions: 2, trial_count: 1, failed_payments: 0,
    gross_revenue_minor: 10000, recognized_revenue_minor: 10000, total_variable_cost_minor: 13000,
    gross_profit_minor: -3000, gross_margin_bps: -3000,
    margin_alerts: [{ company_id: "company", gross_margin_bps: -3000, gross_profit_minor: -3000 }, warning],
    margin_alerts_has_more: false,
  };
  it.each([
    { kind: "usage" as const, coverage: "recorded_usage", row: { company_id: "account", company_name: "Named legal office", feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 } },
    { kind: "revenue" as const, coverage: "recorded_payments", row: { company_id: "account", company_name: "Named legal office", paid_at: "2026-10-20T00:00:00Z", merchant_reference: "payment", amount_paid_minor: 123456, tax_amount_minor: 37 } },
  ])("opts into one strict named $kind response without a second account lookup", async ({ kind, coverage, row }) => {
    fetcher.mockResolvedValue(response({ items: [row], generated_at: "2026-10-22T00:00:00Z", next_cursor: null, has_more: false, coverage }));
    expect((await platformApi.namedReport(kind, "one&two=three")).items).toEqual([row]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const url = new URL(fetcher.mock.calls[0][0]);
    expect(url.pathname).toBe(`/api/platform-console/reports/${kind}`);
    expect(url.searchParams.get("include_account_names")).toBe("true");
    expect(url.searchParams.get("cursor")).toBe("one&two=three");
    expect(url.searchParams.get("two")).toBeNull();
  });
  it("refuses an unnamed usage row when the named response was requested", async () => {
    fetcher.mockResolvedValue(response({ items: [{ company_id: "account", feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 }],
      generated_at: "2026-10-22T00:00:00Z", next_cursor: null, has_more: false, coverage: "recorded_usage" }));
    await expect(platformApi.namedReport("usage")).rejects.toMatchObject({ kind: "contract" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("accepts explicit absent name evidence without fabricating a label", async () => {
    const row = { company_id: "account", company_name: null, feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 };
    fetcher.mockResolvedValue(response({ items: [row], generated_at: "2026-10-22T00:00:00Z", next_cursor: null, has_more: false, coverage: "recorded_usage" }));
    expect((await platformApi.namedReport("usage")).items).toEqual([row]);
  });
  it("opts into named account alerts while retaining the provider warning variant", async () => {
    const named = { ...overview, margin_alerts: [{ company_id: "account", company_name: "Named legal office", gross_margin_bps: -3000, gross_profit_minor: -3000 }, warning] };
    fetcher.mockResolvedValue(response(named));
    expect(await platformApi.namedOverview()).toEqual(named);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.get("include_account_names")).toBe("true");
  });
  it("accepts complete margin and cost-warning variants through the actual overview response validator", async () => {
    fetcher.mockResolvedValue(response(overview));
    expect(await platformApi.overview()).toEqual(overview);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toMatch(/\/api\/platform-console\/reports\/overview$/);
  });
  it.each([
    { ...warning, type: "unknown_cost_warning" },
    { ...warning, severity: "info" },
    { ...warning, extra: "not-reviewed" },
  ])("rejects an unknown overview warning without retrying or returning partial financial data %#", async (alert) => {
    fetcher.mockResolvedValue(response({ ...overview, margin_alerts: [alert] }));
    await expect(platformApi.overview()).rejects.toMatchObject({ kind: "contract" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("passes cancellation through its own request without mutation replay", async () => {
    const abort = new AbortController(); abort.abort();
    fetcher.mockImplementation((_url, init) => init.signal.aborted ? Promise.reject(new DOMException("Aborted", "AbortError")) : Promise.resolve(response(auth)));
    await expect(platformApi.session(abort.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not invalidate a newer login when an older request returns 401 late", async () => {
    let finish!: (response: Response) => void;
    fetcher.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    const pending = platformApi.session();
    advancePlatformSessionEpoch();
    finish(response({}, 401));
    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(invalidated).not.toHaveBeenCalled();
    window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
  });
  it("resends setup only through the exact preauth command with a generic response", async () => {
    fetcher.mockResolvedValue(response({ status: "accepted" }));
    expect(await platformApi.resendInvitation("viewer@example.invalid")).toEqual({ status: "accepted" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toMatch(/\/auth\/invitations\/resend$/);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ email: "viewer@example.invalid" });
  });
  it.each(["invitation", "reset"])("fences a late cancelled %s response even if transport ignores abort", async (kind) => {
    let finish!: (response: Response) => void;
    fetcher.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    const abort = new AbortController();
    const pending = kind === "invitation"
      ? platformApi.acceptInvitation({ token: "test-only", password: "form-input", full_name: "Recipient" }, abort.signal)
      : platformApi.completeReset({ token: "test-only", password: "form-input" }, abort.signal);
    abort.abort();
    finish(kind === "invitation" ? response({}, 401) : response({ status: "complete" }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(invalidated).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
  });
  const mfaProblem = {
    type: "console_mfa_invalid", code: "console_mfa_invalid", status: 401, title: "Unauthorized",
    detail: "private-factor-detail", instance: "/api/platform-console/auth/mfa/verify",
  };
  it("distinguishes the exact typed MFA refusal without invalidating the limited session or reflecting detail", async () => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    try {
      fetcher.mockResolvedValue(new Response(JSON.stringify(mfaProblem), { status: 401, headers: { "Content-Type": "application/problem+json; charset=utf-8" } }));
      const error = await platformApi.verify({ recovery_code: "USED-RECOVERY-CODE" }).catch((value: unknown) => value);
      expect(error).toMatchObject({ status: 401, kind: "mfa_invalid" });
      expect(consoleErrorMessage(error)).toContain("The MFA code is invalid or was already used.");
      expect(consoleErrorMessage(error)).not.toContain("private-factor-detail");
      expect(invalidated).not.toHaveBeenCalled();
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated); }
  });
  it.each([
    { body: { ...mfaProblem, type: "console_session_invalid" }, contentType: "application/problem+json" },
    { body: { ...mfaProblem, code: "console_session_invalid" }, contentType: "application/problem+json" },
    { body: { ...mfaProblem, status: 403 }, contentType: "application/problem+json" },
    { body: { ...mfaProblem, instance: "/api/platform-console/auth/session" }, contentType: "application/problem+json" },
    { body: { detail: "console_mfa_invalid" }, contentType: "application/problem+json" },
    { body: [mfaProblem], contentType: "application/problem+json" },
    { body: mfaProblem, contentType: "application/json" },
  ])("never suppresses a genuine or unverified 401 envelope %#", async ({ body, contentType }) => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    try {
      fetcher.mockResolvedValue(new Response(JSON.stringify(body), { status: 401, headers: { "Content-Type": contentType } }));
      await expect(platformApi.verify({ code: "123456" })).rejects.toMatchObject({ kind: "unauthorized" });
      expect(invalidated).toHaveBeenCalledTimes(1);
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated); }
  });
  it("does not accept an MFA refusal as a live session response on a different endpoint", async () => {
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    try {
      fetcher.mockResolvedValue(new Response(JSON.stringify(mfaProblem), { status: 401, headers: { "Content-Type": "application/problem+json" } }));
      await expect(platformApi.session()).rejects.toMatchObject({ kind: "unauthorized" });
      expect(invalidated).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated); }
  });
  it("bounds MFA error-body reads and cancels an oversized body before rejecting the session", async () => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(4097)); }, cancel: cancelled });
    fetcher.mockResolvedValue(new Response(body, { status: 401, headers: { "Content-Type": "application/problem+json" } }));
    try {
      await expect(platformApi.verify({ code: "123456" })).rejects.toMatchObject({ kind: "unauthorized" });
      expect(cancelled).toHaveBeenCalledTimes(1);
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally { await body.cancel(); }
  });
  it("treats malformed problem JSON as an unauthorized response, never as a retryable factor error", async () => {
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    fetcher.mockResolvedValue(new Response("not-json", { status: 401, headers: { "Content-Type": "application/problem+json" } }));
    await expect(platformApi.verify({ code: "123456" })).rejects.toMatchObject({ kind: "unauthorized" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not apply an MFA error after its existing request deadline expires during the problem read", async () => {
    vi.useFakeTimers();
    document.cookie = "caseops_console_csrf=console-proof; Path=/";
    const invalidated = vi.fn(); window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    let finish!: () => void;
    let reading!: () => void;
    const started = new Promise<void>((resolve) => { reading = resolve; });
    const body = new ReadableStream<Uint8Array>({ pull(controller) {
      finish = () => { controller.enqueue(new TextEncoder().encode(JSON.stringify(mfaProblem))); controller.close(); };
      reading();
    } }, { highWaterMark: 0 });
    try {
      fetcher.mockResolvedValue(new Response(body, { status: 401, headers: { "Content-Type": "application/problem+json" } }));
      const pending = platformApi.verify({ code: "123456" });
      await started;
      await vi.advanceTimersByTimeAsync(30_000);
      finish();
      await expect(pending).rejects.toMatchObject({ name: "AbortError" });
      expect(invalidated).not.toHaveBeenCalled();
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
      window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
      await body.cancel();
    }
  });
});
