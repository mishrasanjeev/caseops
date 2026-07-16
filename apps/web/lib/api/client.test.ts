import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./config";
import { apiBlobRequest, apiRequest, getCsrfHeaders } from "./client";

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
    await new Promise((resolve) => setTimeout(resolve, 0));
    vi.unstubAllGlobals();
    window.localStorage.clear();
    document.cookie = "caseops_csrf=; Max-Age=0; Path=/";
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
});
