import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listTeamsMock, useCapabilityMock } = vi.hoisted(() => ({
  listTeamsMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listTeams: listTeamsMock,
  createTeam: vi.fn(),
  deleteTeam: vi.fn(),
  setTeamScoping: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import TeamsAdminPage from "@/app/app/admin/teams/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("TeamsAdminPage", () => {
  beforeEach(() => {
    listTeamsMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    listTeamsMock.mockResolvedValue({ team_scoping_enabled: false, teams: [] });
  });

  it("renders the Teams heading and the empty-state after listTeams resolves", async () => {
    render(withClient(<TeamsAdminPage />));
    expect(screen.getByRole("heading", { name: /^Teams$/ })).toBeInTheDocument();
    await waitFor(() => expect(listTeamsMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/No teams yet/i)).toBeInTheDocument();
  });
});
