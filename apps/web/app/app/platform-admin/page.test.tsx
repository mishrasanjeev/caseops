import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import PlatformAdminPage from "@/app/app/platform-admin/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformAdminPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("denies tenant admins without platform capability", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformAdminPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(screen.getByText(/tenant admin roles do not grant/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders founder-only overview, enrollments, and margin alerts", async () => {
    capabilityMock.mockReturnValue(true);
    renderWithQuery(<PlatformAdminPage />);

    expect(await screen.findByText("Monthly recurring revenue")).toBeInTheDocument();
    expect(screen.getAllByText("Acme Law").length).toBeGreaterThan(0);
    expect(screen.getByText(/stress-case margin/i)).toBeInTheDocument();
  });
});
