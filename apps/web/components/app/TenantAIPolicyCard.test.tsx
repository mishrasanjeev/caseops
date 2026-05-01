import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock, getMock, updateMock } = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  getMock: vi.fn(),
  updateMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => capabilityMock(cap),
}));

vi.mock("@/lib/api/endpoints", () => ({
  getTenantAIPolicy: getMock,
  updateTenantAIPolicy: updateMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { TenantAIPolicyCard } from "@/components/app/TenantAIPolicyCard";

function renderCard(): ReturnType<typeof render> {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TenantAIPolicyCard />
    </QueryClientProvider>,
  );
}

describe("TenantAIPolicyCard (PG-107 v1.5)", () => {
  beforeEach(() => {
    capabilityMock.mockReset();
    getMock.mockReset();
    updateMock.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("hides itself when caller does not have workspace:admin", () => {
    capabilityMock.mockReturnValue(false);
    renderCard();
    expect(screen.queryByTestId("tenant-ai-policy-card")).toBeNull();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("renders Evidence-only status by default and Enable button", async () => {
    capabilityMock.mockReturnValue(true);
    getMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: false,
    });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-ai-policy-card")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Evidence-only \(A, default\)/i)).toBeInTheDocument();
    expect(
      screen.getByTestId("tenant-ai-policy-predictive-toggle"),
    ).toHaveTextContent(/Enable/i);
  });

  it("flips to Predictive on click and calls update endpoint", async () => {
    capabilityMock.mockReturnValue(true);
    getMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: false,
    });
    updateMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: true,
    });
    const user = userEvent.setup();
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-ai-policy-card")).toBeInTheDocument(),
    );
    await user.click(
      screen.getByTestId("tenant-ai-policy-predictive-toggle"),
    );
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({
        predictive_bench_strategy_enabled: true,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Predictive \(B\)/i)).toBeInTheDocument(),
    );
  });
});
