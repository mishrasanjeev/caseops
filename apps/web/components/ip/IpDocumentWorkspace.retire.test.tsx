/**
 * B4-ADJ-07: a permitted member retires an IP document with a reason; the panel
 * names every record that still relies on it and never enables a retirement
 * the server would refuse; retired documents stay readable under history.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IpDocument, IpDocumentRetirementPreview } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/config";

const {
  fetchIpDocumentsMock,
  fetchIpDocumentsForDocketMock,
  fetchIpDocumentRetirementMock,
  retireIpDocumentMock,
  sessionMembership,
} = vi.hoisted(() => ({
  fetchIpDocumentsMock: vi.fn(),
  fetchIpDocumentsForDocketMock: vi.fn(),
  fetchIpDocumentRetirementMock: vi.fn(),
  retireIpDocumentMock: vi.fn(),
  sessionMembership: { id: "membership-manager" },
}));

vi.mock("@/lib/api/endpoints", () => ({
  addIpDocumentLinks: vi.fn(),
  applyIpDocumentBulk: vi.fn(),
  downloadApiFile: vi.fn(),
  fetchIpDocumentRetirement: fetchIpDocumentRetirementMock,
  fetchIpDocuments: fetchIpDocumentsMock,
  fetchIpDocumentsForDocket: fetchIpDocumentsForDocketMock,
  fetchIpDocumentTaxonomy: vi.fn().mockResolvedValue({
    taxonomy_version: "ip-document-taxonomy-v1",
    entries: [{ key: "evidence", label: "Evidence", is_active: true, version: 1 }],
  }),
  importIpDocumentAliases: vi.fn(),
  previewIpDocumentBulk: vi.fn(),
  previewIpDocumentName: vi.fn(),
  retireIpDocument: retireIpDocumentMock,
  seedIpDocumentTaxonomy: vi.fn(),
  transitionIpDocument: vi.fn(),
  uploadIpDocument: vi.fn(),
  uploadIpDocumentVersion: vi.fn(),
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({ status: "authenticated", token: null, context: { membership: sessionMembership } }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function document(overrides: Partial<IpDocument> = {}): IpDocument {
  return {
    id: "document-1",
    taxonomy_key: "evidence",
    taxonomy_label: "Evidence",
    title: "Executed deed",
    confidentiality: "internal",
    is_privileged: false,
    current_version: 1,
    created_by_membership_id: "membership-uploader",
    created_at: "2026-10-31T00:00:00Z",
    updated_at: "2026-10-31T00:00:00Z",
    links: [],
    retirement: null,
    versions: [{
      id: "version-1",
      version: 1,
      original_filename: "deed.txt",
      display_name: "ACME_Trademark_ASTER_evidence_2026-10-31_1.txt",
      content_type: "text/plain",
      size_bytes: 100,
      sha256_hex: "a".repeat(64),
      processing_status: "indexed",
      extracted_char_count: 100,
      extraction_error: null,
      ocr_quality_score: 0.95,
      low_ocr_quality: false,
      ai_eligible: true,
      state: "draft",
      uploaded_by_membership_id: "membership-uploader",
      locked_by_membership_id: null,
      locked_at: null,
      created_at: "2026-10-31T00:00:00Z",
    }],
    ...overrides,
  } as IpDocument;
}

const RETIRABLE: IpDocumentRetirementPreview = {
  document_id: "document-1",
  title: "Executed deed",
  current_version: 1,
  already_retired: false,
  may_retire: true,
  permission_reason: null,
  blockers: [],
  retirable: true,
};

function renderWorkspace(props: { canManage?: boolean; canUpload?: boolean } = {}) {
  return render(withClient(
    <IpDocumentWorkspace
      dockets={[]}
      canUpload={props.canUpload ?? false}
      canManage={props.canManage ?? true}
      canReview={false}
      canConfigure={false}
    />,
  ));
}

describe("IpDocumentWorkspace retirement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionMembership.id = "membership-manager";
    fetchIpDocumentsMock.mockResolvedValue({ items: [document()], total: 1 });
    fetchIpDocumentRetirementMock.mockResolvedValue(RETIRABLE);
  });

  it("retires with a field-anchored reason and reloads the current list", async () => {
    retireIpDocumentMock.mockResolvedValue(document({
      retirement: { retired_at: "2026-11-01T00:00:00Z", retired_by_name: "Ram", reason: "Wrong file" },
    }));
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Retire" }));
    const panel = await screen.findByRole("region", { name: "Retire Executed deed" });
    const reason = await within(panel).findByLabelText("Reason for retiring");
    const confirm = within(panel).getByRole("button", { name: "Retire document" });
    expect(confirm).toBeEnabled();

    fireEvent.change(reason, { target: { value: "too short" } });
    fireEvent.click(confirm);
    const error = await within(panel).findByRole("alert");
    expect(error).toHaveTextContent("Give a reason of at least 10 characters.");
    expect(reason).toHaveAttribute("aria-invalid", "true");
    expect(reason.getAttribute("aria-describedby")).toContain(error.id);
    expect(retireIpDocumentMock).not.toHaveBeenCalled();

    fireEvent.change(reason, { target: { value: "  Uploaded the wrong file.  " } });
    fetchIpDocumentsMock.mockResolvedValue({ items: [], total: 0 });
    fireEvent.click(confirm);
    await waitFor(() => expect(retireIpDocumentMock).toHaveBeenCalledWith({
      documentId: "document-1", expectedCurrentVersion: 1, reason: "Uploaded the wrong file.",
    }));
    expect(await screen.findByText(/No current controlled IP documents/)).toBeInTheDocument();
    expect(fetchIpDocumentsMock).toHaveBeenLastCalledWith({ includeHistory: false });
  });

  it("names each blocking record with its path and keeps the confirm disabled", async () => {
    fetchIpDocumentRetirementMock.mockResolvedValue({
      ...RETIRABLE,
      retirable: false,
      blockers: [{
        kind: "recordal", record_id: "recordal-1", label: "Assignment recordal", status: "draft",
        docket_id: "docket-1", docket_title: "ASTER trademark",
        resolution: "Withdraw this recordal on Post-registration first.", href: "/app/ip/recordals",
      }, {
        kind: "docket_event", record_id: "restricted", label: "A record you cannot open", status: null,
        docket_id: null, docket_title: null,
        resolution: "Ask a colleague with access to that record to release the document.", href: null,
      }],
    });
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Retire" }));
    const panel = await screen.findByRole("region", { name: "Retire Executed deed" });
    const list = await within(panel).findByTestId("ip-document-retirement-blockers");
    expect(within(panel).getByText(/2 records still rely on this document/)).toBeInTheDocument();
    expect(within(list).getByText("Assignment recordal · draft")).toBeInTheDocument();
    expect(within(list).getByText("On ASTER trademark")).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/app/ip/recordals");
    expect(within(list).getByText("A record you cannot open")).toBeInTheDocument();
    expect(within(panel).queryByLabelText("Reason for retiring")).not.toBeInTheDocument();
    const confirm = within(panel).getByRole("button", { name: "Retire document" });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAccessibleDescription(/still rely on this document/);
    // No raw record ids reach the lawyer.
    expect(panel).not.toHaveTextContent("recordal-1");
  });

  it("reloads the blockers when a record starts relying on the document mid-flow", async () => {
    retireIpDocumentMock.mockRejectedValue(new ApiError(409, "1 record still relies on this document.", {
      code: "ip_document_retirement_blocked", blockers: [],
    }));
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Retire" }));
    const panel = await screen.findByRole("region", { name: "Retire Executed deed" });
    fireEvent.change(await within(panel).findByLabelText("Reason for retiring"), {
      target: { value: "Uploaded the wrong file." },
    });
    fetchIpDocumentRetirementMock.mockResolvedValue({
      ...RETIRABLE, retirable: false,
      blockers: [{
        kind: "recordal", record_id: "recordal-2", label: "Assignment recordal", status: "draft",
        docket_id: "docket-1", docket_title: "ASTER trademark",
        resolution: "Withdraw this recordal on Post-registration first.", href: "/app/ip/recordals",
      }],
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Retire document" }));
    expect(await within(panel).findByText("Assignment recordal · draft")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Retire document" })).toBeDisabled();
  });

  it("shows a retry when the reliance check fails", async () => {
    fetchIpDocumentRetirementMock.mockRejectedValueOnce(new Error("network down"));
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Retire" }));
    const panel = await screen.findByRole("region", { name: "Retire Executed deed" });
    expect(await within(panel).findByText("Could not check which records rely on this document")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Retire document" })).toBeDisabled();
    fireEvent.click(within(panel).getByRole("button", { name: /try again|retry/i }));
    expect(await within(panel).findByLabelText("Reason for retiring")).toBeInTheDocument();
  });

  it("offers Retire to a document manager and to the uploader only", async () => {
    const { unmount } = renderWorkspace({ canManage: false, canUpload: true });
    expect(await screen.findByText("ACME_Trademark_ASTER_evidence_2026-10-31_1.txt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    unmount();
    sessionMembership.id = "membership-uploader";
    renderWorkspace({ canManage: false, canUpload: true });
    expect(await screen.findByRole("button", { name: "Retire" })).toBeInTheDocument();
  });

  it("lists retired documents only under history, read-only with their reason", async () => {
    fetchIpDocumentsMock.mockImplementation(async (options?: { includeHistory?: boolean }) => (
      options?.includeHistory
        ? {
          items: [document({
            retirement: { retired_at: "2026-11-01T06:00:00Z", retired_by_name: "Ram Gupta", reason: "Uploaded the wrong file" },
          })],
          total: 1,
        }
        : { items: [], total: 0 }
    ));
    renderWorkspace({ canManage: true, canUpload: true });
    expect(await screen.findByText(/No current controlled IP documents/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show retired documents and documents of closed records"));
    const card = await screen.findByTestId("ip-document-document-1");
    expect(card).toHaveAttribute("data-retired", "true");
    expect(within(card).getByText("Retired")).toBeInTheDocument();
    expect(within(card).getByText(/by Ram Gupta: Uploaded the wrong file/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /Download original/ })).toBeEnabled();
    expect(within(card).queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Move to/ })).not.toBeInTheDocument();
    expect(within(card).queryByLabelText(/New version for/)).not.toBeInTheDocument();
    expect(within(card).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(fetchIpDocumentsMock).toHaveBeenLastCalledWith({ includeHistory: true });
  });
});
