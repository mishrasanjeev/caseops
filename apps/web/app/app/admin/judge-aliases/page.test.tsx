import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  canCurate: false,
  listJudgeAliases: vi.fn(),
  listJudgeMappingReviews: vi.fn(),
  listCuratorJudges: vi.fn(),
  listCuratorBenches: vi.fn(),
  resolveJudgeMappingReview: vi.fn(),
  createJudgeAlias: vi.fn(),
  createBenchAlias: vi.fn(),
  mergeJudgeIdentities: vi.fn(),
  reprocessJudgeAuthority: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listJudgeAliases: mocks.listJudgeAliases,
  listJudgeMappingReviews: mocks.listJudgeMappingReviews,
  listCuratorJudges: mocks.listCuratorJudges,
  listCuratorBenches: mocks.listCuratorBenches,
  resolveJudgeMappingReview: mocks.resolveJudgeMappingReview,
  createJudgeAlias: mocks.createJudgeAlias,
  createBenchAlias: mocks.createBenchAlias,
  mergeJudgeIdentities: mocks.mergeJudgeIdentities,
  reprocessJudgeAuthority: mocks.reprocessJudgeAuthority,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: () => mocks.canCurate,
}));

import JudgeAliasesAdminPage from "@/app/app/admin/judge-aliases/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("JudgeAliasesAdminPage", () => {
  beforeEach(() => {
    mocks.canCurate = false;
    for (const mock of Object.values(mocks)) {
      if (typeof mock === "function" && "mockReset" in mock) mock.mockReset();
    }
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [],
      returned_count: 0,
      limit: 100,
      has_more: false,
    });
    mocks.listCuratorJudges.mockResolvedValue({
      judges: [],
      returned_count: 0,
      limit: 200,
      has_more: false,
    });
    mocks.listCuratorBenches.mockResolvedValue({
      benches: [],
      returned_count: 0,
      limit: 200,
      has_more: false,
    });
  });

  it("renders the header + a card per judge with all aliases", async () => {
    mocks.listJudgeAliases.mockResolvedValue({
      aliases: [
        {
          id: "a1",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice A.S. Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
        {
          id: "a2",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice Atul Sharachchandra Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
      ],
      judge_count: 1,
      alias_count: 2,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    // Wait for the link to the judge profile (only visible after the
    // query resolves). The judge name appears multiple times in the
    // rendered DOM (link + label + alias chip) so anchor on the
    // /app/courts/judges/{id} href specifically.
    const profileLinks = await screen.findAllByRole("link", {
      name: /Atul Sharachchandra Chandurkar/i,
    });
    expect(profileLinks[0]).toHaveAttribute(
      "href",
      "/app/courts/judges/j1",
    );
    expect(screen.getByText(/Justice A\.S\. Chandurkar/i)).toBeInTheDocument();
    expect(mocks.listJudgeAliases).toHaveBeenCalled();
  });

  it("shows the empty state when no aliases are recorded yet", async () => {
    mocks.listJudgeAliases.mockResolvedValue({
      aliases: [],
      judge_count: 0,
      alias_count: 0,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/No aliases recorded yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    mocks.listJudgeAliases.mockRejectedValue(new Error("network"));
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/Could not load judge aliases/i),
    ).toBeInTheDocument();
  });

  it("resolves one collision evidence slot with the server record version", async () => {
    const user = userEvent.setup();
    mocks.canCurate = true;
    mocks.listJudgeAliases.mockResolvedValue({ aliases: [], judge_count: 0, alias_count: 0 });
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [
        {
          id: "review-1",
          authority_document_id: "authority-1",
          authority_title: "Acme v Zenith",
          court_id: "court-1",
          court_name: "Delhi High Court",
          raw_judge_name: "Justice A Rao",
          source_ordinal: 1,
          reason: "collision",
          status: "open",
          resolver_version: "judge-alias-v2",
          candidates: [{ id: "judge-1", full_name: "Justice A. Rao", court_id: "court-1" }],
          resolved_judge_id: null,
          resolution_note: null,
          record_version: 3,
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
        },
      ],
      returned_count: 1,
      limit: 100,
      has_more: false,
    });
    mocks.resolveJudgeMappingReview.mockResolvedValue({});

    render(withClient(<JudgeAliasesAdminPage />));

    await screen.findByText("Acme v Zenith");
    await user.selectOptions(screen.getByLabelText("Canonical judge"), "judge-1");
    await user.type(
      screen.getByLabelText("Resolution note"),
      "Official roster confirms this identity.",
    );
    await user.click(screen.getByRole("button", { name: /resolve evidence/i }));

    await waitFor(() =>
      expect(mocks.resolveJudgeMappingReview).toHaveBeenCalledWith("review-1", {
        judge_id: "judge-1",
        expected_record_version: 3,
        note: "Official roster confirms this identity.",
      }),
    );
  });

  it("searches the server-owned court catalog when a review has no candidates", async () => {
    const user = userEvent.setup();
    mocks.canCurate = true;
    mocks.listJudgeAliases.mockResolvedValue({ aliases: [], judge_count: 0, alias_count: 0 });
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [
        {
          id: "review-unresolved",
          authority_document_id: "authority-2",
          authority_title: "Unresolved bench record",
          court_id: "court-1",
          court_name: "Delhi High Court",
          raw_judge_name: "A Rao",
          source_ordinal: 0,
          reason: "unresolved",
          status: "open",
          resolver_version: "judge-alias-v2",
          candidates: [],
          resolved_judge_id: null,
          resolution_note: null,
          record_version: 1,
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
        },
      ],
      returned_count: 1,
      limit: 100,
      has_more: false,
    });
    mocks.listCuratorJudges.mockImplementation(
      async (params: { courtId?: string; q?: string }) => ({
        judges:
          params.q === "Rao"
            ? [
                {
                  id: "judge-1",
                  court_id: "court-1",
                  full_name: "Justice A. Rao",
                  source_name: "official_court",
                  source_url: "https://delhihighcourt.nic.in/web/Judges",
                  source_reference: null,
                  identity_version: 1,
                  record_version: 2,
                  merged_into_judge_id: null,
                  is_active: true,
                },
              ]
            : [],
        returned_count: params.q === "Rao" ? 1 : 0,
        limit: 100,
        has_more: false,
      }),
    );

    render(withClient(<JudgeAliasesAdminPage />));

    await screen.findByText("Unresolved bench record");
    await user.type(screen.getByLabelText("Search canonical judges"), "Rao");
    await waitFor(() =>
      expect(mocks.listCuratorJudges).toHaveBeenCalledWith({
        courtId: "court-1",
        q: "Rao",
        limit: 100,
      }),
    );
    await user.selectOptions(screen.getByLabelText("Canonical judge"), "judge-1");
    expect(screen.getByLabelText("Canonical judge")).toHaveValue("judge-1");
  });
});
