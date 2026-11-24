import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ResearchAnswerRecord } from "@/lib/api/research-answers";

const { createMock, fetchMock, listMock, saveMock, capabilityMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  fetchMock: vi.fn(),
  listMock: vi.fn(),
  saveMock: vi.fn(),
  capabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/research-answers", async (load) => ({
  ...(await load<typeof import("@/lib/api/research-answers")>()),
  createResearchAnswer: createMock,
  fetchResearchAnswer: fetchMock,
  listResearchAnswers: listMock,
  saveResearchAnswerToMatter: saveMock,
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: (name: string) => capabilityMock(name) }));
vi.mock("@/components/app/MatterPicker", () => ({
  OPERATIONAL_MATTER_STATUSES: new Set(["active"]),
  MatterName: ({ matterId }: { matterId: string }) => <span>{matterId}</span>,
  MatterPicker: ({ value, onChange }: { value: string; onChange: (id: string) => void }) => (
    <input aria-label="Save to matter" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

import { ResearchAnswerPanel } from "./ResearchAnswerPanel";
import { ResearchAnswerView, researchAnswerToHtml, researchAnswerToText } from "./ResearchAnswerView";

const action = {
  state: "available" as const, label: "Open source", open_url: "https://official.example.test/138.pdf",
  source_reference: "https://official.example.test/138.pdf", reason: null, opens_new_tab: true,
  target_type: "authority_document" as const, target_id: "doc-1",
};

function answered(overrides: Partial<ResearchAnswerRecord> = {}): ResearchAnswerRecord {
  return {
    id: "ans-1",
    status: "answered",
    query: "Section 138 notice period and procedure?",
    error_code: null,
    message: null,
    analysis_version: "caseops-research-answer-v1-2026-11-24",
    created_at: "2026-11-24T10:00:00Z",
    completed_at: "2026-11-24T10:01:00Z",
    context_matter: null,
    saved_matter: null,
    saved_at: null,
    answer: {
      short_answer: { text: "A complaint lies once notice and payment periods pass [1][2].", citations: [1, 2], unsupported: false },
      key_points: [{ text: "Notice within thirty days of information [2].", citations: [2], unsupported: false }],
      facts_insufficient: true,
      missing_facts: ["Date the payee learnt of the dishonour."],
      assumptions: ["No payment has been made."],
      sections: [
        { key: "applicable_law", title: "Applicable law", paragraphs: [{ text: "Section 138 creates the offence [1].", citations: [1], unsupported: false }], steps: [], timeline: [] },
        { key: "time_limits", title: "Time limits and timeline", paragraphs: [], steps: [], timeline: [
          { period: "30 days", starts: "Information of dishonour", detail: { text: "Demand notice [2].", citations: [2], unsupported: false } },
        ] },
        { key: "ingredients", title: "Essential legal ingredients", paragraphs: [{ text: "A legally enforceable debt.", citations: [], unsupported: true }], steps: [], timeline: [] },
        { key: "procedure", title: "Procedure", paragraphs: [], steps: [{ text: "Send the demand notice [2].", citations: [2], unsupported: false }], timeline: [] },
      ],
      authorities: [
        { source: 1, disposition: "supporting", proposition: "Creates the offence.", relevance: "Governing provision.", passage: null, passage_verified: false, paragraph: null, cited_inline: true },
        { source: 2, disposition: "supporting", proposition: "Notice timing.", relevance: "Same facts.", passage: "held the notice must be issued within thirty days", passage_verified: true, paragraph: "14", cited_inline: true },
      ],
      matter_facts: [],
      verification: { removed_citation_markers: 1, unverified_passages: 0, uncited_paragraphs: 1, removed_unverified_mentions: 1, notes: ["1 passage(s) were withheld because they named a case that is not in the verified source set."] },
      law_checked_as_of: "2026-11-24",
      sources_retrieved_from: "2026-11-01T00:00:00Z",
      sources_retrieved_to: "2026-11-01T00:00:00Z",
      disclaimer: "Source-bounded research support, not legal advice.",
    },
    sources: [
      { number: 1, kind: "statute_section", id: "sec-138", title: "Section 138, Negotiable Instruments Act, 1881", citation: "NI Act, Section 138", court: null, bench: null, decision_date: null, weight: "Statutory provision (verified text)", source_action: { ...action, target_type: "statute_section", target_id: "sec-138" }, in_app_href: "/app/statutes/ni-act-1881/sections/Section%20138", treatment_signal: null, retrieved_at: null },
      { number: 2, kind: "judgment", id: "doc-1", title: "Cheque dishonour <notice> limitation", citation: "2026:DHC:1380", court: "High Court of Delhi", bench: "Justice A. Rao", decision_date: "2026-05-01", weight: "Binding within High Court of Delhi's jurisdiction; persuasive elsewhere", source_action: action, in_app_href: null, treatment_signal: { worst_treatment: "distinguished", adverse_count: 2 }, retrieved_at: "2026-11-01T00:00:00Z" },
    ],
    ...overrides,
  };
}

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ResearchAnswerView", () => {
  it("shows Short answer, then Detailed research, then Authorities, in that order", () => {
    render(<ResearchAnswerView record={answered()} />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(headings).toEqual(["Short answer", "Detailed research", "Relevant judicial authorities & sources"]);
    const sections = within(screen.getByTestId("research-detailed")).getAllByRole("heading", { level: 4 }).map((node) => node.textContent);
    expect(sections).toEqual(["1. Applicable law", "2. Time limits and timeline", "3. Essential legal ingredients", "4. Procedure"]);
    expect(screen.getByTestId("research-law-checked")).toHaveTextContent("Law checked as of");
    expect(screen.getByTestId("research-missing-facts")).toHaveTextContent("Date the payee learnt of the dishonour.");
    expect(screen.getByText("No source attached. Verify before relying.")).toBeVisible();
    expect(screen.getByTestId("research-verification-notes")).toHaveTextContent("withheld");
  });

  it("links every inline marker to the authority card and moves keyboard focus there", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(<ResearchAnswerView record={answered()} />);
    const markers = screen.getAllByTestId("research-citation-marker");
    const cards = screen.getAllByTestId("research-authority-card");
    const cardIds = new Set(cards.map((card) => `#${card.id}`));
    for (const marker of markers) expect(cardIds.has(marker.getAttribute("href") ?? "")).toBe(true);
    const short = within(screen.getByTestId("research-short-answer")).getAllByTestId("research-citation-marker");
    fireEvent.click(short[1]);
    expect(document.activeElement).toBe(cards[1]);
    fireEvent.click(within(cards[1]).getByRole("button", { name: "Back to the answer" }));
    expect(document.activeElement).toBe(short[1]);
  });

  it("shows record-owned authority identity, verified pinpoints and no inferred treatment", () => {
    render(<ResearchAnswerView record={answered()} />);
    const judgment = screen.getAllByTestId("research-authority-card")[1];
    expect(judgment).toHaveTextContent("2026:DHC:1380 · High Court of Delhi · Justice A. Rao");
    expect(judgment).toHaveTextContent("Para 14 (located in the source text)");
    expect(judgment).toHaveTextContent("Verified passage");
    expect(judgment).toHaveTextContent("Treatment history not verified.");
    expect(judgment).toHaveTextContent("2 citing judgment(s) may treat it adversely");
    const statute = screen.getAllByTestId("research-authority-card")[0];
    expect(within(statute).getByRole("link", { name: /Open section in CaseOps/ })).toHaveAttribute("target", "_blank");
  });

  it("exports Copy text and Download HTML in the same section order, escaped", () => {
    const record = answered();
    const text = researchAnswerToText(record);
    const order = ["A. SHORT ANSWER", "B. DETAILED RESEARCH", "C. RELEVANT JUDICIAL AUTHORITIES & SOURCES"].map((label) => text.indexOf(label));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(text).toContain("Paragraph: para 14");
    expect(text).toContain("[no source attached]");
    const html = researchAnswerToHtml(record);
    expect(html).toContain("&lt;notice&gt;");
    expect(html).not.toContain("<notice>");
    expect(html.indexOf("A. SHORT ANSWER")).toBeLessThan(html.indexOf("C. RELEVANT"));
  });
});

describe("ResearchAnswerPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    listMock.mockResolvedValue({ items: [] });
  });

  it("queues a question, polls until answered, then renders actions and the three parts", async () => {
    createMock.mockResolvedValue(answered({ status: "queued", answer: null, sources: [] }));
    fetchMock.mockResolvedValueOnce(answered({ status: "running", answer: null, sources: [] })).mockResolvedValue(answered());
    render(withClient(<ResearchAnswerPanel initialQuestion="" contextMatterId={null} />));
    fireEvent.change(screen.getByLabelText("Legal question"), { target: { value: "Section 138 notice period and procedure?" } });
    fireEvent.submit(screen.getByRole("form", { name: "Ask a research question" }));
    expect(await screen.findByTestId("research-answer-pending")).toBeVisible();
    await waitFor(() => expect(screen.getByTestId("research-answer")).toBeVisible(), { timeout: 6000 });
    expect(createMock).toHaveBeenCalledWith({ query: "Section 138 notice period and procedure?", contextMatterId: null });
    expect(screen.getByTestId("research-answer-actions")).toBeVisible();
  }, 10_000);

  it("explains an abstained answer instead of showing a model response", async () => {
    createMock.mockResolvedValue(answered({ status: "abstained", error_code: "no_sources", message: "CaseOps found no indexed statute section or judgment for this question.", answer: null, sources: [] }));
    render(withClient(<ResearchAnswerPanel initialQuestion="What is the limitation for an unindexed remedy?" contextMatterId={null} />));
    fireEvent.submit(screen.getByRole("form", { name: "Ask a research question" }));
    expect(await screen.findByTestId("research-answer-unavailable")).toHaveTextContent("found no indexed");
    expect(screen.queryByTestId("research-answer")).not.toBeInTheDocument();
  });

  it("saves an answered research record to the chosen matter", async () => {
    // The server echoes the launch matter as the answer's context matter.
    createMock.mockResolvedValue(answered({ context_matter: { id: "matter-9", title: "Cheque complaint" } }));
    saveMock.mockResolvedValue(answered({ saved_matter: { id: "matter-9", title: "Cheque complaint" }, saved_at: "2026-11-24T10:02:00Z" }));
    render(withClient(<ResearchAnswerPanel initialQuestion="Section 138 notice period and procedure?" contextMatterId="matter-9" />));
    expect(screen.getByTestId("research-context-matter")).toHaveTextContent("Matter documents are not read.");
    fireEvent.submit(screen.getByRole("form", { name: "Ask a research question" }));
    await screen.findByTestId("research-answer-actions");
    expect(screen.getByLabelText("Save to matter")).toHaveValue("matter-9");
    await act(async () => { fireEvent.submit(screen.getByRole("form", { name: "Save research to a matter" })); });
    expect(saveMock).toHaveBeenCalledWith("ans-1", "matter-9");
    expect(await screen.findByTestId("research-saved-matter")).toHaveTextContent("Cheque complaint");
  });

  it("does not offer generation to a role without the AI capability", () => {
    capabilityMock.mockImplementation((name: string) => name !== "recommendations:generate");
    render(withClient(<ResearchAnswerPanel initialQuestion="" contextMatterId={null} />));
    expect(screen.queryByRole("form", { name: "Ask a research question" })).not.toBeInTheDocument();
    expect(screen.getByText(/cannot generate AI research answers/)).toBeVisible();
  });
});
