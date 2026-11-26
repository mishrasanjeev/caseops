import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "ans-1" }) }));
vi.mock("@/components/app/MatterPicker", () => ({
  OPERATIONAL_MATTER_STATUSES: new Set(["active"]),
  MatterName: ({ matterId }: { matterId: string }) => <span>{matterId}</span>,
  MatterPicker: ({ value, onChange }: { value: string; onChange: (id: string) => void }) => (
    <input aria-label="Save to matter" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

import ResearchAnswerPage from "@/app/app/research/answers/[id]/page";

import { ResearchAnswerPanel, ResearchAnswerStatus } from "./ResearchAnswerPanel";
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
      question_focus: [],
      coverage_gaps: [],
      verification: { removed_citation_markers: 1, unverified_passages: 0, uncited_paragraphs: 1, removed_unverified_mentions: 1, unlinked_authorities: 0, notes: ["1 passage(s) were withheld because they named a case that is not in the verified source set."] },
      law_checked_as_of: "2026-11-24",
      sources_retrieved_from: "2026-11-01T00:00:00Z",
      sources_retrieved_to: "2026-11-01T00:00:00Z",
      disclaimer: "Source-bounded research support, not legal advice.",
    },
    sources: [
      { number: 1, kind: "statute_section", id: "sec-138", title: "Section 138, Negotiable Instruments Act, 1881", citation: "NI Act, Section 138", court: null, bench: null, decision_date: null, weight: "Statutory provision (verified text)", source_action: { ...action, target_type: "statute_section", target_id: "sec-138" }, in_app_href: "/app/statutes/ni-act-1881/sections/Section%20138", treatment_signal: null, retrieved_at: null },
      { number: 2, kind: "judgment", id: "doc-1", title: "Cheque dishonour <notice> limitation", citation: "2026:DHC:1380", court: "High Court of Delhi", bench: "Justice A. Rao", decision_date: "2026-05-01", weight: "Binding within High Court of Delhi's jurisdiction; persuasive elsewhere", source_action: action, in_app_href: null, treatment_signal: { worst_treatment: "distinguished", adverse_count: 2 }, retrieved_at: "2026-11-01T00:00:00Z" },
    ],
    suggestions: [],
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
    // The Short Answer comes before every action control.
    const short = screen.getByTestId("research-short-answer");
    const actions = screen.getByTestId("research-answer-actions");
    expect(short.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

// BUG-001 (Ram, 2026-11-26): the answer page put each block under its own
// width cap (65ch of three font sizes, max-w-3xl, none), so the document
// hugged the left of an uncapped <main> with ragged right edges.
describe("research answer layout contract", () => {
  const record = () => {
    const base = answered();
    return answered({
      answer: { ...base.answer!, matter_facts: [{ label: "Cheque amount", value: "Rs 5 lakh" }] },
    });
  };
  const classes = (element: Element) => (element.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
  const cappedIn = (root: Element) => [...root.querySelectorAll("[class]")]
    .filter((element) => classes(element).some((name) => name.startsWith("max-w-")))
    .map((element) => `${element.tagName.toLowerCase()}.${classes(element).join(".")}`);

  it("sets no per-block width cap inside the document, so every block shares the column's edges", () => {
    const { container } = render(<ResearchAnswerView record={record()} />);
    expect(cappedIn(container)).toEqual([]);
  });

  it("spaces parts, blocks and lines with one gap scale and no vertical sibling margins", () => {
    const { container } = render(<ResearchAnswerView record={record()} />);
    const article = screen.getByTestId("research-answer");
    expect(article).toHaveClass("flex", "flex-col", "gap-8");
    for (const id of ["research-short-answer", "research-detailed", "research-authorities"]) {
      const part = screen.getByTestId(id);
      expect(part.parentElement).toBe(article);
      expect(part).toHaveClass("flex", "flex-col", "gap-4");
    }
    for (const section of ["applicable_law", "time_limits", "ingredients", "procedure"]) {
      expect(screen.getByTestId(`research-section-${section}`)).toHaveClass("flex", "flex-col", "gap-2");
    }
    expect(screen.getAllByTestId("research-authority-card")[0].parentElement).toHaveClass("flex", "flex-col", "gap-4");
    const margins = [...container.querySelectorAll("[class]")]
      .flatMap((element) => classes(element).filter((name) => /^-?m[tby]-/.test(name)));
    expect(margins).toEqual([]);
  });

  it("gives part headings, numbered sub-sections and authority titles three distinct sizes", () => {
    render(<ResearchAnswerView record={record()} />);
    const size = (element: Element) => classes(element).filter((name) => /^text-(xs|sm|base|lg|xl|2xl)$/.test(name)).join();
    const parts = screen.getAllByRole("heading", { level: 3 });
    const subSections = within(screen.getByTestId("research-detailed")).getAllByRole("heading", { level: 4 });
    const authorityTitles = within(screen.getByTestId("research-authorities")).getAllByRole("heading", { level: 4 });
    expect(new Set(parts.map(size))).toEqual(new Set(["text-xl"]));
    expect(new Set(subSections.map(size))).toEqual(new Set(["text-base"]));
    expect(new Set(authorityTitles.map(size))).toEqual(new Set(["text-sm"]));
  });

  it("renders the permanent page's header, document and actions inside one reading column", async () => {
    capabilityMock.mockReturnValue(true);
    fetchMock.mockResolvedValue(record());
    render(withClient(<ResearchAnswerPage />));
    const column = await screen.findByTestId("research-answer-column");
    await waitFor(() => expect(within(column).getByTestId("research-answer")).toBeVisible());
    expect(column).toHaveClass("mx-auto", "w-full", "max-w-[70ch]", "flex", "flex-col", "gap-8");
    expect(within(column).getByRole("heading", { level: 1, name: "Research answer" })).toBeVisible();
    expect(within(column).getByTestId("research-answer-actions")).toBeVisible();
    expect(cappedIn(within(column).getByTestId("research-answer"))).toEqual([]);
    expect(cappedIn(within(column).getByTestId("research-answer-actions"))).toEqual([]);
  });

  it("renders the answer below the question card on /app/research, never as a card inside the card", async () => {
    capabilityMock.mockReturnValue(true);
    listMock.mockResolvedValue({ items: [] });
    createMock.mockResolvedValue(record());
    render(withClient(<ResearchAnswerPanel initialQuestion="Section 138 notice period and procedure?" contextMatterId={null} />));
    fireEvent.submit(screen.getByRole("form", { name: "Ask a research question" }));
    const document = await screen.findByTestId("research-answer");
    const card = screen.getByTestId("research-answer-panel");
    expect(card).not.toContainElement(document);
    expect(card).not.toContainElement(screen.getByTestId("research-answer-actions"));
    const column = screen.getByTestId("research-answer-column");
    expect(column).toContainElement(document);
    expect(column).toHaveClass("mx-auto", "max-w-[70ch]");
  });
});

// BUG-003 (Ram, 2026-11-26): a pending answer must say what it is doing, for
// how long, and what to expect, and survive leaving the page and coming back.
describe("ResearchAnswerStatus pending state", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts mm:ss from the record's creation time, names the step and sets the expectation", () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-11-24T10:01:05Z"));
    const running = answered({ status: "running", answer: null, sources: [] });
    const first = render(<ResearchAnswerStatus record={running} />);
    expect(screen.getByTestId("research-answer-elapsed")).toHaveTextContent("01:05");
    expect(screen.getByTestId("research-answer-step")).toHaveTextContent("Retrieving statutes and judgments");
    expect(screen.getByTestId("research-answer-expectation")).toHaveTextContent("Research answers usually take one to two minutes.");
    expect(screen.getByRole("link", { name: "its permanent link" })).toHaveAttribute("href", "/app/research/answers/ans-1");
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(screen.getByTestId("research-answer-elapsed")).toHaveTextContent("01:08");
    first.unmount();

    // Navigating away and back mounts a new component: the count still
    // comes from created_at, not from the new mount.
    vi.setSystemTime(new Date("2026-11-24T10:03:30Z"));
    render(<ResearchAnswerStatus record={running} onPermalinkPage />);
    expect(screen.getByTestId("research-answer-elapsed")).toHaveTextContent("03:30");
    expect(screen.getByTestId("research-answer-expectation")).toHaveTextContent("taking longer than usual");
    expect(screen.queryByRole("link", { name: "its permanent link" })).not.toBeInTheDocument();
  });

  it("reads an API timestamp without a zone as UTC and names the queued step", () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-11-24T10:00:42Z"));
    render(<ResearchAnswerStatus record={answered({ status: "queued", answer: null, sources: [], created_at: "2026-11-24T10:00:00.123456" })} />);
    expect(screen.getByTestId("research-answer-elapsed")).toHaveTextContent("00:41");
    expect(screen.getByTestId("research-answer-step")).toHaveTextContent("Queued");
  });
});

describe("Nov 26 focus, coverage and abstention guidance", () => {
  it("shows what the question was researched as and what the sources did not cover", () => {
    const record = answered();
    record.answer!.question_focus = ["Section 138, Negotiable Instruments Act, 1881"];
    record.answer!.coverage_gaps = ["Territorial jurisdiction is not addressed by the retrieved sources."];
    render(<ResearchAnswerView record={record} />);
    expect(screen.getByTestId("research-question-focus")).toHaveTextContent(
      "Researched as: Section 138, Negotiable Instruments Act, 1881",
    );
    expect(screen.getByTestId("research-coverage-gaps")).toHaveTextContent("Territorial jurisdiction");
    const text = researchAnswerToText(record);
    expect(text).toContain("Researched as: Section 138, Negotiable Instruments Act, 1881");
    expect(text).toContain("Not covered by the retrieved sources:");
  });

  it("turns an abstention into usable next questions that fill the question box", () => {
    const onUse = vi.fn();
    const suggestion = "What are the essential ingredients, time limits and procedure under Section 9, Arbitration and Conciliation Act, 1996?";
    const record = answered({
      status: "abstained", error_code: "needs_detail", answer: null, sources: [],
      message: "CaseOps could not tell which law this question is about. Name the Act and section.",
      suggestions: [suggestion],
    });
    render(<ResearchAnswerStatus record={record} onUseSuggestion={onUse} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Name the Act and section");
    fireEvent.click(screen.getByRole("button", { name: /Section 9, Arbitration/ }));
    expect(onUse).toHaveBeenCalledWith(suggestion);
  });

  it("links suggestions back to Research with the matter on the permanent page", () => {
    const record = answered({
      status: "abstained", error_code: "no_sources", answer: null, sources: [],
      context_matter: { id: "m-1", title: "Supplier cheque complaint" },
      message: "No verified source.", suggestions: ["How does Section 9 apply?"],
    });
    render(<ResearchAnswerStatus record={record} onPermalinkPage />);
    expect(screen.getByRole("link", { name: "How does Section 9 apply?" })).toHaveAttribute(
      "href", "/app/research?tab=answer&q=How%20does%20Section%209%20apply%3F&matter=m-1",
    );
  });
});
