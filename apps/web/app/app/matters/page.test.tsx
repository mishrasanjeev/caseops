import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMattersMock, useRouterMock } = vi.hoisted(() => ({
  listMattersMock: vi.fn(),
  useRouterMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatters: listMattersMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: useRouterMock,
}));

import MattersPage from "@/app/app/matters/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MattersPage", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
    useRouterMock.mockReturnValue({
      push: vi.fn(),
      replace: vi.fn(),
      refresh: vi.fn(),
    });
  });

  it("renders the Matter portfolio header and a row per matter", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });
    render(withClient(<MattersPage />));
    expect(screen.getByText(/Matter portfolio/i)).toBeInTheDocument();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
    expect(await screen.findByText(/Acme v Smith/i)).toBeInTheDocument();
  });

  it("surfaces the QueryErrorState when listMatters throws", async () => {
    listMattersMock.mockRejectedValue(new Error("boom"));
    render(withClient(<MattersPage />));
    expect(
      await screen.findByText(/Could not load matters/i),
    ).toBeInTheDocument();
  });
});
