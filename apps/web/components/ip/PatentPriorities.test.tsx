import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PatentApplication, PatentPriority, PatentPriorityPage } from "@/lib/api/ip-patents";

const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), parents: vi.fn(), parent: vi.fn(),
  sources: vi.fn(), graph: vi.fn(), download: vi.fn(), document: vi.fn() }));
vi.mock("@/lib/api/ip-patents", async (original) => ({
  ...await original<typeof import("@/lib/api/ip-patents")>(), fetchPatentPriorities: mocks.list,
  createPatentPriority: mocks.create, fetchPatentApplications: mocks.parents,
  fetchPatentApplication: mocks.parent, fetchPatentFamilyGraph: mocks.graph,
}));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpDocumentsForDocket: mocks.sources,
  fetchIpDocument: mocks.document, downloadApiFile: mocks.download }));
import { PatentFamilyGraph, PatentPriorities } from "./PatentPriorities";

const id = (last: string) => `10000000-0000-4000-8000-00000000000${last}`;
const source = { kind: "document_version" as const, document_id: id("4"), document_version_id: id("5"), content_sha256: "a".repeat(64) };
const child: PatentApplication = {
  id: id("1"), docket_id: id("2"), family_id: id("3"), record_kind: "patent_application", version: 1,
  lifecycle_version: 0, lifecycle_status: "draft", is_active: true, prosecution_phase: "disclosure",
  created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z",
  facts: { title: "Child application", application_kind: "complete", jurisdiction: "IN", office: "IP India",
    filing_date: "2026-09-05", publication_date: null, identifiers: [], source_pending_identifier_allocation: true, source },
};
const parent: PatentApplication = { ...child, id: id("6"), docket_id: id("7"), facts: { ...child.facts, title: "Recorded parent" } };
const priority: PatentPriority = { id: id("8"), canonical_relationship_id: id("9"), application_id: child.id,
  parent_application_id: parent.id, current_application_title: child.facts.title, current_parent_title: parent.facts.title,
  sequence: 1, application_version: 1, parent_version: 1, lifecycle_version: 0, parent_lifecycle_version: 0,
  supersedes_priority_id: null, withdrawn: false, is_current: true, review_flags: [], relation_kind: "priority",
  priority_date: "2026-09-05", source, reason: "Original recorded priority evidence.", created_at: child.created_at };
const page: PatentPriorityPage = { application_id: child.id, collection_sequence: 1, priorities: [priority], next_cursor: null };
const corrected: PatentPriority = { ...priority, id: id("a"), sequence: 2, supersedes_priority_id: priority.id,
  reason: "Corrected source transcription." };
const key = ["ip", "patent-priorities", child.id, false, null, null];
function mount(record = child, graph = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}>{graph ? <PatentFamilyGraph familyId={record.family_id} />
    : <PatentPriorities record={record} canWrite onOpenDocuments={vi.fn()} />}</QueryClientProvider>);
  return client;
}
async function edit(name = "Correct relationship") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByRole("option", { name: "Signed source - version 1" });
  const save = screen.getByRole("button", { name: name === "Withdraw record" ? "Save withdrawal record" : "Save relationship" });
  await waitFor(() => expect(save).toBeEnabled());
  return screen.getByRole("form");
}

