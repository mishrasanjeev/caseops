import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PatentApplication } from "@/lib/api/ip-patents";
import type { PatentEvidence, PatentProsecutionPreview } from "@/lib/api/ip-patent-prosecution";

const mocks = vi.hoisted(() => ({ evidence: vi.fn(), events: vi.fn(), save: vi.fn(), preview: vi.fn(), commit: vi.fn(), sources: vi.fn() }));
vi.mock("@/lib/api/ip-patent-prosecution", async (original) => ({
  ...await original<typeof import("@/lib/api/ip-patent-prosecution")>(), fetchPatentEvidence: mocks.evidence,
  fetchPatentProsecution: mocks.events, createPatentEvidence: mocks.save,
  previewPatentProsecution: mocks.preview, createPatentProsecution: mocks.commit,
}));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpDocumentsForDocket: mocks.sources }));
vi.mock("@/components/ip/PatentSourceDownload", () => ({ PatentSourceDownload: () => <button>Download source version</button> }));
import { PatentProsecutionWorkspace } from "./PatentProsecutionWorkspace";

const id = (suffix: string) => `10000000-0000-4000-8000-00000000000${suffix}`;
const source = { kind: "document_version" as const, document_id: id("4"), document_version_id: id("5"), content_sha256: "a".repeat(64) };
const application: PatentApplication = {
  id: id("1"), docket_id: id("2"), family_id: id("3"), record_kind: "patent_application", version: 1,
  lifecycle_version: 0, lifecycle_status: "ready", is_active: true, prosecution_phase: "disclosure",
  created_at: "2026-09-09T00:00:00Z", updated_at: "2026-09-09T00:00:00Z",
  facts: { title: "Sourced patent", application_kind: "complete", jurisdiction: "IN", office: "IP India",
    filing_date: null, publication_date: null, identifiers: [], source, source_pending_identifier_allocation: true },
};
const edition: PatentEvidence = { id: id("6"), application_id: application.id, root_id: id("6"), predecessor_id: null,
  sequence: 1, edition: 1, is_current: true, anchor_version: 1, lifecycle_version: 0, title: "Filed claims",
  document_kind: "filing_package", source, documents: [{ document_kind: "claims", source }],
  manifest_sha256: "b".repeat(64), reason: "Preserve exact prepared claims.", created_at: application.created_at };
const page = { application_id: application.id, work_sequence: 1, records: [edition], next_cursor: null };
const preview: PatentProsecutionPreview = { application_id: application.id, work_sequence: 1, current_phase: "disclosure",
  proposed_phase: "examination", backdated: true, affected_deadline_ids: [],
  required_acknowledgements: ["backdated_recalculation_review_required", "exceptional_transition_review_required"],
  preview_sha256: "c".repeat(64), changes_deadlines: false, authoritative_calculation_available: false };
function mount(area: "evidence" | "prosecution" = "evidence", current = application) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(<QueryClientProvider client={client}><PatentProsecutionWorkspace application={current} area={area} canWrite onOpenDocuments={vi.fn()} /></QueryClientProvider>);
  return { client, ...result };
}

