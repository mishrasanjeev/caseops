import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchJudgeProfileMock, fetchJudgeAuthoritiesMock } = vi.hoisted(() => ({
  fetchJudgeProfileMock: vi.fn(),
  fetchJudgeAuthoritiesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchJudgeProfile: fetchJudgeProfileMock,
  fetchJudgeAuthorities: fetchJudgeAuthoritiesMock,
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
  identity_source_action: {
    state: "available",
    label: "Open source",
    open_url: "/api/source-actions/open?url=judge",
    source_reference: "https://www.sci.gov.in/judge/a-rao",
    reason: null,
    opens_new_tab: true,
    target_type: null,
    target_id: null,
  },
  aliases: [],
  portfolio_matter_count: 1,
  authority_document_count: 5,
  analytics_eligible_authority_count: 5,
  mapping_coverage_percent: 100,
  coverage_state: "mapped_results",
  coverage_disclaimer:
    "Coverage is limited to source records mapped to this canonical judge identity.",
  recent_authorities: [
    {
      id: "mapped-1",
      title: "Mapped authority",
      court_name: "Supreme Court of India",
      bench_name: "Justice A. Rao",
      decision_date: "2026-02-01",
      case_reference: "C.A. 1/2026",
      neutral_citation: "2026 INSC 2",
      source: "supreme_court_latest_orders",
      source_reference: "https://www.sci.gov.in/judgments/mapped-1.pdf",
      source_action: {
        state: "available",
        label: "Open source",
        open_url: "/api/source-actions/targets/authority_document/mapped-1/open",
        source_reference: "https://www.sci.gov.in/judgments/mapped-1.pdf",
        reason: null,
        opens_new_tab: true,
        target_type: "authority_document",
        target_id: "mapped-1",
      },
      mapping_confidence: "low",
      mapping_status: "needs_review",
      mapping_evidence: { source: "judges_json", ordinal: 0 },
      raw_judge_name: "A Rao",
      role: "sat_on",
      analytics_eligible: false,
    },
  ],
  recent_authorities_has_more: false,
  recent_authorities_next_cursor: null,
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
        source_action: {
          state: "unverified",
          label: "Open source",
          open_url: null,
          source_reference: "https://official.example.test/acme.pdf",
          reason: "Source host is not verified.",
          opens_new_tab: true,
          target_type: "authority_document",
          target_id: "auth-1",
        },
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
    fetchJudgeAuthoritiesMock.mockReset();
  });

  it("renders safe descriptive context analytics", async () => {
    fetchJudgeProfileMock.mockResolvedValue(PROFILE_FIXTURE);
    const { container } = render(withClient(<JudgeProfilePage />));

    expect(await screen.findByText(/Justice A\. Rao/)).toBeInTheDocument();
    expect(screen.getByTestId("judge-context-explorer")).toBeInTheDocument();
    expect(screen.getByText("Court/Judge Context Explorer")).toBeInTheDocument();
    expect(screen.getByText("Act / statute counts")).toBeInTheDocument();
    expect(screen.getByText("Acme v Zenith")).toBeInTheDocument();
    expect(screen.getByText("Mapped authority")).toBeInTheDocument();
    expect(screen.getByText("Excluded from analytics")).toBeInTheDocument();

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

  it("applies authority filters through the canonical endpoint", async () => {
    const user = userEvent.setup();
    fetchJudgeProfileMock.mockResolvedValue(PROFILE_FIXTURE);
    fetchJudgeAuthoritiesMock.mockResolvedValue({
      judge_id: "judge-1",
      authorities: [],
      returned_count: 0,
      has_more: false,
      next_cursor: null,
      mapped_authority_count: 5,
      analytics_eligible_authority_count: 5,
      coverage_state: "no_filter_matches",
      coverage_disclaimer: PROFILE_FIXTURE.coverage_disclaimer,
    });
    render(withClient(<JudgeProfilePage />));

    await screen.findByText("Mapped authority");
    await user.type(screen.getByLabelText("From year"), "2025");
    await user.type(screen.getByLabelText("To year"), "2025");
    await user.selectOptions(screen.getByLabelText("Mapping confidence"), "exact");
    await user.click(screen.getByRole("button", { name: /^filter$/i }));

    await waitFor(() =>
      expect(fetchJudgeAuthoritiesMock).toHaveBeenCalledWith("judge-1", {
        cursor: undefined,
        limit: 20,
        yearFrom: 2025,
        yearTo: 2025,
        mappingConfidence: "exact",
      }),
    );
    expect(await screen.findByText("No authorities match these filters")).toBeInTheDocument();
  });

  it("appends the next page to authorities embedded in the profile", async () => {
    const user = userEvent.setup();
    const nextAuthority = {
      ...PROFILE_FIXTURE.recent_authorities[0],
      id: "mapped-2",
      title: "Mapped authority two",
      source_action: {
        ...PROFILE_FIXTURE.recent_authorities[0].source_action,
        open_url: "/api/source-actions/targets/authority_document/mapped-2/open",
        target_id: "mapped-2",
      },
    };
    fetchJudgeProfileMock.mockResolvedValue({
      ...PROFILE_FIXTURE,
      authority_document_count: 2,
      recent_authorities_has_more: true,
      recent_authorities_next_cursor: "next-page",
    });
    fetchJudgeAuthoritiesMock.mockResolvedValue({
      judge_id: "judge-1",
      authorities: [nextAuthority],
      returned_count: 1,
      has_more: false,
      next_cursor: null,
      mapped_authority_count: 2,
      analytics_eligible_authority_count: 1,
      coverage_state: "mapped_results",
      coverage_disclaimer: PROFILE_FIXTURE.coverage_disclaimer,
    });
    render(withClient(<JudgeProfilePage />));

    await screen.findByText("Mapped authority");
    await user.click(screen.getByRole("button", { name: /load more/i }));

    await waitFor(() =>
      expect(fetchJudgeAuthoritiesMock).toHaveBeenCalledWith("judge-1", {
        cursor: "next-page",
        limit: 20,
      }),
    );
    expect(await screen.findByText("Mapped authority two")).toBeInTheDocument();
    expect(screen.getByText("Mapped authority")).toBeInTheDocument();
    expect(screen.getByText(/2 shown of 2 mapped/i)).toBeInTheDocument();
  });
});
