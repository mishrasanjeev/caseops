import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  statsMock,
  searchMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  statsMock: vi.fn(),
  searchMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAuthorityCorpusStats: statsMock,
  searchAuthorities: searchMock,
  createAuthorityAnnotation: vi.fn(),
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
    });
  });

  it("renders the research query input and submit button", () => {
    render(withClient(<ResearchPage />));
    expect(screen.getByTestId("research-query-input")).toBeInTheDocument();
    expect(screen.getByTestId("research-query-submit")).toBeInTheDocument();
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

  it("does not render the removed Judgment Alerts submodule", () => {
    render(withClient(<ResearchPage />));

    expect(screen.queryByTestId("judgment-alert-center")).not.toBeInTheDocument();
    expect(screen.queryByText(/Judgment alerts/i)).not.toBeInTheDocument();
  });
});