describe("Patent prosecution and immutable work product", () => {
  beforeEach(() => {
    vi.resetAllMocks(); mocks.evidence.mockResolvedValue(page);
    mocks.events.mockResolvedValue({ ...page, records: [] });
    mocks.sources.mockResolvedValue({ items: [{ id: source.document_id, title: "Source", versions: [{ id: source.document_version_id, version: 1, sha256_hex: source.content_sha256 }] }] });
    mocks.preview.mockResolvedValue(preview);
    mocks.save.mockImplementation(async () => { mocks.evidence.mockResolvedValue({ ...page, work_sequence: 2, records: [{ ...edition, title: "Saved edition" }] }); return edition; });
    mocks.commit.mockResolvedValue({});
  });

  it("waits for authoritative discovery and does not offer a blank create path on failure", async () => {
    let resolve!: (value: typeof page) => void;
    mocks.evidence.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    mount();
    expect(screen.queryByRole("button", { name: "Prepare edition" })).not.toBeInTheDocument();
    await act(async () => resolve(page));
    expect(await screen.findByRole("button", { name: "Prepare edition" })).toBeEnabled();
    expect(mocks.events).not.toHaveBeenCalled();
  });

  it("hydrates a retained edition and saves exact source versions without losing inputs", async () => {
    const { client } = mount();
    fireEvent.click(await screen.findByRole("button", { name: "New edition" }));
    const form = screen.getByRole("form", { name: "Prepare patent edition" });
    await waitFor(() => expect(within(form).getByLabelText("Source evidence")).toHaveValue(source.document_version_id));
    expect(within(form).getByLabelText("Edition title")).toHaveValue(edition.title);
    fireEvent.change(within(form).getByLabelText("Edition title"), { target: { value: "Saved edition" } });
    act(() => { client.setQueryData(["ip", "patent-work", application.id, "evidence", {}], { ...page, work_sequence: 8 }); });
    expect(within(form).getByLabelText("Edition title")).toHaveValue("Saved edition");
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Retain the old receipt and prepare a new version." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save edition" }));
    await screen.findByRole("heading", { name: "Saved edition" });
    expect(mocks.save).toHaveBeenCalledWith(application.id, expect.objectContaining({ expected_work_sequence: 1, predecessor_id: edition.id, source, documents: edition.documents }), expect.any(String));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Patent evidence saved.");
  });

  it("requires impact acknowledgement and invalidates a preview when evidence changes", async () => {
    mount("prosecution");
    fireEvent.click(await screen.findByRole("button", { name: "Record event" }));
    const form = screen.getByRole("form", { name: "Record patent event" });
    await waitFor(() => expect(within(form).getByLabelText("Source evidence")).toBeInTheDocument());
    fireEvent.change(within(form).getByLabelText("Source evidence"), { target: { value: source.document_version_id } });
    fireEvent.change(within(form).getByLabelText("Received date"), { target: { value: "2026-09-07" } });
    fireEvent.change(within(form).getByLabelText("Effective date"), { target: { value: "2026-09-06" } });
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Record the sourced office action." } });
    fireEvent.click(within(form).getByRole("button", { name: "Preview event" }));
    const commit = await screen.findByRole("button", { name: "Record reviewed event" });
    expect(commit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(commit).toBeEnabled();
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Changed source rationale." } });
    expect(screen.queryByRole("button", { name: "Record reviewed event" })).not.toBeInTheDocument();
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it("retains rejected input and does not emit a success state", async () => {
    mocks.save.mockRejectedValue(new Error("Source access revoked."));
    mount(); fireEvent.click(await screen.findByRole("button", { name: "New edition" }));
    const form = screen.getByRole("form", { name: "Prepare patent edition" });
    await waitFor(() => expect(within(form).getByRole("button", { name: "Save edition" })).toBeEnabled());
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Keep this rejected draft." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save edition" }));
    await screen.findByRole("alert");
    expect(within(form).getByLabelText("Reason")).toHaveValue("Keep this rejected draft.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(mocks.save).toHaveBeenCalledOnce();
  });

  it("preserves a hydrated draft across a failed background discovery read", async () => {
    const { client } = mount();
    fireEvent.click(await screen.findByRole("button", { name: "New edition" }));
    const form = screen.getByRole("form", { name: "Prepare patent edition" });
    fireEvent.change(within(form).getByLabelText("Edition title"), { target: { value: "Unsaved sourced amendment" } });
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Retain this work through an interrupted list read." } });
    mocks.evidence.mockRejectedValueOnce(new Error("List temporarily unavailable."));
    await act(async () => { await client.invalidateQueries({ queryKey: ["ip", "patent-work", application.id] }); });
    await screen.findByText("Could not load patent work", { exact: true });
    expect(screen.getByRole("form", { name: "Prepare patent edition" })).toBeVisible();
    expect(screen.getByLabelText("Edition title")).toHaveValue("Unsaved sourced amendment");
    expect(within(screen.getByRole("form", { name: "Prepare patent edition" })).getByLabelText("Reason")).toHaveValue("Retain this work through an interrupted list read.");
    expect(mocks.save).not.toHaveBeenCalled();
  });

  it("keeps closed evidence readable without commands", async () => {
    mount("evidence", { ...application, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    await screen.findByRole("heading", { name: edition.title });
    expect(screen.getByRole("button", { name: "Download source version" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "New edition" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare edition" })).not.toBeInTheDocument();
  });
});
