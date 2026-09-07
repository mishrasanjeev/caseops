import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PatentApplication, PatentFamily } from "@/lib/api/ip-patents";

const mocks = vi.hoisted(() => ({
  list: vi.fn(), get: vi.fn(), create: vi.fn(), correct: vi.fn(), sources: vi.fn(),
  document: vi.fn(), download: vi.fn(), push: vi.fn(), capability: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.capability }));
vi.mock("@/lib/api/ip-patents", async (original) => ({
  ...await original<typeof import("@/lib/api/ip-patents")>(),
  fetchPatentApplications: mocks.list, fetchPatentApplication: mocks.get,
  createPatentApplication: mocks.create, correctPatentApplication: mocks.correct,
}));
vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDocumentsForDocket: mocks.sources, fetchIpDocument: mocks.document, downloadApiFile: mocks.download,
}));
vi.mock("@/components/ip/PatentFamilyLifecycle", () => ({
  PatentRecordLifecycle: ({ record }: { record: PatentApplication }) => <div data-testid="application-lifecycle">{record.docket_id}</div>,
}));
vi.mock("@/components/ip/IpDocumentWorkspace", () => ({
  IpDocumentWorkspace: ({ assetType, scopeDocketId, canUpload, canManage, canReview }: {
    assetType: string; scopeDocketId: string; canUpload: boolean; canManage: boolean; canReview: boolean;
  }) => <div data-testid="scoped-documents" data-upload={canUpload} data-manage={canManage} data-review={canReview}>{assetType}:{scopeDocketId}</div>,
}));

import { PatentApplicationDetail, PatentFamilyApplications } from "./PatentApplicationWorkspace";

const id = (last: string) => `10000000-0000-4000-8000-00000000000${last}`;
const source = { kind: "document_version" as const, document_id: id("4"), document_version_id: id("5"), content_sha256: "a".repeat(64) };
const family: PatentFamily = {
  id: id("1"), docket_id: id("2"), asset_id: id("3"), record_kind: "patent_family",
  version: 3, lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
  created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
  facts: { title: "Original invention", client_id: id("6"), disclosure_date: "2026-09-05",
    disclosure_narrative: "Original disclosure", confidentiality: "restricted", source: null },
};
const application: PatentApplication = {
  id: id("7"), docket_id: id("8"), family_id: family.id, record_kind: "patent_application",
  version: 1, lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
  prosecution_phase: "disclosure", created_at: family.created_at, updated_at: family.updated_at,
  facts: { title: "Original application", application_kind: "complete", jurisdiction: "IN", office: "IP India",
    filing_date: "2026-09-05", publication_date: null, source_pending_identifier_allocation: true, identifiers: [], source },
};
function mount(component: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
  return client;
}

