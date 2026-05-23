import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchJudgeProfileMock } = vi.hoisted(() => ({
  fetchJudgeProfileMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchJudgeProfile: fetchJudgeProfileMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ judge_id: "judge-1" }),
}));

import JudgeProfilePage from "@/app/app/courts/judges/[judge_id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PROFILE_FIXTURE = {
  judge: {
    id: "judge-1",
    court_id: "court-1",
    full_name: "Justice A. Rao",
    honorific: "Hon'ble",
    current_position: "Puisne Judge",
    is_active: true,
  },
  court: {
    id: "court-1",
    name: "Supreme Court of India",
    short_name: "SC",
    forum_level: "supreme_court",
    jurisdiction: "India",
    seat_city: "New Delhi",
    hc_catalog_key: null,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  portfolio_matter_count: 1,
  authority_document_count: 5,
  recent_authorities: [],
  practice_areas: [{ area: "Commercial / Arbitration", count: 3 }],
  decision_volume: [{ year: 2026, count: 5 }],
  earliest_decision_date: "2026-01-01",
  latest_decision_date: "2026-02-01",
  structured_match_coverage_percent: 100,
  career: [],
  analytics: {
    disclaimer:
      "Descriptive historical context from indexed source records only; not legal advice, not a forecast, and not a forum-selection recommendation.",
    sample_size: 5,
    analyzed_document_count: 5,
    sample_size_threshold: 5,
    sample_size_label: "descriptive",
    pattern_claims_suppressed: false,
    limitations: ["Counts are descriptive metadata from indexed authority records."],
    practice_area_counts: [{ label: "Commercial / Arbitration", count: 3 }],
    statute_counts: [{ label: "Arbitration Act", count: 3 }],
    court_counts: [{ label: "Supreme Court of India", count: 5 }],
    practice_area_trends: [
      { year: 2026, area: "Commercial / Arbitration", count: 3 },
    ],
    case_list: [
      {
        id: "auth-1",
        title: "Acme v Zenith",
        court_name: "Supreme Court of India",
        bench_name: "Justice A. Rao",
        decision_date: "2026-01-01",
        case_reference: "ARB.P. 1/2026",
        neutral_citation: "2026 INSC 1",
        source: "official",
        source_reference: "https://official.example.test/acme.pdf",
        practice_area: "Commercial / Arbitration",
        statutes_or_sections: ["Section 11 Arbitration Act"],
        summary_preview: "Bounded source-backed metadata summary.",
      },
    ],
  },
};

describe("JudgeProfilePage", () => {
  beforeEach(() => {
    fetchJudgeProfileMock.mockReset();
  });

  it("renders safe descriptive context analytics", async () => {
    fetchJudgeProfileMock.mockResolvedValue(PROFILE_FIXTURE);
    const { container } = render(withClient(<JudgeProfilePage />));

    expect(await screen.findByText(/Justice A\. Rao/)).toBeInTheDocument();
    expect(screen.getByTestId("judge-context-explorer")).toBeInTheDocument();
    expect(screen.getByText("Court/Judge Context Explorer")).toBeInTheDocument();
    expect(screen.getByText("Act / statute counts")).toBeInTheDocument();
    expect(screen.getByText("Acme v Zenith")).toBeInTheDocument();

    const pageText = (container.textContent ?? "").toLowerCase();
    for (const forbidden of [
      "best judge",
      "best bench",
      "best court",
      "most suitable judge",
      "success probability",
      "likely to win",
      "likely to lose",
      "favorable recommendation",
      "unfavorable recommendation",
      "judge reputation score",
      "judge shopping",
      "outcome prediction",
    ]) {
      expect(pageText).not.toContain(forbidden);
    }
  });
});
