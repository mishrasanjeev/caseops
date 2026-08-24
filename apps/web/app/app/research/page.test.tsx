import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  statsMock,
  searchMock,
  createReportMock,
  indianKanoonReadinessMock,
  indianKanoonSearchMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  statsMock: vi.fn(),
  searchMock: vi.fn(),
  createReportMock: vi.fn(),
  indianKanoonReadinessMock: vi.fn(),
  indianKanoonSearchMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAuthorityCorpusStats: statsMock,
  searchAuthorities: searchMock,
  createAuthorityResearchReport: createReportMock,
  createAuthorityAnnotation: vi.fn(),
  fetchIndianKanoonReadiness: indianKanoonReadinessMock,
  searchIndianKanoon: indianKanoonSearchMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import ResearchPage from "@/app/app/research/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ResearchPage", () => {
  beforeEach(() => {
    statsMock.mockReset();
    searchMock.mockReset();
    createReportMock.mockReset();
    indianKanoonReadinessMock.mockReset();
    indianKanoonSearchMock.mockReset();
    createReportMock.mockResolvedValue({ id: "report-1" });
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    statsMock.mockResolvedValue({ document_count: 0 });
    searchMock.mockResolvedValue({
      query: "",
      mode: "keyword",
      provider: "caseops-authority-search-v2",
      generated_at: "2026-05-23T00:00:00Z",
      results: [],
      contextual_plan: null,
      coverage_notice: null,
      total_after_filter: 0,
      offset: 0,
      outcome: "no_matching_documents",
      diagnostics: {},
      corpus_coverage: {
        document_count: 0,
        chunk_count: 0,
        embedded_chunk_count: 0,
        forum_counts: {},
        last_ingested_at: null,
        last_indexed_at: null,
        index_state: "unavailable",
        scope_summary: "indexed authority corpus; en language scope",
      },
    });
    indianKanoonReadinessMock.mockResolvedValue({
      provider: "indian-kanoon",
      state: "ready",
      configured: true,
      enabled: true,
      external_calls_enabled: true,
      missing_config_names: [],
      missing_approval_keys: [],
      missing_cost_categories: [],
      permitted_uses: ["document_display", "research_storage", "search"],
      daily_budget_minor: 10000,
      monthly_budget_minor: 100000,
      retention_days: 30,
      terms_owner: "CaseOps legal",
      terms_approved_at: "2026-08-24T00:00:00Z",
      terms_expires_at: "2026-09-24T00:00:00Z",
      kill_switch_name: "INDIAN_KANOON_ENABLED",
      attribution: {
        label: "Powered by Indian Kanoon",
        provider_url: "https://indiankanoon.org/",
        terms_url: "https://indiankanoon.org/terms.html",
        logo_required: true,
      },
      limitations: [],
    });
    indianKanoonSearchMock.mockResolvedValue({
      query: "constitutional proportionality",
      page_number: 0,
      returned_count: 1,
      results: [
        {
          document_id: "12345",
          title: "Example Industries v State",
          publisher: "Supreme Court of India",
          jurisdiction: "India",
          issuing_body: "Supreme Court of India",
          source_category: "supreme_court",
          document_type: "judgment",
          decision_or_publication_date: "2026-08-20",
          canonical_citation: "2026 INSC 101",
          authority_status: "provider_record_unreviewed",
          binding_status: "verify_jurisdiction_and_precedential_status",
          canonical_url: "https://indiankanoon.org/doc/12345/",
          source_action: {
            state: "available",
            label: "Open source",
            open_url:
              "/api/source-actions/open?url=https%3A%2F%2Findiankanoon.org%2Fdoc%2F12345%2F",
            source_reference: "https://indiankanoon.org/doc/12345/",
            reason: null,
            opens_new_tab: true,
          },
          attribution: {
            label: "Powered by Indian Kanoon",
            provider_url: "https://indiankanoon.org/",
            terms_url: "https://indiankanoon.org/terms.html",
            logo_required: true,
          },
          rank: 1,
          headline: "The exact passage matched the query.",
        },
      ],
      call: {
        cached: false,
        stale: false,
        freshness_warning: null,
        retrieved_at: "2026-08-25T00:00:00Z",
        estimated_cost_minor: 50,
        currency: "INR",
        cost_category: "legal_source_search",
        cost_basis: "approved_actual",
      },
      attribution: {
        label: "Powered by Indian Kanoon",
        provider_url: "https://indiankanoon.org/",
        terms_url: "https://indiankanoon.org/terms.html",
        logo_required: true,
      },
      disclaimer: "Verify the exact passage and subsequent treatment before reliance.",
    });
  });

  it("renders the research query input and submit button", () => {
    render(withClient(<ResearchPage />));
    expect(screen.getByTestId("research-query-input")).toBeInTheDocument();
    expect(screen.getByTestId("research-query-submit")).toBeInTheDocument();
  });

  it("runs a readiness-gated licensed search with attribution and source access", async () => {
    render(withClient(<ResearchPage />));
    fireEvent.click(screen.getByTestId("research-source-indian-kanoon"));
    expect(
      await screen.findByText(
        "Powered by Indian Kanoon. Licensed access is active for this workspace.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "constitutional proportionality" },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    expect(
      await screen.findByText("Example Industries v State"),
    ).toBeInTheDocument();
    expect(indianKanoonSearchMock).toHaveBeenCalledWith({
      query: "constitutional proportionality",
      maxResults: 20,
    });
    expect(screen.getByTestId("research-indian-kanoon-attribution")).toHaveTextContent(
      "Powered by Indian Kanoon",
    );
    expect(screen.getByTestId("research-indian-kanoon-attribution")).toHaveTextContent(
      "estimated provider cost ₹0.50",
    );
    expect(screen.getByTestId("source-action-open")).toHaveTextContent("Source");
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("keeps licensed provider calls fail-closed when readiness is blocked", async () => {
    indianKanoonReadinessMock.mockResolvedValueOnce({
      ...(await indianKanoonReadinessMock()),
      state: "blocked_terms",
      enabled: false,
      external_calls_enabled: false,
    });
    indianKanoonReadinessMock.mockClear();
    render(withClient(<ResearchPage />));
    fireEvent.click(screen.getByTestId("research-source-indian-kanoon"));
    expect(
      await screen.findByText(/Licensed access is unavailable/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "constitutional proportionality" },
    });
    expect(screen.getByTestId("research-query-submit")).toBeDisabled();
    expect(indianKanoonSearchMock).not.toHaveBeenCalled();
  });

  it("uses search coverage without issuing a competing corpus-stats request", async () => {
    render(withClient(<ResearchPage />));

    expect(statsMock).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "bail application" },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(1));
    expect(statsMock).not.toHaveBeenCalled();
    expect(
      await screen.findByText(
        "Searching 0 judgments across SC + HCs. Every result links to source.",
      ),
    ).toBeInTheDocument();
  });

  it("submits contextual mode for fact-pattern research", async () => {
    render(withClient(<ResearchPage />));

    fireEvent.click(screen.getByTestId("research-mode-contextual"));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: {
        value:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    await waitFor(() => {
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: "contextual",
          query:
            "Cheque bounced due to insufficient funds and notice was sent after 35 days",
        }),
      );
    });
  });

  it("keeps filter edits staged until Search is clicked", async () => {
    render(withClient(<ResearchPage />));

    const submit = screen.getByTestId("research-query-submit");
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "Section 138 notice delay" },
    });
    fireEvent.change(screen.getByTestId("research-filter-court"), {
      target: { value: "Delhi" },
    });

    expect(submit).not.toBeDisabled();
    expect(searchMock).not.toHaveBeenCalled();

    fireEvent.click(submit);

    await waitFor(() => {
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          query: "Section 138 notice delay",
          courtName: "Delhi",
        }),
      );
    });
  });

  it("submits exact citation mode and keeps the search action operable", async () => {
    render(withClient(<ResearchPage />));
    fireEvent.click(screen.getByTestId("research-mode-exact-citation"));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "2026:DHC:111" },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));
    await waitFor(() =>
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({ mode: "exact_citation", query: "2026:DHC:111" }),
      ),
    );
  });

  it("renders corpus unavailable separately from no matching documents", async () => {
    searchMock.mockResolvedValue({
      query: "section 11 trademark",
      mode: "keyword",
      provider: "caseops-authority-search-v2",
      generated_at: "2026-08-04T00:00:00Z",
      results: [],
      contextual_plan: null,
      coverage_notice: "The authority corpus is unavailable.",
      total_after_filter: 0,
      offset: 0,
      outcome: "corpus_unavailable",
      diagnostics: {},
      corpus_coverage: {
        document_count: 0,
        chunk_count: 0,
        embedded_chunk_count: 0,
        forum_counts: {},
        last_ingested_at: null,
        last_indexed_at: null,
        index_state: "unavailable",
        scope_summary: "indexed authority corpus; en language scope",
      },
    });
    render(withClient(<ResearchPage />));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: { value: "section 11 trademark" },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));
    expect(await screen.findByText("Corpus unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("research-corpus-coverage")).toHaveTextContent(
      "index unavailable",
    );
  });

  it("submits a partial court filter and renders the matching court result", async () => {
    searchMock.mockResolvedValue({
      query: "Triple test for bail under BNSS s.483; parity; custody duration",
      mode: "keyword",
      provider: "caseops-authority-search-v2",
      generated_at: "2026-06-29T00:00:00Z",
      results: [
        {
          authority_document_id: "madras-bnss-483-bail",
          title: "Triple test for bail under BNSS section 483",
          court_name: "Madras High Court",
          forum_level: "high_court",
          document_type: "judgment",
          decision_date: "2026-06-15",
          case_reference: "CRL.O.P. 483/2026",
          neutral_citation: "2026:MHC:483",
          bench_name: "Justice M. Sundar",
          summary: "Madras High Court judgment on parity and custody duration.",
          source: "test",
          source_reference: "https://official.example.test/madras-bail.pdf",
          snippet:
            "The Madras High Court applied the triple test for bail under BNSS section 483, considering parity and custody duration.",
          score: 220,
          matched_terms: ["triple", "bail", "bnss", "parity", "custody"],
          relevance_reason:
            "Why this result: indexed passage match on bail; no adverse treatment found in the indexed citation graph. Verify the source before relying on it.",
          worst_treatment: null,
          adverse_count: 0,
        },
      ],
      contextual_plan: null,
      coverage_notice: null,
      total_after_filter: 1,
      offset: 0,
    });
    render(withClient(<ResearchPage />));

    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: {
        value: "Triple test for bail under BNSS s.483; parity; custody duration",
      },
    });
    fireEvent.change(screen.getByTestId("research-filter-court"), {
      target: { value: "Madras" },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    expect(
      await screen.findByText("Triple test for bail under BNSS section 483"),
    ).toBeInTheDocument();
    expect(screen.getByText("Madras High Court")).toBeInTheDocument();
    expect(screen.getByText(/2026:MHC:483/)).toBeInTheDocument();
    expect(screen.getByText(/Publisher: test/)).toBeInTheDocument();
    expect(screen.getByTestId("research-result-relevance")).toHaveTextContent(
      "Why this result",
    );
    expect(searchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        courtName: "Madras",
      }),
    );
  });

  it("suppresses garbled OCR result cards when readable authority results exist", async () => {
    searchMock.mockResolvedValue({
      query:
        "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      mode: "contextual",
      provider: "caseops-authority-contextual-search-v1",
      generated_at: "2026-06-27T00:00:00Z",
      contextual_plan: {
        key_facts: ["cheque dishonour"],
        likely_issues: ["demand notice timing for cheque dishonour"],
        statutes_or_sections: ["Section 138 Negotiable Instruments Act"],
        procedural_posture: [],
        jurisdiction_hints: [],
        timing_signals: ["after 35 days"],
        planned_query:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
      coverage_notice: null,
      total_after_filter: 2,
      offset: 0,
      results: [
        {
          authority_document_id: "clean-cheque-138",
          title: "Cheque dishonour demand notice limitation under Section 138",
          court_name: "High Court of Delhi",
          forum_level: "high_court",
          document_type: "judgment",
          decision_date: "2026-05-01",
          case_reference: "CRL.A. 138/2026",
          bench_name: "Justice A. Rao",
          summary: "Readable authority on Section 138.",
          source: "test",
          source_reference: "https://official.example.test/cheque-138.pdf",
          snippet:
            "A cheque was dishonoured for insufficient funds. The court analysed Section 138 and Section 142 of the Negotiable Instruments Act.",
          score: 245,
          matched_terms: ["cheque", "notice", "section", "138"],
          relevance_reason: null,
          worst_treatment: null,
          adverse_count: 0,
        },
        {
          authority_document_id: "garbled-cheque-138",
          title: "Cheque dishonour Section 138 notice delay OCR damaged record",
          court_name: "High Court of Delhi",
          forum_level: "high_court",
          document_type: "judgment",
          decision_date: "2026-06-01",
          case_reference: "CRL.A. OCR/2026",
          bench_name: "Justice OCR Damaged",
          summary: "OCR damaged record.",
          source: "test",
          source_reference: "https://official.example.test/garbled.pdf",
          snippet:
            "Section 138 cheque notice insufficient funds after 35 days $O ?J '>2> 380 :J $)2J* J!'>) /=, +> +/2J?(=2>) :J ?( $!?( ! ?2J: 488 $O 477 .*J.:J.",
          score: 240,
          matched_terms: ["cheque", "notice", "section", "138"],
          relevance_reason: null,
          worst_treatment: null,
          adverse_count: 0,
        },
      ],
    });
    render(withClient(<ResearchPage />));

    fireEvent.click(screen.getByTestId("research-mode-contextual"));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: {
        value:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    expect(
      await screen.findByText(
        "Cheque dishonour demand notice limitation under Section 138",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Cheque dishonour Section 138 notice delay OCR damaged record",
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("research-result-garbled")).not.toBeInTheDocument();
  });

  it("omits an unreadable OCR-only authority card instead of rendering corrupted text", async () => {
    searchMock.mockResolvedValue({
      query:
        "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      mode: "contextual",
      provider: "caseops-authority-contextual-search-v1",
      generated_at: "2026-07-02T00:00:00Z",
      contextual_plan: {
        key_facts: ["cheque dishonour"],
        likely_issues: ["demand notice timing for cheque dishonour"],
        statutes_or_sections: ["Section 138 Negotiable Instruments Act"],
        procedural_posture: [],
        jurisdiction_hints: [],
        timing_signals: ["after 35 days"],
        planned_query:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
      coverage_notice:
        "Indexed authority records matched the query, but their extracted text is not readable enough to preview.",
      total_after_filter: 1,
      offset: 0,
      results: [
        {
          authority_document_id: "screenshot-garbled-cheque-138",
          title: "[2003] 3 -- f.t 'II'. 178",
          court_name: "Supreme Court of India",
          forum_level: "supreme_court",
          document_type: "judgment",
          decision_date: "2026-06-20",
          case_reference: "CRL.A. SCREEN/2026",
          bench_name: null,
          summary:
            "[2003] 3 -- f.t 'II'. 178, ; 3ffillllll mi aRT 'A III' 1Tfffi .mi -- aRT .. 12 -- d, 2002. lila l?1t. tt. 1950, 27 3TR 28 JTR.",
          source: "test",
          source_reference: "https://official.example.test/screenshot.pdf",
          snippet:
            "Section 138 cheque notice insufficient funds after 35 days. [2003] 3 -- f.t 'II'. 178, ; 3ffillllll mi aRT 'A III' 1Tfffi .mi -- aRT .. 12 -- d, 2002. lila l?1t. tt. 1950, 27 3TR 28 JTR. SIftIII'l cff. fcIrlTT ;ifo1l. C1>lx mt fl 4<1i fclr q1fiun'l llC1>lll1a fcIrq -- fl .wf. fcIrnl -- <ITT -j+t H.",
          score: 240,
          matched_terms: ["cheque", "notice", "section", "138"],
          relevance_reason:
            "Source-backed match on Section 138 Negotiable Instruments Act.",
          worst_treatment: null,
          adverse_count: 0,
        },
      ],
    });
    render(withClient(<ResearchPage />));

    fireEvent.click(screen.getByTestId("research-mode-contextual"));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: {
        value:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    expect(
      await screen.findByText(/Matching records were omitted/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\[2003\] 3 -- f\.t/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("research-result-garbled")).not.toBeInTheDocument();
  });

  it("does not render the removed Judgment Alerts submodule", () => {
    render(withClient(<ResearchPage />));

    expect(screen.queryByTestId("judgment-alert-center")).not.toBeInTheDocument();
    expect(screen.queryByText(/Judgment alerts/i)).not.toBeInTheDocument();
  });
});
