import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadApiFile } from "@/lib/api/endpoints";

describe("downloadApiFile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("falls back to a direct browser download when fetch is blocked", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await downloadApiFile("/api/matters/m-1/invoices/i-1/download", "invoice-i-1.pdf");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/matters/m-1/invoices/i-1/download",
      expect.objectContaining({
        credentials: "include",
        headers: { Accept: "*/*" },
      }),
    );
    expect(click).toHaveBeenCalledTimes(1);
    const link = document.querySelector("a");
    expect(link).toBeNull();
  });
});