describe("Independent patent application journeys", () => {
  beforeEach(() => {
    vi.resetAllMocks(); mocks.capability.mockReturnValue(true);
    mocks.list.mockResolvedValue({ applications: [application], next_cursor: null });
    mocks.get.mockResolvedValue(application); mocks.create.mockResolvedValue(application);
    mocks.correct.mockResolvedValue({ ...application, version: 2 });
    mocks.sources.mockResolvedValue({ items: [{ id: source.document_id, title: "Original evidence", versions: [
      { id: source.document_version_id, version: 1, sha256_hex: source.content_sha256 },
    ] }], total: 1 });
  });
  it("creates only after exact source selection with the saved family version", async () => {
    mount(<PatentFamilyApplications family={family} canWrite onOpenDocuments={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "New application" }));
    await screen.findByRole("option", { name: "Original evidence - version 1" });
    fireEvent.change(screen.getByLabelText("Application title"), { target: { value: "New application" } });
    fireEvent.change(screen.getByLabelText("Jurisdiction code"), { target: { value: "IN" } });
    fireEvent.change(screen.getByLabelText("Office"), { target: { value: "IP India" } });
    fireEvent.change(screen.getByLabelText("Application source version"), { target: { value: source.document_version_id } });
    fireEvent.click(screen.getByRole("button", { name: "Create application" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(family, expect.objectContaining({
      title: "New application", source, source_pending_identifier_allocation: true, identifiers: [],
    }), expect.stringMatching(/^[a-f0-9-]{36}$/)));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(`/app/ip/patents/applications/${application.id}`));
    expect(mocks.sources).toHaveBeenCalledWith(family.docket_id);
  });
  it("preserves unsaved facts and their original concurrency version across background reads", async () => {
    const client = mount(<PatentApplicationDetail applicationId={application.id} />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit application" }));
    await screen.findByRole("option", { name: "Original evidence - version 1" });
    fireEvent.change(screen.getByLabelText("Application title"), { target: { value: "Unsaved correction" } });
    act(() => { client.setQueryData(["ip", "patent-application", application.id], {
      ...application, version: 2, facts: { ...application.facts, title: "Another writer" },
    }); });
    await screen.findByRole("heading", { level: 1, name: "Another writer" });
    expect(screen.getByLabelText("Application title")).toHaveValue("Unsaved correction");
    fireEvent.change(screen.getByLabelText("Correction reason"), { target: { value: "Correct source transcription." } });
    fireEvent.click(screen.getByRole("button", { name: "Save application correction" }));
    await waitFor(() => expect(mocks.correct).toHaveBeenCalledWith(
      expect.objectContaining({ version: 1, lifecycle_version: 0 }),
      expect.objectContaining({ title: "Unsaved correction", source }), "Correct source transcription.",
    ));
  });
  it("keeps source discovery failure visible and disables saving", async () => {
    mocks.sources.mockRejectedValue(new Error("Source access failed"));
    mount(<PatentApplicationDetail applicationId={application.id} />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit application" }));
    expect(await screen.findByText("Could not load application sources")).toBeVisible();
    expect(screen.getByText("Source access failed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save application correction" })).toBeDisabled();
    expect(mocks.correct).not.toHaveBeenCalled();
  });
  it("offers the scoped document area for an empty source catalogue without inventing a source", async () => {
    mocks.sources.mockResolvedValue({ items: [], total: 0 });
    const open = vi.fn();
    mount(<PatentFamilyApplications family={family} canWrite onOpenDocuments={open} />);
    fireEvent.click(screen.getByRole("button", { name: "New application" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open documents" }));
    expect(open).toHaveBeenCalledOnce(); expect(mocks.create).not.toHaveBeenCalled();
  });
  it("does not expose a blank edit form before authorization or after failed discovery", async () => {
    mocks.get.mockRejectedValue(new Error("Access revoked"));
    mount(<PatentApplicationDetail applicationId={application.id} />);
    expect(screen.queryByRole("button", { name: "Edit application" })).not.toBeInTheDocument();
    await screen.findByText("Could not open patent application");
    expect(screen.queryByLabelText("Application title")).not.toBeInTheDocument();
    expect(mocks.sources).not.toHaveBeenCalled();
  });
  it("does not discover private labels without read capability", () => {
    mocks.capability.mockReturnValue(false);
    mount(<PatentApplicationDetail applicationId={application.id} />);
    expect(screen.getByRole("alert")).toBeVisible(); expect(mocks.get).not.toHaveBeenCalled();
  });
  it("keeps a closed application and its source history read-only while using its own lifecycle", async () => {
    mocks.get.mockResolvedValue({ ...application, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    mount(<PatentApplicationDetail applicationId={application.id} />);
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "Edit application" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Documents" }));
    const docs = await screen.findByTestId("scoped-documents");
    expect(docs).toHaveTextContent(`Patent:${application.docket_id}`);
    for (const flag of ["upload", "manage", "review"]) expect(docs).toHaveAttribute(`data-${flag}`, "false");
    await userEvent.click(screen.getByRole("tab", { name: "Lifecycle" }));
    expect(await screen.findByTestId("application-lifecycle")).toHaveTextContent(application.docket_id);
    expect(screen.getByRole("link", { name: "Patent family" })).toHaveAttribute("href", `/app/ip/patents/${family.id}`);
  });
  it("preserves raw identifiers and pins historical downloads rather than the latest file", async () => {
    mocks.get.mockImplementation((_id, version) => Promise.resolve({ ...application, version: version ?? 2, facts: {
      ...application.facts, source_pending_identifier_allocation: false,
      identifiers: [{ identifier_kind: "application", raw_value: "  IN/2026-001-A  ", source }],
    } }));
    mocks.document.mockResolvedValue({ id: source.document_id, versions: [
      { id: id("9"), version: 2, sha256_hex: "b".repeat(64), display_name: "new.txt" },
      { id: source.document_version_id, version: 1, sha256_hex: source.content_sha256, display_name: "original.txt" },
    ] });
    mount(<PatentApplicationDetail applicationId={application.id} />);
    await screen.findByRole("button", { name: "Edit application" });
    expect(screen.getByText("IN/2026-001-A").textContent).toBe("  IN/2026-001-A  ");
    fireEvent.change(screen.getByLabelText("Version", { exact: true }), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Open version" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(application.id, 1, expect.any(AbortSignal)));
    expect(screen.queryByRole("button", { name: "Edit application" })).not.toBeInTheDocument();
    fireEvent.click((await screen.findAllByRole("button", { name: "Download source version" }))[1]);
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(`/api/ip/documents/${source.document_id}/versions/1/download`, "original.txt"));
  });
});
