import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import PlatformIntegrationsPage from "@/app/app/platform-admin/integrations/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformIntegrationsPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    capabilityMock.mockReturnValue(true);
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("denies tenant admins before fetching platform integrations", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformIntegrationsPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders founder-only connector risk and cost labels", async () => {
    renderWithQuery(<PlatformIntegrationsPage />);

    expect(await screen.findByText("Pine Labs Plural")).toBeInTheDocument();
    expect(screen.getByText(/payment MDR\/fixed-fee/i)).toBeInTheDocument();
    expect(screen.getByText(/production payments disabled/i)).toBeInTheDocument();
    expect(screen.getByText(/Do not enable live payments/i)).toBeInTheDocument();
  });
});
