import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock, capabilityMock } = vi.hoisted(() => ({ fetchMock: vi.fn(), capabilityMock: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ fetchTenantDataGovernanceIntegrity: fetchMock }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => capabilityMock() }));
import DataGovernancePage from "@/app/app/admin/data-governance/page";

function withClient(children: ReactNode) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>; }

describe("DataGovernancePage", () => {
  beforeEach(() => { capabilityMock.mockReset(); fetchMock.mockReset(); capabilityMock.mockReturnValue(true); fetchMock.mockResolvedValue({ checks: [{ check_id: "expired_unpurged", status: "unavailable", summary: "No approved schedule.", findings: [], blocked_by: "DATA-GOV-02" }], ok_count: 0, finding_count: 0, unavailable_count: 1, is_complete: false }); });
  it("shows unavailable controls as unavailable, not healthy", async () => { render(withClient(<DataGovernancePage />)); expect(await screen.findByTestId("governance-check-expired_unpurged")).toHaveTextContent("unavailable"); expect(screen.getByText("Blocked by: DATA-GOV-02")).toBeInTheDocument(); expect(screen.getByText(/cannot approve, export, purge/i)).toBeInTheDocument(); });
  it("does not fetch for a non-owner", () => { capabilityMock.mockReturnValue(false); render(withClient(<DataGovernancePage />)); expect(screen.getByText(/Workspace owner required/i)).toBeInTheDocument(); expect(fetchMock).not.toHaveBeenCalled(); });
});
