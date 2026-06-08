import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import TenantIntegrationsPage from "@/app/app/admin/integrations/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("TenantIntegrationsPage", () => {
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

  it("blocks non-admin callers before fetching integrations", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<TenantIntegrationsPage />);

    expect(screen.getByText("Workspace admin required")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders tenant-safe connector readiness without internal labels", async () => {
    renderWithQuery(<TenantIntegrationsPage />);

    expect(await screen.findByTestId("google-workspace-setup")).toBeInTheDocument();
    expect(screen.getByText("Google Workspace")).toBeInTheDocument();
    expect(screen.getByTestId("google-workspace-google_calendar")).toHaveTextContent(
      "Calendar",
    );
    expect(screen.getByTestId("google-workspace-gmail")).toHaveTextContent("Gmail");
    expect(screen.getByTestId("google-workspace-google_drive")).toHaveTextContent(
      "Drive",
    );
    fireEvent.click(screen.getByTestId("google-drive-list-files"));
    expect(await screen.findByText("Signed vakalatnama.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Pine Labs Plural")).toBeInTheDocument();
    expect(screen.getByText("SendGrid")).toBeInTheDocument();
    expect(screen.queryByText(/gross profit/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/gross margin/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal cost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/payment MDR/i)).not.toBeInTheDocument();
  });
});
