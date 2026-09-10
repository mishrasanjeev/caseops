import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PatentApplication } from "@/lib/api/ip-patents";
import type { PatentProceeding } from "@/lib/api/ip-patent-proceedings";

const mocks = vi.hoisted(() => ({ list: vi.fn(), history: vi.fn(), create: vi.fn(), preview: vi.fn(), transition: vi.fn(), sources: vi.fn(), evidence: vi.fn() }));
vi.mock("@/lib/api/ip-patent-proceedings", async (original) => ({
  ...await original<typeof import("@/lib/api/ip-patent-proceedings")>(), fetchPatentProceedings: mocks.list,
  fetchPatentProceedingHistory: mocks.history, createPatentProceeding: mocks.create,
  previewPatentProceeding: mocks.preview, transitionPatentProceeding: mocks.transition,
}));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpDocumentsForDocket: mocks.sources }));
vi.mock("@/lib/api/ip-patent-prosecution", async (original) => ({ ...await original<typeof import("@/lib/api/ip-patent-prosecution")>(), fetchPatentEvidence: mocks.evidence }));
vi.mock("@/components/ip/PatentSourceDownload", () => ({ PatentSourceDownload: () => <button>Download source version</button> }));
import { patentProceedingHistorySchema, patentProceedingSchema } from "@/lib/api/ip-patent-proceedings";
import { PatentProceedingsWorkspace } from "./PatentProceedingsWorkspace";

const id = (suffix: string) => `10000000-0000-4000-8000-00000000000${suffix}`;
const source = { kind: "document_version" as const, document_id: id("4"), document_version_id: id("5"), content_sha256: "a".repeat(64) };
const application: PatentApplication = {
  id: id("1"), docket_id: id("2"), family_id: id("3"), record_kind: "patent_application", version: 1,
  lifecycle_version: 0, lifecycle_status: "ready", is_active: true, prosecution_phase: "filed",
  created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z",
  facts: { title: "Sourced patent", application_kind: "complete", jurisdiction: "IN", office: "IP India",
    filing_date: null, publication_date: null, identifiers: [], source, source_pending_identifier_allocation: true },
};
const record: PatentProceeding = { id: id("6"), application_id: application.id, docket_id: application.docket_id,
  proceeding_kind: "patent_pre_grant_opposition", title: "Separate pre-grant opposition", counterparty: "Example Research",
  side: "applicant", office: "IP India", jurisdiction: "IN", version: 1, stage: "notice_recorded",
  lifecycle_version: 0, operational: true, allowed_stages: ["response_preparation", "withdrawn"],
  latest: { id: id("7"), revision: 1, sequence: 1, anchor_version: 1, lifecycle_version: 0,
    before_stage: null, after_stage: "notice_recorded", source, received_on: "2026-09-10", effective_on: "2026-09-10",
    proceeding_number: null, evidence_id: null, reason: "Record the supplied notice.", outcome: null,
    exceptional_transition_reason: null, impact: null, created_at: application.created_at } };
const page = { application_id: application.id, work_sequence: 1, records: [record], next_cursor: null };
const history = { proceeding: record, events: [record.latest] };
const impact = { proceeding_id: record.id, current_stage: "notice_recorded", proposed_stage: "response_preparation",
  required_acknowledgements: [], preview_sha256: "b".repeat(64), changes_application_phase: false, changes_deadlines: false };
