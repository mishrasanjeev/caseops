import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import PlatformProviderEventsPage from "@/app/app/platform-admin/provider-events/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformProviderEventsPage", () => {
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

  it("searches provider events and records reprocess requests", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PlatformProviderEventsPage />);

    expect(await screen.findByText("ORDER_PROCESSED")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search"), "order-1");
    await user.click(screen.getByRole("button", { name: /^Search$/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/platform-admin/provider-events?q=order-1"),
        ),
      ).toBe(true),
    );

    await user.click(screen.getByRole("button", { name: /reprocess/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/platform-admin/provider-events/evt-1/reprocess"),
        ),
      ).toBe(true),
    );
  });

  it("denies non-founder users before loading provider events", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformProviderEventsPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
  });
});
