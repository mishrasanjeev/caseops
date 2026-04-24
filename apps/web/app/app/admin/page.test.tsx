import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => capabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import AdminPage from "@/app/app/admin/page";

describe("AdminPage audit export (P0-001 cookie-auth regression)", () => {
  let originalFetch: typeof globalThis.fetch;
  let originalCreateObjectURL: typeof URL.createObjectURL;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL;
  const fetchMock = vi.fn();

  beforeEach(() => {
    capabilityMock.mockReset();
    capabilityMock.mockImplementation(() => true);
    fetchMock.mockReset();
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("downloads via credentials:'include' (no Authorization header)", async () => {
    // jsdom's Response cannot wrap a Blob directly — use a plain
    // string body and stub blob() to return what the page expects.
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: {
        get: (k: string) =>
          k.toLowerCase() === "content-disposition"
            ? 'attachment; filename="audit-export.jsonl"'
            : null,
      },
      blob: async () => new Blob(["row\n"], { type: "application/jsonl" }),
    });
    const user = userEvent.setup();
    render(<AdminPage />);
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe("include");
    expect(init.headers?.Authorization).toBeUndefined();
  });

  it("surfaces an actionable error on 401 instead of throwing 'session expired'", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "no" }),
    });
    const { toast } = await import("sonner");
    const user = userEvent.setup();
    render(<AdminPage />);
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/sign in again/i),
      ),
    );
  });

  it("surfaces an actionable error on 403 with the capability hint", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "denied" }),
    });
    const { toast } = await import("sonner");
    const user = userEvent.setup();
    render(<AdminPage />);
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/audit:export/i),
      ),
    );
  });
});

// QG-AUTH-004 lint-style guard: the admin page MUST NOT depend on
// getStoredToken() for the audit export path. We assert the absence at
// the source level so a future regression that re-imports it is caught
// by vitest, not by a real user.
describe("AdminPage QG-AUTH-004 — no getStoredToken dependency", () => {
  it("admin page source does not import getStoredToken", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "page.tsx"),
      "utf-8",
    );
    expect(src).not.toMatch(/getStoredToken/);
  });
});