function mount(current = application) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(<QueryClientProvider client={client}><PatentProceedingsWorkspace application={current} canWrite onOpenDocuments={vi.fn()} /></QueryClientProvider>);
  return { client, ...result };
}
async function fill(form: HTMLElement) {
  await waitFor(() => expect(within(form).getByRole("option", { name: "Source - version 1" })).toBeInTheDocument());
  fireEvent.change(within(form).getByLabelText("Proceeding source"), { target: { value: source.document_version_id } });
  fireEvent.change(within(form).getByLabelText("Received date"), { target: { value: "2026-09-10" } });
  fireEvent.change(within(form).getByLabelText("Effective date"), { target: { value: "2026-09-10" } });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Retain this exact opposition source." } });
}
async function edit() {
  fireEvent.click(await screen.findByRole("button", { name: /Separate pre-grant opposition/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Update proceeding" }));
  const form = screen.getByRole("form", { name: "Update patent proceeding" });
  await fill(form);
  return form;
}

describe("Concrete patent pre-grant proceeding workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks(); mocks.list.mockResolvedValue(page); mocks.history.mockResolvedValue(history);
    mocks.sources.mockResolvedValue({ items: [{ id: source.document_id, title: "Source", versions: [{ id: source.document_version_id, version: 1, sha256_hex: source.content_sha256 }] }] });
    mocks.evidence.mockResolvedValue({ ...page, records: [] }); mocks.preview.mockResolvedValue(impact);
    mocks.create.mockImplementation(async () => { mocks.list.mockResolvedValue(page); return record; });
    mocks.transition.mockImplementation(async () => {
      const saved: PatentProceeding = { ...record, version: 2, stage: "response_preparation", latest: { ...record.latest,
        id: id("8"), revision: 2, sequence: 2, before_stage: "notice_recorded", after_stage: "response_preparation" } };
      mocks.list.mockResolvedValue({ ...page, work_sequence: 2, records: [saved] });
      mocks.history.mockResolvedValue({ proceeding: saved, events: [record.latest, saved.latest] }); return saved;
    });
  });

  it("waits for discovery and denies create on failed discovery", async () => {
    let reject!: (error: Error) => void;
    mocks.list.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    mount(); expect(screen.queryByRole("button", { name: "New pre-grant opposition" })).not.toBeInTheDocument();
    await act(async () => reject(new Error("Discovery unavailable")));
    await screen.findByText("Could not load proceedings", { exact: true });
    expect(screen.queryByRole("button", { name: "New pre-grant opposition" })).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("creates a separate sourced identity and shows success without error feedback", async () => {
    mocks.list.mockResolvedValue({ ...page, work_sequence: 0, records: [] }); mount();
    fireEvent.click(await screen.findByRole("button", { name: "New pre-grant opposition" }));
    const form = screen.getByRole("form", { name: "New patent proceeding" }); await fill(form);
    fireEvent.change(within(form).getByLabelText("Proceeding title"), { target: { value: record.title } });
    fireEvent.change(within(form).getByLabelText("Counterparty"), { target: { value: record.counterparty } });
    fireEvent.click(within(form).getByRole("button", { name: "Save proceeding" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Patent proceeding saved.");
    expect(await screen.findByRole("heading", { name: record.title })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledWith(application.id, expect.objectContaining({
      source, proceeding_kind: "patent_pre_grant_opposition", expected_work_sequence: 0,
      source_pending_identifier_allocation: true, proceeding_number: null }), expect.any(String));
  });

  it("hydrates before editing and retains drafts plus original tokens across background errors", async () => {
    const { client } = mount(); const form = await edit();
    mocks.list.mockRejectedValueOnce(new Error("Interrupted list read"));
    await act(async () => { await client.invalidateQueries({ queryKey: ["ip", "patent-proceedings", application.id, "list"] }); });
    expect(within(form).getByLabelText("Reason")).toHaveValue("Retain this exact opposition source.");
    act(() => { client.setQueryData(["ip", "patent-proceedings", application.id, "list", {}], { ...page, work_sequence: 19 }); });
    fireEvent.click(within(form).getByRole("button", { name: "Preview stage" }));
    await screen.findByRole("button", { name: "Record reviewed stage" });
    expect(mocks.preview).toHaveBeenCalledWith(application.id, record.id, expect.objectContaining({ expected_work_sequence: 1, expected_proceeding_version: 1 }));
  });

  it("requires exceptional acknowledgement and invalidates changed previews", async () => {
    mocks.preview.mockResolvedValue({ ...impact, required_acknowledgements: ["backdated_source_review", "exceptional_stage_review"] });
    mount(); const form = await edit(); fireEvent.click(within(form).getByRole("button", { name: "Preview stage" }));
    const save = await screen.findByRole("button", { name: "Record reviewed stage" }); expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox")); expect(save).toBeEnabled();
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Changed source rationale." } });
    expect(screen.queryByRole("button", { name: "Record reviewed stage" })).not.toBeInTheDocument();
    expect(mocks.transition).not.toHaveBeenCalled();
  });

  it("persists the reviewed stage with exact source and no error feedback", async () => {
    mount(); const form = await edit(); fireEvent.click(within(form).getByRole("button", { name: "Preview stage" }));
    fireEvent.click(await screen.findByRole("button", { name: "Record reviewed stage" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Patent proceeding saved.");
    expect(await screen.findByRole("heading", { name: "response preparation" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.transition).toHaveBeenCalledWith(application.id, record.id, expect.objectContaining({ source, preview_sha256: impact.preview_sha256 }), expect.any(String));
  });

  it("retains rejected stage input and immutable history without success", async () => {
    mocks.transition.mockRejectedValue(new Error("Source access revoked")); mount(); const form = await edit();
    fireEvent.click(within(form).getByRole("button", { name: "Preview stage" }));
    fireEvent.click(await screen.findByRole("button", { name: "Record reviewed stage" }));
    await screen.findByRole("alert");
    expect(within(form).getByLabelText("Reason")).toHaveValue("Retain this exact opposition source.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Proceeding stage history" })).getAllByRole("listitem")).toHaveLength(1);
  });

  it("retains terminal history without reopening or transition actions", async () => {
    mocks.history.mockResolvedValue({ ...history, proceeding: { ...record, operational: false, allowed_stages: [] } });
    mount({ ...application, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    fireEvent.click(await screen.findByRole("button", { name: /Separate pre-grant opposition/ }));
    expect(await screen.findByText("Read-only proceeding")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download source version" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update proceeding" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New pre-grant opposition" })).not.toBeInTheDocument();
  });

  it("validates the complete canonical nested contract and rejects unknown domain or source fields", () => {
    expect(patentProceedingHistorySchema.parse(history)).toEqual(history);
    expect(patentProceedingSchema.safeParse({ ...record, proceeding_kind: "opposition" }).success).toBe(false);
    expect(patentProceedingSchema.safeParse({ ...record, latest: { ...record.latest, source: { ...source, invented: true } } }).success).toBe(false);
    expect(patentProceedingSchema.safeParse({ ...record, latest: { ...record.latest, impact: { ...impact, changes_deadlines: true } } }).success).toBe(false);
  });
});
