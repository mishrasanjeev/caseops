import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAppealStrength: fetchMock,
}));

import { AppealStrengthPanel } from "./AppealStrengthPanel";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("AppealStrengthPanel", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("renders no-draft note + weak overall when has_draft is false", async () => {
    fetchMock.mockResolvedValue({
      matter_id: "m-1",
      draft_id: null,
      overall_strength: "weak",
      bench_context_quality: "low",
      has_draft: false,
      ground_assessments: [],
      weak_evidence_paths: ["No appeal-memorandum draft on this matter yet."],
      recommended_edits: [],
    });
    render(withClient(<AppealStrengthPanel matterId="m-1" />));
    await waitFor(() =>
      expect(
        screen.getByTestId("appeal-strength-no-draft-note"),
      ).toBeInTheDocument(),
    );
    // Weak label badge present
    expect(screen.getByText(/^weak$/)).toBeInTheDocument();
  });

  it("renders per-ground rows with citation coverage badges", async () => {
    fetchMock.mockResolvedValue({
      matter_id: "m-2",
      draft_id: "d-2",
      overall_strength: "moderate",
      bench_context_quality: "high",
      has_draft: true,
      ground_assessments: [
        {
          ordinal: 1,
          summary: "Lower court overlooked the controlling authority.",
          citation_coverage: "supported",
          supporting_authorities: [
            {
              citation: "2024:BHC:99",
              resolved_authority_id: "a-1",
              title: "Test v Seed",
              forum_level: "high_court",
              strength_label: "peer",
            },
          ],
          bench_history_match_count: 1,
          suggestions: [],
        },
        {
          ordinal: 2,
          summary: "Order is contrary to record at p.47.",
          citation_coverage: "uncited",
          supporting_authorities: [],
          bench_history_match_count: 0,
          suggestions: [
            "Ground 2 has no cited authority. Add at least one citable authority anchoring the legal proposition.",
          ],
        },
      ],
      weak_evidence_paths: [
        "Ground 2 (Order is contrary to record at p.47.…) has no cited authority — submission risk.",
      ],
      recommended_edits: [
        "Ground 2 has no cited authority. Add at least one citable authority anchoring the legal proposition.",
      ],
    });
    render(withClient(<AppealStrengthPanel matterId="m-2" />));
    await waitFor(() =>
      expect(screen.getByTestId("appeal-strength-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("appeal-strength-ground-1")).toBeInTheDocument();
    expect(screen.getByTestId("appeal-strength-ground-2")).toBeInTheDocument();
    expect(screen.getByText(/2024:BHC:99/)).toBeInTheDocument();
    expect(screen.getByText(/submission risk/)).toBeInTheDocument();
    // Bench-aware rule: no favorability copy in the rendered surface
    const surface = document.body.innerHTML.toLowerCase();
    for (const forbidden of [
      "favourable",
      "favorable",
      "tendency",
      "tends to",
      "usually grants",
      "probability",
      "winnable",
      "winnability",
    ]) {
      expect(surface).not.toContain(forbidden);
    }
  });
});
