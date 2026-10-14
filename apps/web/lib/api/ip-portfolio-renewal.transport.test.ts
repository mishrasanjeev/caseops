import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { updateIpPortfolioRenewalDate } from "./endpoints";

const docketId = "11111111-1111-4111-8111-111111111111";
const reason = "Synthetic source date correction";

describe("Portfolio renewal corrections through the real HTTP client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.cookie = "caseops_csrf=renewal-fixture-csrf; path=/";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    document.cookie = "caseops_csrf=; max-age=0; path=/";
    vi.unstubAllGlobals();
  });

  it.each(["2029-04-30", null])("serializes correction %s exactly once, including null clearing", async renewalDueDate => {
    const response = { id: docketId, current_version: 8 };
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));

    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate, reason })).resolves.toEqual(response);

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe(`http://localhost:8000/api/ip/dockets/${docketId}/portfolio-renewal-date`);
    expect(init).toMatchObject({ method: "PATCH", credentials: "include", headers: {
      "Content-Type": "application/json", "X-CSRF-Token": "renewal-fixture-csrf",
    } });
    expect(JSON.parse(init!.body as string)).toEqual({ expected_current_version: 7,
      renewal_due_date: renewalDueDate, reason });
  });

  it.each([409, 422, 500])("preserves HTTP %s without retrying a failed correction", async status => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      type: "portfolio_correction_rejected", status, detail: "Synthetic correction rejection",
    }), { status, headers: { "Content-Type": "application/problem+json" } }));

    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate: null, reason })).rejects.toMatchObject({ status,
      problemType: "portfolio_correction_rejected", detail: "Synthetic correction rejection" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not retry a transport failure", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Synthetic network failure"));
    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate: null, reason })).rejects.toMatchObject({ name: "NetworkError" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
