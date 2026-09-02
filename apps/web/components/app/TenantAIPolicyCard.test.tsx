import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock, getMock, updateMock, getTokenMock, updateTokenMock } = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  getMock: vi.fn(),
  updateMock: vi.fn(),
  getTokenMock: vi.fn(),
  updateTokenMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => capabilityMock(cap),
}));

vi.mock("@/lib/api/endpoints", () => ({
  getTenantAIPolicy: getMock,
  updateTenantAIPolicy: updateMock,
  getAITokenGovernance: getTokenMock,
  updateAITokenGovernance: updateTokenMock,
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
    getTokenMock.mockReset();
    updateTokenMock.mockReset();
    getTokenMock.mockResolvedValue({
      firm_quota_tokens: null,
      user_quota_tokens: null,
      warning_threshold_percent: 90,
      firm_state: "unlimited",
      firm_used_tokens: 0,
      firm_remaining_tokens: null,
      top_users: [],
      usage_by_purpose_model: [],
    });
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
      workspace_assistant_enabled: false,
      policy_version: 1,
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
      workspace_assistant_enabled: false,
      policy_version: 1,
    });
    updateMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: true,
      workspace_assistant_enabled: false,
      policy_version: 2,
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
        expected_version: 1,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Predictive \(B\)/i)).toBeInTheDocument(),
    );
  });

  it("lets an admin enable the workspace assistant with optimistic concurrency", async () => {
    capabilityMock.mockReturnValue(true);
    getMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: false,
      workspace_assistant_enabled: false,
      policy_version: 7,
    });
    updateMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: false,
      workspace_assistant_enabled: true,
      policy_version: 8,
    });
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByTestId("tenant-ai-policy-assistant-toggle"));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({
        workspace_assistant_enabled: true,
        expected_version: 7,
      }),
    );
    expect(await screen.findByText("Enabled")).toBeInTheDocument();
  });

  it("refetches the authoritative policy after a conflicting update", async () => {
    capabilityMock.mockReturnValue(true);
    getMock.mockResolvedValue({
      company_id: "c-1",
      predictive_bench_strategy_enabled: false,
      workspace_assistant_enabled: false,
      policy_version: 7,
    });
    updateMock.mockRejectedValue(new Error("Policy version conflict"));
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByTestId("tenant-ai-policy-assistant-toggle"));
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
  });
});
