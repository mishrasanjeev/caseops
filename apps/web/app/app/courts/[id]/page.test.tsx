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
  analytics: {
    disclaimer:
      "Descriptive historical context from indexed source records only; not legal advice, not a forecast, and not a forum-selection recommendation.",
    sample_size: 6,
    analyzed_document_count: 6,
    sample_size_threshold: 5,
    sample_size_label: "descriptive",
    pattern_claims_suppressed: false,
    limitations: ["Counts are descriptive metadata from indexed authority records."],
    practice_area_counts: [{ label: "Commercial / Arbitration", count: 4 }],
    statute_counts: [{ label: "Arbitration Act", count: 4 }],
    court_counts: [],
    practice_area_trends: [],
    case_list: [
      {
        id: "auth-1",
        title: "Acme v Zenith",
        court_name: "Delhi High Court",
        bench_name: "Justice A",
        decision_date: "2026-01-01",
        case_reference: "ARB.P. 1/2026",
        neutral_citation: "2026:DHC:1",
        source: "official",
        source_reference: "https://official.example.test/acme.pdf",
        practice_area: "Commercial / Arbitration",
        statutes_or_sections: ["Section 11 Arbitration Act"],
        summary_preview: "Bounded source-backed metadata summary.",
      },
    ],
  },
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
    expect(screen.getByTestId("court-context-explorer")).toBeInTheDocument();
    expect(screen.getByText("Court Context Explorer")).toBeInTheDocument();
    expect(screen.getByText("Acme v Zenith")).toBeInTheDocument();
  });

  it("renders error state with retry when query fails", async () => {
    fetchCourtProfileMock.mockRejectedValue(new Error("boom"));
    render(withClient(<CourtProfilePage />));
    expect(await screen.findByText(/Could not load court profile/i)).toBeInTheDocument();
  });
});
