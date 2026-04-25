import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchCtxMock } = vi.hoisted(() => ({
  fetchCtxMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchBenchStrategyContext: fetchCtxMock,
}));

import { BenchContextCard } from "./BenchContextCard";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("BenchContextCard", () => {
  beforeEach(() => {
    fetchCtxMock.mockReset();
  });

  it("renders the structured-match coverage + counts when quality is high", async () => {
    fetchCtxMock.mockResolvedValue({
      matter_id: "m-1",
      court_name: "Bombay High Court",
      structured_match_coverage_percent: 75,
      context_quality: "high",
      judge_candidates: [
        {
          judge_id: "j-1",
          full_name: "Justice X",
          structured_authority_count: 12,
          fallback_authority_count: 0,
        },
      ],
      similar_authorities: [
        {
          id: "a-1",
          title: "ABC v XYZ — appeal",
          decision_date: "2024-01-01",
          case_reference: "APPL 1/2024",
          neutral_citation: "2024:BHC:1",
          bench_name: "Bench A",
          forum_level: "high_court",
          structured_match: true,
        },
      ],
      practice_area_patterns: [
        {
          area: "Civil / Contract",
          authority_count: 5,
          sample_authority_ids: ["a-1", "a-2", "a-3"],
        },
      ],
      recurring_tests: [
        {
          phrase: "balance of convenience",
          occurrences: 4,
          sample_authority_ids: ["a-1", "a-2", "a-3"],
        },
      ],
      authorities_frequently_cited: [],
      drafting_cautions: ["Watch out for limitation."],
      unsupported_gaps: [],
    });
    render(withClient(<BenchContextCard matterId="m-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("bench-context-card")).toBeInTheDocument(),
    );
    expect(screen.getByText(/75%/)).toBeInTheDocument();
    expect(screen.getByText(/Civil \/ Contract/)).toBeInTheDocument();
    expect(screen.getByText(/balance of convenience/)).toBeInTheDocument();
    expect(screen.getByText(/Watch out for limitation/)).toBeInTheDocument();
    // The "no favorability" rule is structural — quality badge shows
    // the level but never a "favourable" label.
    expect(screen.queryByText(/favourable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/usually grants/i)).not.toBeInTheDocument();
  });

  it("renders the limitation note when quality is low", async () => {
    fetchCtxMock.mockResolvedValue({
      matter_id: "m-2",
      court_name: null,
      structured_match_coverage_percent: 0,
      context_quality: "low",
      judge_candidates: [],
      similar_authorities: [],
      practice_area_patterns: [],
      recurring_tests: [],
      authorities_frequently_cited: [],
      drafting_cautions: [
        "Only 0% of the bench-history matches come from structured judges_json.",
      ],
      unsupported_gaps: [],
    });
    render(withClient(<BenchContextCard matterId="m-2" />));
    await waitFor(() =>
      expect(
        screen.getByTestId("bench-context-fallback-note"),
      ).toBeInTheDocument(),
    );
    // Pattern detail must be hidden when quality is low (so the
    // lawyer can't accidentally rely on a thin signal).
    expect(
      screen.queryByText(/Practice-area concentration/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Recurring legal tests/i),
    ).not.toBeInTheDocument();
  });

  it("renders the limitation note when quality is none", async () => {
    fetchCtxMock.mockResolvedValue({
      matter_id: "m-3",
      court_name: null,
      structured_match_coverage_percent: 0,
      context_quality: "none",
      judge_candidates: [],
      similar_authorities: [],
      practice_area_patterns: [],
      recurring_tests: [],
      authorities_frequently_cited: [],
      drafting_cautions: [],
      unsupported_gaps: [],
    });
    render(withClient(<BenchContextCard matterId="m-3" />));
    await waitFor(() =>
      expect(
        screen.getByTestId("bench-context-fallback-note"),
      ).toBeInTheDocument(),
    );
  });
});
