import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadApiFile, downloadCauseListPdf } from "@/lib/api/endpoints";

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

  it("sends the double-submit CSRF token for cause-list PDF generation", async () => {
    document.cookie = "caseops_csrf=cause-list-csrf";
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:cause-list");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => new Blob(["%PDF-1.7"]),
      headers: new Headers({
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="cause-list.pdf"',
      }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await downloadCauseListPdf({ date: "2026-07-10" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/cause-lists/download",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-CSRF-Token": "cause-list-csrf",
        }),
      }),
    );
    expect(click).toHaveBeenCalledTimes(1);
  });
});