describe("Patent priorities and family graph", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.list.mockResolvedValue(page);
    mocks.parents.mockResolvedValue({ applications: [child, parent], next_cursor: null });
    mocks.parent.mockResolvedValue(parent);
    mocks.sources.mockResolvedValue({ items: [{ id: source.document_id, title: "Signed source",
      versions: [{ id: source.document_version_id, version: 1, sha256_hex: source.content_sha256 }] }], total: 1 });
    mocks.create.mockImplementation(async () => { mocks.list.mockResolvedValue({ ...page, collection_sequence: 2, priorities: [corrected] }); return corrected; });
    mocks.graph.mockResolvedValue({ family_id: child.family_id, applications: [child], priorities: [priority],
      applications_next_cursor: parent.id, priorities_next_cursor: "4:3", has_more_applications: true, has_more_relationships: true });
  });

  it("waits for authoritative discovery and hydrates exact retained fields", async () => {
    let resolve!: (value: PatentPriorityPage) => void;
    mocks.list.mockReturnValue(new Promise<PatentPriorityPage>((done) => { resolve = done; }));
    mount();
    expect(screen.getByRole("button", { name: "Add relationship" })).toBeDisabled();
    expect(mocks.parent).not.toHaveBeenCalled();
    await act(async () => resolve(page));
    const form = await edit();
    expect(within(form).getByLabelText("Parent application")).toHaveValue(parent.id);
    expect(within(form).getByLabelText("Recorded priority date")).toHaveValue(priority.priority_date);
    expect(within(form).getByLabelText("Relationship source version")).toHaveValue(source.document_version_id);
    expect(screen.queryByRole("option", { name: /Child application/ })).not.toBeInTheDocument();
  });

  it("preserves draft values and the original sequence through background discovery", async () => {
    const client = mount();
    const form = await edit();
    fireEvent.change(within(form).getByLabelText("Recorded priority date"), { target: { value: "2026-09-04" } });
    act(() => { client.setQueryData(key, { ...page, collection_sequence: 4 }); });
    expect(within(form).getByLabelText("Recorded priority date")).toHaveValue("2026-09-04");
    fireEvent.change(within(form).getByLabelText("Relationship change reason"), { target: { value: corrected.reason } });
    fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(child.id, {
      parent_application_id: parent.id, relation_kind: "priority", priority_date: "2026-09-04", source,
      reason: corrected.reason, withdrawn: false, expected_application_version: 1, expected_lifecycle_version: 0,
      expected_parent_version: 1, expected_parent_lifecycle_version: 0, expected_priority_sequence: 1,
      supersedes_priority_id: priority.id,
    }, expect.stringMatching(/^[a-f0-9-]{36}$/)));
  });

  it("cancels stale list responses before applying a confirmed correction", async () => {
    const client = mount();
    const form = await edit();
    let resolve!: (value: PatentPriorityPage) => void;
    let signal: AbortSignal | undefined;
    mocks.list.mockImplementationOnce((_id, _history, _continuation, value) => {
      signal = value; return new Promise<PatentPriorityPage>((done) => { resolve = done; });
    });
    act(() => { void client.invalidateQueries({ queryKey: key, exact: true }); });
    await waitFor(() => expect(signal).toBeDefined());
    fireEvent.change(within(form).getByLabelText("Relationship change reason"), { target: { value: corrected.reason } });
    fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }));
    await screen.findByText(corrected.reason);
    expect(signal!.aborted).toBe(true);
    await act(async () => resolve(page));
    expect(screen.getByText(corrected.reason)).toBeVisible();
    expect(screen.queryByText(priority.reason)).not.toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledOnce();
  });

  it("withdraws only the sourced relationship record and keeps closed parents readable", async () => {
    mocks.parent.mockResolvedValue({ ...parent, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    mocks.parents.mockResolvedValue({ applications: [], next_cursor: null });
    mount();
    const form = await edit("Withdraw record");
    expect(within(form).getByLabelText("Relationship type")).toBeDisabled();
    expect(within(form).getByLabelText("Recorded priority date")).toBeDisabled();
    expect(within(form).queryByLabelText("Parent application")).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Relationship change reason"), { target: { value: "Withdraw the incorrect recorded link." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save withdrawal record" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(child.id,
      expect.objectContaining({ withdrawn: true, supersedes_priority_id: priority.id, expected_parent_lifecycle_version: 1,
        parent_application_id: parent.id, priority_date: priority.priority_date }), expect.any(String)));
    expect(mocks.parents).not.toHaveBeenCalled();
  });

  it("fails closed on discovery, selected-parent, and source errors", async () => {
    mocks.list.mockRejectedValue(new Error("Access revoked"));
    const client = mount();
    await screen.findByText("Could not load priority records");
    expect(screen.getByRole("button", { name: "Add relationship" })).toBeDisabled();
    mocks.list.mockResolvedValue(page);
    act(() => { void client.invalidateQueries({ queryKey: key, exact: true }); });
    const button = await screen.findByRole("button", { name: "Correct relationship" });
    await waitFor(() => expect(button).toBeEnabled());
    mocks.parent.mockRejectedValue(new Error("Parent denied"));
    mocks.sources.mockRejectedValue(new Error("Source denied"));
    fireEvent.click(button);
    await screen.findByText("Selected parent is unavailable");
    await screen.findByText("Could not load relationship sources");
    expect(screen.getByRole("button", { name: "Save relationship" })).toBeDisabled();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("keeps terminal application history readable with no mutation controls", async () => {
    mocks.list.mockResolvedValue({ ...page, priorities: [{ ...priority, is_current: false, withdrawn: true }] });
    mount({ ...child, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    await screen.findByText("Withdrawn record");
    expect(screen.queryByRole("button", { name: "Add relationship" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct relationship" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download source version" })).toBeVisible();
  });

  it("uses independent graph cursors and displays off-page parent links without extra reads", async () => {
    mount(child, true);
    const links = await screen.findByRole("list", { name: "Family graph links" });
    expect(within(links).getByRole("link", { name: parent.facts.title })).toHaveAttribute("href", `/app/ip/patents/applications/${parent.id}`);
    expect(mocks.parents).not.toHaveBeenCalled();
    expect(mocks.parent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Next applications" }));
    await waitFor(() => expect(mocks.graph).toHaveBeenCalledWith(child.family_id, parent.id, undefined, expect.any(AbortSignal)));
    const older = await screen.findByRole("button", { name: "Older links" });
    await waitFor(() => expect(older).toBeEnabled());
    fireEvent.click(older);
    await waitFor(() => expect(mocks.graph).toHaveBeenCalledWith(child.family_id, parent.id, "4:3", expect.any(AbortSignal)));
  });
});
