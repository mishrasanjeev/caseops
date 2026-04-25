import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMattersMock } = vi.hoisted(() => ({
  listMattersMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatters: listMattersMock,
}));

import HearingsPage from "@/app/app/hearings/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("HearingsPage (portfolio aggregate)", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
  });

  it("renders the Hearings header and aggregates matters", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: "2026-05-01",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
    });
    render(withClient(<HearingsPage />));
    expect(
      screen.getByText(/Hearings across your portfolio/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
  });

  it("surfaces an error state when listMatters fails", async () => {
    listMattersMock.mockRejectedValue(new Error("network"));
    render(withClient(<HearingsPage />));
    expect(
      await screen.findByText(/Could not load hearings/i),
    ).toBeInTheDocument();
  });
});
