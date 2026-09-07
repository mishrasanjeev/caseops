import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(), get: vi.fn(), create: vi.fn(), correct: vi.fn(), clients: vi.fn(),
  sources: vi.fn(), document: vi.fn(), download: vi.fn(), push: vi.fn(), capability: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.capability }));
vi.mock("@/lib/api/ip-patents", () => ({
  fetchPatentFamilies: mocks.list, fetchPatentFamily: mocks.get,
  createPatentFamily: mocks.create, correctPatentFamily: mocks.correct,
}));
vi.mock("@/lib/api/endpoints", () => ({
  listClients: mocks.clients, fetchIpDocumentsForDocket: mocks.sources,
  fetchIpDocument: mocks.document, downloadApiFile: mocks.download,
}));
vi.mock("@/components/ip/IpDocumentWorkspace", () => ({
  IpDocumentWorkspace: ({ assetType, scopeDocketId, canUpload, canManage, canReview }: {
    assetType: string; scopeDocketId: string; canUpload: boolean; canManage: boolean; canReview: boolean;
  }) => <div data-testid="scoped-documents" data-upload={canUpload} data-manage={canManage} data-review={canReview}>{assetType}:{scopeDocketId}</div>,
}));

import { PatentFamilyDetail, PatentFamilyIndex } from "./PatentFamilyWorkspace";

const family = {
  id: "fa", docket_id: "docket", asset_id: "asset", record_kind: "patent_family",
  version: 1, lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
  created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
  facts: { title: "Original invention", client_id: "client", disclosure_date: "2026-09-05",
    disclosure_narrative: "Original disclosure", confidentiality: "restricted", source: null },
};
function mount(component: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
  return client;
}
describe("Patent disclosure workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.get.mockResolvedValue(family);
    mocks.list.mockResolvedValue({ families: [family], next_cursor: null });
    mocks.clients.mockResolvedValue({ clients: [{ id: "client", name: "Inventor client", is_active: true }] });
    mocks.sources.mockResolvedValue({ items: [], total: 0 });
    mocks.create.mockResolvedValue(family);
    mocks.correct.mockResolvedValue({ ...family, version: 2 });
  });
  it("creates a restricted disclosure with a durable idempotency key", async () => {
    mount(<PatentFamilyIndex />);
    fireEvent.click(screen.getByRole("button", { name: "New disclosure" }));
    await screen.findByRole("option", { name: "Inventor client" });
    fireEvent.change(screen.getByLabelText("Invention title"), { target: { value: "New invention" } });
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "client" } });
    fireEvent.change(screen.getByLabelText("Disclosure date"), { target: { value: "2026-09-05" } });
    fireEvent.change(screen.getByLabelText("Invention disclosure"), { target: { value: "Detailed disclosure" } });
    fireEvent.click(screen.getByRole("button", { name: "Create disclosure" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      title: "New invention", client_id: "client", confidentiality: "restricted", source: null,
    }), expect.stringMatching(/^[a-f0-9-]{36}$/)));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/app/ip/patents/fa"));
  });
  it("does not hydrate over unsaved corrections or advance their expected version", async () => {
    const client = mount(<PatentFamilyDetail familyId="fa" />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit disclosure" }));
    fireEvent.change(screen.getByLabelText("Invention title"), { target: { value: "Unsaved title" } });
    client.setQueryData(["ip", "patent-family", "fa"], {
      ...family, version: 2, facts: { ...family.facts, title: "Another writer's title" },
    });
    await screen.findByRole("heading", { name: "Another writer's title", level: 1 });
    expect(screen.getByLabelText("Invention title")).toHaveValue("Unsaved title");
    fireEvent.change(screen.getByLabelText("Correction reason"), { target: { value: "Corrected transcription." } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(mocks.correct).toHaveBeenCalledWith(
      expect.objectContaining({ version: 1 }), expect.objectContaining({ title: "Unsaved title" }),
      "Corrected transcription.",
    ));
  });
  it("pins the exact source version, rejects a mismatched hash, and scopes document discovery", async () => {
    const pin = { kind: "document_version", document_id: "doc", document_version_id: "v1", content_sha256: "a".repeat(64) };
    mocks.get.mockResolvedValue({ ...family, facts: { ...family.facts, source: pin } });
    mocks.document.mockResolvedValue({ id: "doc", versions: [
      { id: "v2", version: 2, sha256_hex: "b".repeat(64), display_name: "latest.txt" },
      { id: "v1", version: 1, sha256_hex: "a".repeat(64), display_name: "original.txt" },
    ] });
    mount(<PatentFamilyDetail familyId="fa" />);
    fireEvent.click(await screen.findByRole("button", { name: "Download source version" }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(
      "/api/ip/documents/doc/versions/1/download", "original.txt",
    ));
    mocks.document.mockResolvedValue({ id: "doc", versions: [{ id: "v1", version: 1, sha256_hex: "b".repeat(64) }] });
    fireEvent.click(await screen.findByRole("button", { name: "Download source version" }));
    await screen.findByRole("alert");
    expect(mocks.download).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("tab", { name: /^Documents$/ }));
    expect(await screen.findByTestId("scoped-documents")).toHaveTextContent("Patent:docket");
  });
  it("does not discover private records without read permission", () => {
    mocks.capability.mockReturnValue(false);
    mount(<PatentFamilyIndex />);
    expect(screen.getByRole("alert")).toBeVisible();
    expect(mocks.list).not.toHaveBeenCalled();
  });
  it("keeps terminal disclosure history readable without editable document controls", async () => {
    mocks.get.mockResolvedValue({ ...family, lifecycle_status: "closed", lifecycle_version: 1, is_active: false });
    mount(<PatentFamilyDetail familyId="fa" />);
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "Edit disclosure" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open version" })).toBeEnabled();
    await userEvent.click(screen.getByRole("tab", { name: "Documents" }));
    const documents = await screen.findByTestId("scoped-documents");
    for (const capability of ["upload", "manage", "review"]) expect(documents).toHaveAttribute(`data-${capability}`, "false");
  });
  it("keeps a read failure visible and does not show an editable blank record", async () => {
    mocks.get.mockRejectedValue(new Error("Access revoked"));
    mount(<PatentFamilyDetail familyId="fa" />);
    await screen.findByText("Could not open patent family");
    expect(screen.queryByRole("button", { name: "Edit disclosure" })).not.toBeInTheDocument();
  });
});
