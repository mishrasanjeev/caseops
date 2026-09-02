import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  fetchCore: vi.fn(),
  fetchReports: vi.fn(),
  fetchPortfolio: vi.fn(),
  finalize: vi.fn(),
  getReview: vi.fn(),
  listMatters: vi.fn(),
  listReviews: vi.fn(),
  publish: vi.fn(),
  searchParams: "report=report-1",
  update: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.searchParams),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAuthorityResearchReports: mocks.fetchReports,
  fetchIpCoreRecords: mocks.fetchCore,
  fetchIpPortfolio: mocks.fetchPortfolio,
  listMatters: mocks.listMatters,
}));

vi.mock("@/lib/api/intelligent-reviews", () => ({
  createIntelligentReview: mocks.create,
  finalizeIntelligentReview: mocks.finalize,
  getIntelligentReview: mocks.getReview,
  listIntelligentReviews: mocks.listReviews,
  publishIntelligentReview: mocks.publish,
  updateIntelligentReviewAuthorities: mocks.update,
}));

vi.mock("@/lib/capabilities", () => ({
  can: () => true,
  useResolvedCapabilities: () => [
    "recommendations:generate",
    "recommendations:decide",
    "drafts:review",
  ],
  useRole: () => "owner",
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import IntelligentReviewsPage from "@/app/app/research/reviews/page";

const report = {
  id: "report-1",
  company_id: "company-1",
  created_by_membership_id: "membership-1",
  name: "Opposition authorities",
  query: "prior use and deceptive similarity",
  mode: "keyword",
  criteria: {},
  results: [
    {
      authority_document_id: "authority-support",
      title: "Aster Brands v Nova",
      court_name: "Supreme Court of India",
      forum_level: "supreme_court",
      document_type: "judgment",
      decision_date: "2025-01-10",
      case_reference: "CA 100/2025",
      neutral_citation: "2025 INSC 100",
      source: "official",
      source_reference: "https://judgments.example/support",
      source_action: {
        state: "available",
        label: "Open source",
        open_url: "/api/source-actions/targets/authority_document/authority-support/open",
        source_reference: "https://judgments.example/support",
        reason: null,
        opens_new_tab: true,
      },
    },
    {
      authority_document_id: "authority-contrary",
      title: "Nova Products v Aster",
      court_name: "Delhi High Court",
      forum_level: "high_court",
      document_type: "judgment",
      decision_date: "2024-02-10",
      case_reference: "CS(COMM) 10/2024",
      neutral_citation: "2024:DHC:100",
      source: "official",
      source_reference: "https://judgments.example/contrary",
      source_action: {
        state: "available",
        label: "Open source",
        open_url: "/api/source-actions/targets/authority_document/authority-contrary/open",
        source_reference: "https://judgments.example/contrary",
        reason: null,
        opens_new_tab: true,
      },
    },
  ],
  analysis_version: "authority-search-v3",
  generated_at: "2026-08-28T08:00:00Z",
  created_at: "2026-08-28T08:00:00Z",
};

const supporting = {
  authority_document_id: "authority-support",
  disposition: "supporting",
  title: "Aster Brands v Nova",
  citation: "2025 INSC 100",
  court: "Supreme Court of India",
  decision_date: "2025-01-10",
  source_url: "https://judgments.example/support",
  source_action: {
    state: "available",
    label: "Open source",
    open_url: "/api/source-actions/targets/authority_document/authority-support/open",
    source_reference: "https://judgments.example/support",
    reason: null,
    opens_new_tab: true,
    target_type: "authority_document",
    target_id: "authority-support",
  },
  passage: "Proved prior use supported the passing-off claim.",
  relevance: "Supports the client's proved prior-use position.",
  treatment: "Applied",
  access_state: "available",
  content_hash: "support-hash",
  source_version: "official-v1",
  retrieved_at: "2026-08-27T08:00:00Z",
  selected: true,
} as const;

const contrary = {
  authority_document_id: "authority-contrary",
  disposition: "contrary",
  title: "Nova Products v Aster",
  citation: "2024:DHC:100",
  court: "Delhi High Court",
  decision_date: "2024-02-10",
  source_url: "https://judgments.example/contrary",
  source_action: {
    state: "available",
    label: "Open source",
    open_url: "/api/source-actions/targets/authority_document/authority-contrary/open",
    source_reference: "https://judgments.example/contrary",
    reason: null,
    opens_new_tab: true,
    target_type: "authority_document",
    target_id: "authority-contrary",
  },
  passage: "Visual comparison alone did not prove likely confusion.",
  relevance: "Tests the evidentiary gap in the proposed opposition.",
  treatment: "Distinguished",
  access_state: "available",
  content_hash: "contrary-hash",
  source_version: "official-v1",
  retrieved_at: "2026-08-27T08:00:00Z",
  selected: true,
} as const;

function reviewFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "review-1",
    company_id: "company-1",
    matter_id: "matter-1",
    ip_docket_id: null,
    ip_proceeding_id: null,
    source_research_report_id: "report-1",
    state: "ready",
    progress: 100,
    error_code: null,
    issue: "Does prior use support the trademark opposition?",
    relevant_facts: ["The client claims continuous use from 2018."],
    applicable_provisions: [
      { text: "Prior-use principles require proved use.", authority_document_ids: ["authority-support"] },
    ],
    supporting_authorities: [supporting],
    contrary_authorities: [contrary],
    factual_analogies: [
      { text: "Both records turn on market evidence.", authority_document_ids: ["authority-support", "authority-contrary"] },
    ],
    gaps: ["Registry status requires current verification."],
    lawyer_checks: ["Verify the current statutory text."],
    unresolved_contradictions: ["First-use date is recorded as both 2018 and 2019."],
    abstention_reason: null,
    stale_warning: null,
    source_freshness_at: "2026-08-27T08:00:00Z",
    non_exhaustive_disclaimer: "This is source-bounded decision support, not exhaustive legal research.",
    lawyer_notes: null,
    completeness: {
      selected_authority_count: 2,
      supporting_authority_count: 1,
      contrary_authority_count: 1,
      cited_assertion_count: 2,
      unsupported_assertion_count: 0,
      complete: true,
      reasons: [],
    },
    review_template_version: "caseops-intelligent-review-v1",
    prompt_policy_version: "caseops-legal-review-safety-v2",
    model_run_id: "run-1",
    output_hash: "output-hash",
    finalized_by_membership_id: null,
    finalized_at: null,
    published_draft_id: null,
    created_at: "2026-08-28T08:00:00Z",
    updated_at: "2026-08-28T08:01:00Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><IntelligentReviewsPage /></QueryClientProvider>);
}

describe("IntelligentReviewsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.searchParams = "report=report-1";
    mocks.fetchReports.mockResolvedValue({ reports: [report] });
    mocks.fetchCore.mockResolvedValue({ assets: [], applications: [], proceedings: [], identifiers: [] });
    mocks.fetchPortfolio.mockResolvedValue({ rows: [], counts: {}, filters: {}, limit: 100, next_cursor: null });
    mocks.listMatters.mockResolvedValue({
      matters: [{ id: "matter-1", matter_code: "IP-101", title: "Aster opposition", status: "active" }],
      next_cursor: null,
    });
    mocks.listReviews.mockResolvedValue({ reviews: [reviewFixture()] });
    mocks.getReview.mockResolvedValue(reviewFixture());
  });

  it("renders both sides, exact source URLs, frozen metadata, gaps, and contradictions", async () => {
    renderPage();
    expect(await screen.findByText("Supporting and contrary authorities")).toBeInTheDocument();
    const detail = within(screen.getByTestId("intelligent-review-detail"));
    expect(detail.getByText("Aster Brands v Nova")).toBeInTheDocument();
    expect(detail.getByText("Nova Products v Aster")).toBeInTheDocument();
    expect(detail.getByText("https://judgments.example/support")).toBeInTheDocument();
    expect(detail.getByText("https://judgments.example/contrary")).toBeInTheDocument();
    expect(screen.getByText("Registry status requires current verification.")).toBeInTheDocument();
    expect(screen.getByText(/both 2018 and 2019/)).toBeInTheDocument();
    expect(screen.getByText(/not exhaustive legal research/)).toBeInTheDocument();
    expect(screen.getByText(/caseops-intelligent-review-v1/)).toBeInTheDocument();
  });

  it("queues a review using server-owned Matter, report, and authority identifiers", async () => {
    const user = userEvent.setup();
    mocks.listReviews.mockResolvedValue({ reviews: [] });
    mocks.create.mockResolvedValue(reviewFixture({ state: "queued", progress: 0 }));
    renderPage();
    await screen.findByText("Opposition authorities");
    await user.click(screen.getByRole("combobox", { name: "Matter target" }));
    await user.click(await screen.findByRole("option", { name: /IP-101/ }));
    await user.click(screen.getByRole("button", { name: "Generate review" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0]).toEqual(expect.objectContaining({
        sourceResearchReportId: "report-1",
        matterId: "matter-1",
        ipDocketId: null,
        includedAuthorityIds: ["authority-support", "authority-contrary"],
      }));
  });

  it("freezes a server-owned opposition proceeding for IP Draft handoff", async () => {
    const user = userEvent.setup();
    mocks.listReviews.mockResolvedValue({ reviews: [] });
    mocks.fetchPortfolio.mockResolvedValue({
      rows: [{
        docket_id: "docket-1",
        primary_identifier: "TM-1001",
        title: "Aster mark",
        record_type: "trademark",
        status: "active",
        is_active: true,
      }],
      counts: {}, filters: {}, limit: 100, next_cursor: null,
    });
    mocks.fetchCore.mockResolvedValue({
      assets: [], applications: [], identifiers: [],
      proceedings: [{
        id: "proceeding-1",
        docket_id: "docket-1",
        proceeding_kind: "opposition",
        side: "opponent",
        stage: "notice_filed",
        office: "Trade Marks Registry Delhi",
      }],
    });
    mocks.create.mockResolvedValue(reviewFixture({ state: "queued", progress: 0 }));
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "IP docket" }));
    await user.click(screen.getByRole("combobox", { name: "IP docket target" }));
    await user.click(await screen.findByRole("option", { name: /TM-1001/ }));
    await user.click(await screen.findByRole("combobox", { name: "Opposition proceeding for Draft handoff" }));
    await user.click(await screen.findByRole("option", { name: /opponent.*notice_filed/i }));
    await user.click(screen.getByRole("button", { name: "Generate review" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0]).toEqual(expect.objectContaining({
        matterId: null,
        ipDocketId: "docket-1",
        ipProceedingId: "proceeding-1",
      }));
  });

  it("requires completeness before finalization and preserves lawyer selection", async () => {
    const user = userEvent.setup();
    const incomplete = reviewFixture({
      supporting_authorities: [supporting],
      contrary_authorities: [{ ...contrary, selected: false }],
      completeness: {
        selected_authority_count: 1,
        supporting_authority_count: 1,
        contrary_authority_count: 0,
        cited_assertion_count: 1,
        unsupported_assertion_count: 1,
        complete: false,
        reasons: ["1 analysis assertion(s) no longer have a selected citation."],
      },
      updated_at: "2026-08-28T08:02:00Z",
    });
    mocks.update.mockResolvedValue(incomplete);
    renderPage();
    await screen.findByText("Supporting and contrary authorities");
    const contraryCheckbox = within(screen.getByTestId("intelligent-review-detail")).getByRole(
      "checkbox",
      { name: /Nova Products v Aster/ },
    );
    await user.click(contraryCheckbox);
    await user.click(screen.getByRole("button", { name: "Save selection" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      includedAuthorityIds: ["authority-support"],
    })));
    expect(await screen.findByText(/no longer have a selected citation/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalize review" })).toBeDisabled();
  });

  it("finalizes and publishes only through the lawyer and Draft gates", async () => {
    const user = userEvent.setup();
    const finalized = reviewFixture({ state: "finalized", finalized_at: "2026-08-28T09:00:00Z", updated_at: "2026-08-28T09:00:00Z" });
    const published = reviewFixture({ state: "published", published_draft_id: "draft-1", updated_at: "2026-08-28T09:01:00Z" });
    mocks.finalize.mockResolvedValue(finalized);
    mocks.publish.mockResolvedValue({ review: published, draft_id: "draft-1", draft_version_id: "version-1" });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Finalize review" }));
    await user.click(await screen.findByRole("button", { name: "Publish to Drafts" }));
    expect(await screen.findByRole("link", { name: /Open Draft/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1/drafts/draft-1",
    );
  });

  it("deep-links an IP review Draft into its exact proceeding workspace", async () => {
    const published = reviewFixture({
      state: "published",
      matter_id: null,
      ip_docket_id: "docket-1",
      ip_proceeding_id: "proceeding-1",
      published_draft_id: "draft-1",
    });
    mocks.listReviews.mockResolvedValue({ reviews: [published] });
    mocks.getReview.mockResolvedValue(published);
    renderPage();
    expect(await screen.findByRole("link", { name: /Open Draft/ })).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-1&view=proceedings&proceeding=proceeding-1&draft=draft-1",
    );
  });

  it("loads a permission-visible review deep link even when it is outside bounded history", async () => {
    const linked = reviewFixture({ id: "review-linked", issue: "Linked opposition review" });
    mocks.searchParams = "report=report-1&review=review-linked";
    mocks.listReviews.mockResolvedValue({ reviews: [reviewFixture({ id: "review-newer" })] });
    mocks.getReview.mockImplementation(async (reviewId: string) => {
      expect(reviewId).toBe("review-linked");
      return linked;
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "Linked opposition review" })).toBeInTheDocument();
    expect(mocks.getReview).toHaveBeenCalledWith("review-linked");
  });

  it("shows typed abstention without presenting invented analysis", async () => {
    const abstained = reviewFixture({
      state: "abstained",
      error_code: "insufficient_accessible_sources",
      abstention_reason: "No selected authority has both an accessible source and usable text.",
      supporting_authorities: [],
      contrary_authorities: [],
    });
    mocks.listReviews.mockResolvedValue({ reviews: [abstained] });
    mocks.getReview.mockResolvedValue(abstained);
    renderPage();
    expect(await screen.findByText(/No selected authority has both an accessible source/)).toBeInTheDocument();
    expect(screen.queryByText("Supporting and contrary authorities")).not.toBeInTheDocument();
  });
});
