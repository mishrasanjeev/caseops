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

import RecommendationsHubPage from "@/app/app/recommendations/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("RecommendationsHubPage", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
  });

  it("renders the Recommendations header and a row per matter", async () => {
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
    });
    render(withClient(<RecommendationsHubPage />));
    // PageHeader renders the same word as both eyebrow and title here,
    // so anchor on the heading role specifically.
    expect(
      screen.getByRole("heading", { name: /Recommendations/i }),
    ).toBeInTheDocument();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
    expect(await screen.findByText(/Acme v Smith/i)).toBeInTheDocument();
  });

  it("surfaces an error state when listMatters fails", async () => {
    listMattersMock.mockRejectedValue(new Error("network"));
    render(withClient(<RecommendationsHubPage />));
    expect(
      await screen.findByText(/Could not load matters/i),
    ).toBeInTheDocument();
  });
});
