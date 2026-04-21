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

import PortfolioPage from "@/app/app/portfolio/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PortfolioPage", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "X-1",
          title: "Test matter",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
    });
  });

  it("renders the Portfolio header and the Total matters KPI heading", async () => {
    render(withClient(<PortfolioPage />));
    expect(screen.getByText(/Portfolio health/i)).toBeInTheDocument();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Total matters/i)).toBeInTheDocument();
  });
});
