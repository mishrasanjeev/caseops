import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  statsMock,
  searchMock,
  rulesMock,
  alertsMock,
  digestMock,
  createRuleMock,
  runRuleMock,
  updateAlertMock,
  updateRuleMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  statsMock: vi.fn(),
  searchMock: vi.fn(),
  rulesMock: vi.fn(),
  alertsMock: vi.fn(),
  digestMock: vi.fn(),
  createRuleMock: vi.fn(),
  runRuleMock: vi.fn(),
  updateAlertMock: vi.fn(),
  updateRuleMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAuthorityCorpusStats: statsMock,
  searchAuthorities: searchMock,
  createAuthorityAnnotation: vi.fn(),
  listJudgmentAlertRules: rulesMock,
  listJudgmentAlerts: alertsMock,
  fetchJudgmentAlertDigestPreview: digestMock,
  createJudgmentAlertRule: createRuleMock,
  runJudgmentAlertRule: runRuleMock,
  updateJudgmentAlert: updateAlertMock,
  updateJudgmentAlertRule: updateRuleMock,
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
    rulesMock.mockReset();
    alertsMock.mockReset();
    digestMock.mockReset();
    createRuleMock.mockReset();
    runRuleMock.mockReset();
    updateAlertMock.mockReset();
    updateRuleMock.mockReset();
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
    rulesMock.mockResolvedValue({
      rules: [
        {
          id: "rule-1",
          company_id: "company-1",
          name: "Cheque dishonour watch",
          query_terms: ["cheque dishonour"],
          court_name: null,
          forum_level: null,
          judge_name: null,
          practice_area: null,
          statute_terms: ["Section 138"],
          document_types: ["judgment", "order"],
          since_date: null,
          until_date: null,
          is_archived: false,
          created_by_membership_id: "member-1",
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
          archived_at: null,
        },
      ],
    });
    alertsMock.mockResolvedValue({
      alerts: [
        {
          id: "alert-1",
          company_id: "company-1",
          rule_id: "rule-1",
          is_read: false,
          read_at: null,
          dismissed_at: null,
          created_at: "2026-05-24T00:00:00Z",
          authority: {
            authority_document_id: "auth-1",
            title: "Section 138 cheque dishonour notice delay judgment",
            court_name: "High Court of Delhi",
            forum_level: "high_court",
            document_type: "judgment",
            citation_reference: "2026:DHC:1717",
            decision_date: "2026-05-17",
            match_reason:
              "Matched saved query terms against existing authority metadata.",
            source: "test-source",
            source_reference: "https://official.example.test/adp17-cheque.pdf",
            snippet: "Bounded source-backed summary under 280 chars.",
          },
        },
      ],
    });
    digestMock.mockResolvedValue({
      generated_at: "2026-05-24T00:00:00Z",
      unread_count: 1,
      dismissed_count: 0,
      alerts: [],
      delivery_status: "in_app_only",
      delivery_note:
        "In-app preview only. External delivery is not configured in this foundation.",
    });
    createRuleMock.mockResolvedValue({
      id: "rule-2",
      company_id: "company-1",
      name: "New watch",
      query_terms: ["limitation"],
      court_name: null,
      forum_level: null,
      judge_name: null,
      practice_area: null,
      statute_terms: [],
      document_types: ["judgment", "order"],
      since_date: null,
      until_date: null,
      is_archived: false,
      created_by_membership_id: "member-1",
      created_at: "2026-05-24T00:00:00Z",
      updated_at: "2026-05-24T00:00:00Z",
      archived_at: null,
    });
    runRuleMock.mockResolvedValue({
      rule_id: "rule-1",
      preview_only: false,
      matched_count: 1,
      created_count: 1,
      matches: [],
      delivery_status: "in_app_only",
    });
    updateAlertMock.mockResolvedValue({
      id: "alert-1",
      company_id: "company-1",
      rule_id: "rule-1",
      is_read: true,
      read_at: "2026-05-24T00:01:00Z",
      dismissed_at: null,
      created_at: "2026-05-24T00:00:00Z",
      authority: {
        authority_document_id: "auth-1",
        title: "Section 138 cheque dishonour notice delay judgment",
        court_name: "High Court of Delhi",
        forum_level: "high_court",
        document_type: "judgment",
        citation_reference: "2026:DHC:1717",
        decision_date: "2026-05-17",
        match_reason:
          "Matched saved query terms against existing authority metadata.",
        source: "test-source",
        source_reference: "https://official.example.test/adp17-cheque.pdf",
        snippet: "Bounded source-backed summary under 280 chars.",
      },
    });
    updateRuleMock.mockResolvedValue({
      id: "rule-1",
      company_id: "company-1",
      name: "Cheque dishonour watch",
      query_terms: ["cheque dishonour"],
      court_name: null,
      forum_level: null,
      judge_name: null,
      practice_area: null,
      statute_terms: ["Section 138"],
      document_types: ["judgment", "order"],
      since_date: null,
      until_date: null,
      is_archived: true,
      created_by_membership_id: "member-1",
      created_at: "2026-05-24T00:00:00Z",
      updated_at: "2026-05-24T00:00:00Z",
      archived_at: "2026-05-24T00:02:00Z",
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

  it("supports in-app judgment alert rules and alert actions", async () => {
    render(withClient(<ResearchPage />));

    await waitFor(() => {
      expect(screen.getByTestId("judgment-alert-center")).toBeInTheDocument();
    });
    expect(screen.getByText("In-app only")).toBeInTheDocument();
    expect(
      screen.getAllByText(/External delivery is not configured/i).length,
    ).toBeGreaterThan(0);

    fireEvent.change(screen.getByTestId("judgment-alert-name"), {
      target: { value: "Limitation watch" },
    });
    fireEvent.change(screen.getByTestId("judgment-alert-terms"), {
      target: { value: "limitation, Section 138" },
    });
    fireEvent.click(screen.getByTestId("judgment-alert-create"));

    await waitFor(() => {
      expect(createRuleMock).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Limitation watch",
          query_terms: ["limitation", "Section 138"],
          document_types: ["judgment", "order"],
        }),
      );
    });

    fireEvent.click(screen.getByTestId("judgment-alert-run-rule-1"));
    await waitFor(() => {
      expect(runRuleMock).toHaveBeenCalledWith(
        expect.objectContaining({ ruleId: "rule-1", previewOnly: false }),
      );
    });

    fireEvent.click(screen.getByTestId("judgment-alert-read-alert-1"));
    await waitFor(() => {
      expect(updateAlertMock).toHaveBeenCalledWith({
        alertId: "alert-1",
        action: "read",
      });
    });
  });
});
