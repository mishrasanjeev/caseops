import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchCourtProfileMock } = vi.hoisted(() => ({
  fetchCourtProfileMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchCourtProfile: fetchCourtProfileMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "court-1" }),
}));

import CourtProfilePage from "@/app/app/courts/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PROFILE_FIXTURE = {
  court: {
    id: "court-1",
    name: "Delhi High Court",
    short_name: "DHC",
    forum_level: "high_court",
    jurisdiction: "Delhi",
    seat_city: "New Delhi",
  },
  judges: [
    { id: "j-1", name: "Hon'ble Justice A", role: "sitting" },
    { id: "j-2", name: "Hon'ble Justice B", role: "sitting" },
  ],
  portfolio_matter_count: 7,
  authority_document_count: 412,
  recent_authorities: [],
  benches: [],
};

describe("CourtProfilePage", () => {
  beforeEach(() => {
    fetchCourtProfileMock.mockReset();
  });

  it("renders skeleton while profile is loading", () => {
    fetchCourtProfileMock.mockImplementation(() => new Promise(() => {}));
    const { container } = render(withClient(<CourtProfilePage />));
    // Skeletons render as div with the .h-10/.h-64 utility classes,
    // visible immediately even with no data.
    expect(container.firstChild).not.toBeNull();
  });

  it("renders court header + KPI tiles when profile lands", async () => {
    fetchCourtProfileMock.mockResolvedValue(PROFILE_FIXTURE);
    render(withClient(<CourtProfilePage />));
    expect(await screen.findByText("Delhi High Court")).toBeInTheDocument();
    expect(screen.getByText(/Delhi · New Delhi/)).toBeInTheDocument();
    expect(screen.getByText("Judges on record")).toBeInTheDocument();
    expect(screen.getByText("Your matters here")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument(); // judges count
    expect(screen.getByText("7")).toBeInTheDocument(); // matters count
  });

  it("renders error state with retry when query fails", async () => {
    fetchCourtProfileMock.mockRejectedValue(new Error("boom"));
    render(withClient(<CourtProfilePage />));
    expect(await screen.findByText(/Could not load court profile/i)).toBeInTheDocument();
  });
});
