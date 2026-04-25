import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listStatutesMock } = vi.hoisted(() => ({
  listStatutesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listStatutes: listStatutesMock,
}));

import StatutesIndexPage from "@/app/app/statutes/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("StatutesIndexPage", () => {
  beforeEach(() => {
    listStatutesMock.mockReset();
  });

  it("renders an Act tile for each seeded statute", async () => {
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "bnss-2023",
          short_name: "BNSS",
          long_name: "Bharatiya Nagarik Suraksha Sanhita, 2023",
          enacted_year: 2023,
          jurisdiction: "india",
          source_url: "https://www.indiacode.nic.in/handle/123456789/20062",
          section_count: 17,
        },
      ],
      total_section_count: 17,
    });
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByTestId("statute-tile-bnss-2023"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Bharatiya Nagarik Suraksha Sanhita/i),
    ).toBeInTheDocument();
    // "17 sections" appears in both the page header description
    // (total_section_count) and the per-tile section_count badge.
    // Anchor on the link inside the BNSS tile to disambiguate.
    const browseLinks = screen.getAllByRole("link", {
      name: /Browse sections/i,
    });
    expect(browseLinks[0]).toHaveAttribute("href", "/app/statutes/bnss-2023");
  });

  it("shows the empty state when no acts seeded", async () => {
    listStatutesMock.mockResolvedValue({ statutes: [], total_section_count: 0 });
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByText(/No statutes seeded yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    listStatutesMock.mockRejectedValue(new Error("network"));
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByText(/Could not load statutes/i),
    ).toBeInTheDocument();
  });
});
