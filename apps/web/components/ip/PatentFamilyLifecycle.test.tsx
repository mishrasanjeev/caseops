import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ history: vi.fn(), applicationHistory: vi.fn(), preview: vi.fn(), transition: vi.fn() }));
vi.mock("@/lib/api/ip-patents", () => ({ fetchPatentFamilyLifecycleHistory: mocks.history, fetchPatentApplicationLifecycleHistory: mocks.applicationHistory }));
vi.mock("@/lib/api/endpoints", () => ({ previewIpDocketLifecycle: mocks.preview, transitionIpDocketLifecycle: mocks.transition }));
import type { PatentApplication, PatentFamily } from "@/lib/api/ip-patents";
import { PatentFamilyLifecycle, PatentRecordLifecycle } from "./PatentFamilyLifecycle";

const family: PatentFamily = {
  id: "00000000-0000-4000-8000-000000000001", docket_id: "00000000-0000-4000-8000-000000000002",
  asset_id: "00000000-0000-4000-8000-000000000003", record_kind: "patent_family",
  version: 2, lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
  created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
  facts: { title: "Restricted disclosure", client_id: "00000000-0000-4000-8000-000000000004",
    disclosure_date: "2026-09-05", disclosure_narrative: "Original facts.", confidentiality: "restricted", source: null },
};
const review = {
  docket_id: family.docket_id, from_status: "draft", to_status: "closed", expected_lifecycle_version: 0,
  impacts: [], blocker_codes: [], requires_exception_acknowledgement: false, reopen_without_child_resurrection: false,
};
function mount(record = family, canReview = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["ip", "patent-family", family.id], record);
  const result = render(<QueryClientProvider client={client}><PatentFamilyLifecycle family={record} canReview={canReview} /></QueryClientProvider>);
  return { client, rerender: (next: PatentFamily) => result.rerender(<QueryClientProvider client={client}><PatentFamilyLifecycle family={next} canReview={canReview} /></QueryClientProvider>) };
}
async function preview() {
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Client instructed closure." } });
  fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "Closed on instruction" } });
  fireEvent.change(screen.getByLabelText("Instruction or evidence reference"), { target: { value: "instruction:original" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview lifecycle change" }));
  await screen.findByLabelText("Lifecycle impact review");
}

describe("Patent family lifecycle", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.history.mockResolvedValue({ events: [], next_cursor: null });
    mocks.applicationHistory.mockResolvedValue({ events: [], next_cursor: null });
    mocks.preview.mockResolvedValue(review);
    mocks.transition.mockResolvedValue({ docket_id: family.docket_id, status: "closed", is_active: false, lifecycle_version: 1 });
  });
  it("requires explicit confirmation and preserves disclosure facts in the authoritative cache", async () => {
    const { client } = mount();
    await preview();
    const confirm = screen.getByRole("button", { name: "Confirm lifecycle change" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I confirm this lifecycle change and its recorded impacts."));
    fireEvent.click(confirm);
    await waitFor(() => expect(mocks.transition).toHaveBeenCalledTimes(1));
    expect(mocks.transition).toHaveBeenCalledWith(family.docket_id, expect.objectContaining({
      lifecycleVersion: 0, toStatus: "closed", evidenceRef: "instruction:original", acknowledgedExceptionCodes: [],
    }));
    await waitFor(() => expect(client.getQueryData(["ip", "patent-family", family.id])).toEqual({
      ...family, lifecycle_status: "closed", lifecycle_version: 1, is_active: false,
    }));
  });
  it("invalidates preview when evidence or the authoritative lifecycle version changes", async () => {
    const { rerender } = mount();
    await preview();
    fireEvent.change(screen.getByLabelText("Instruction or evidence reference"), { target: { value: "instruction:replacement" } });
    expect(screen.queryByRole("button", { name: "Confirm lifecycle change" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview lifecycle change" }));
    await screen.findByRole("button", { name: "Confirm lifecycle change" });
    rerender({ ...family, lifecycle_version: 1, lifecycle_status: "closed", is_active: false });
    expect(screen.queryByRole("button", { name: "Confirm lifecycle change" })).not.toBeInTheDocument();
    expect(mocks.transition).not.toHaveBeenCalled();
  });
  it("requires each exception to be acknowledged, and never retries a failed mutation", async () => {
    mocks.preview.mockResolvedValue({ ...review, blocker_codes: ["open_incident"], requires_exception_acknowledgement: true });
    mocks.transition.mockRejectedValue(new Error("Lifecycle version changed; reload."));
    mount(); await preview();
    fireEvent.click(screen.getByLabelText("I confirm this lifecycle change and its recorded impacts."));
    expect(screen.getByRole("button", { name: "Confirm lifecycle change" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Reviewed exception: open incident"));
    fireEvent.click(screen.getByLabelText("I confirm this lifecycle change and its recorded impacts."));
    fireEvent.click(screen.getByRole("button", { name: "Confirm lifecycle change" }));
    await screen.findByRole("alert");
    expect(mocks.transition).toHaveBeenCalledTimes(1);
  });
  it("shows read-only history without reviewer capability and paginates with the server cursor", async () => {
    mocks.history.mockResolvedValue({ events: [{
      id: "event", sequence: 2, from_status: "closed", to_status: "ready",
      reason: "Explicit client reopening", evidence_refs: ["instruction:reopen"],
      effective_at: "2026-09-06T00:00:00Z", entered_at: "2026-09-06T01:00:00Z",
    }], next_cursor: 2 });
    mount(family, false);
    await screen.findByText("Explicit client reopening");
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Older events" }));
    await waitFor(() => expect(mocks.history).toHaveBeenCalledWith(family.id, 2, expect.any(AbortSignal)));
    expect(mocks.preview).not.toHaveBeenCalled();
  });
  it("does not let a delayed preview for an old version authorize a newer record", async () => {
    let resolve!: (value: typeof review) => void;
    mocks.preview.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { rerender } = mount();
    fireEvent.submit(screen.getByRole("form", { name: "Family lifecycle command" }));
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(1));
    rerender({ ...family, lifecycle_version: 2 });
    await act(async () => resolve(review));
    expect(screen.queryByRole("button", { name: "Confirm lifecycle change" })).not.toBeInTheDocument();
  });
  it("closes only the selected application and leaves its family and sibling caches unchanged", async () => {
    const application: PatentApplication = {
      id: "00000000-0000-4000-8000-000000000005", docket_id: "00000000-0000-4000-8000-000000000006",
      family_id: family.id, record_kind: "patent_application", version: 1, lifecycle_version: 0,
      lifecycle_status: "draft", is_active: true, prosecution_phase: "disclosure",
      created_at: family.created_at, updated_at: family.updated_at,
      facts: { title: "Independent application", application_kind: "complete", jurisdiction: "IN", office: "IP India",
        filing_date: null, publication_date: null, source_pending_identifier_allocation: true, identifiers: [],
        source: { kind: "document_version", document_id: family.id, document_version_id: family.id, content_sha256: "a".repeat(64) } },
    };
    mocks.preview.mockResolvedValue({ ...review, docket_id: application.docket_id });
    mocks.transition.mockResolvedValue({ docket_id: application.docket_id, status: "closed", is_active: false, lifecycle_version: 1 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    client.setQueryData(["ip", "patent-family", family.id], family);
    client.setQueryData(["ip", "patent-application", application.id], application);
    client.setQueryData(["ip", "patent-application", "sibling"], { ...application, id: "sibling" });
    render(<QueryClientProvider client={client}><PatentRecordLifecycle record={application} canReview /></QueryClientProvider>);
    await waitFor(() => expect(mocks.applicationHistory).toHaveBeenCalledWith(application.id, undefined, expect.any(AbortSignal)));
    expect(mocks.history).not.toHaveBeenCalled();
    await preview();
    fireEvent.click(screen.getByLabelText("I confirm this lifecycle change and its recorded impacts."));
    fireEvent.click(screen.getByRole("button", { name: "Confirm lifecycle change" }));
    await waitFor(() => expect(client.getQueryData(["ip", "patent-application", application.id])).toEqual({
      ...application, lifecycle_status: "closed", lifecycle_version: 1, is_active: false,
    }));
    expect(client.getQueryData(["ip", "patent-family", family.id])).toEqual(family);
    expect(client.getQueryData(["ip", "patent-application", "sibling"])).toEqual({ ...application, id: "sibling" });
    expect(mocks.transition).toHaveBeenCalledWith(application.docket_id, expect.objectContaining({ lifecycleVersion: 0 }));
  });
});
