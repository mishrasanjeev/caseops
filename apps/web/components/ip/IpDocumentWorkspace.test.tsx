import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  downloadApiFileMock,
  fetchIpDocumentsMock,
  fetchIpDocumentTaxonomyMock,
  importIpDocumentAliasesMock,
  previewIpDocumentNameMock,
} = vi.hoisted(() => ({
  downloadApiFileMock: vi.fn(),
  fetchIpDocumentsMock: vi.fn(),
  fetchIpDocumentTaxonomyMock: vi.fn(),
  importIpDocumentAliasesMock: vi.fn(),
  previewIpDocumentNameMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  addIpDocumentLinks: vi.fn(),
  applyIpDocumentBulk: vi.fn(),
  downloadApiFile: downloadApiFileMock,
  fetchIpDocuments: fetchIpDocumentsMock,
  fetchIpDocumentTaxonomy: fetchIpDocumentTaxonomyMock,
  importIpDocumentAliases: importIpDocumentAliasesMock,
  previewIpDocumentBulk: vi.fn(),
  previewIpDocumentName: previewIpDocumentNameMock,
  transitionIpDocument: vi.fn(),
  uploadIpDocument: vi.fn(),
  uploadIpDocumentVersion: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const dockets = [{
  id: "docket-1",
  company_id: "company-1",
  matter_id: null,
  record_type: "trademark",
  title: "ASTER trademark",
  primary_identifier: "TM-12345",
  status: "active",
  restricted: false,
  is_active: true,
  lifecycle_version: 1,
  lifecycle_effective_at: null,
  lifecycle_reason: null,
  lifecycle_outcome: null,
  lifecycle_source: null,
  lifecycle_evidence_ref: null,
  successor_docket_id: null,
  current_version: 1,
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
  current_particulars: {
    id: "particulars-1",
    docket_id: "docket-1",
    version: 1,
    form_key: "TM-A",
    form_version: "2026.1",
    mark_kind: "word",
    representation_json: { word_mark: "ASTER" },
    classes_json: [{ class_number: 9, specification: "Software" }],
    use_priority_json: null,
    parties_json: [{ role: "applicant", name: "ACME" }],
    agent_json: null,
    filing_manifest_json: [],
    readiness_status: "ready",
    readiness_errors_json: [],
    finalized_at: null,
    created_at: "2026-08-09T00:00:00Z",
  },
  notice_links: [],
  deadline_incidents: [],
  title_interests: [],
  cost_items: [],
  related_right_obligations: [],
  evidence_candidates: [],
  deadline_coverages: [],
}];

describe("IpDocumentWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchIpDocumentsMock.mockResolvedValue({ items: [], total: 0 });
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [
        { key: "evidence", label: "Evidence", is_active: true, version: 1 },
        { key: "correspondence", label: "Correspondence", is_active: true, version: 1 },
      ],
    });
  });

  it("requires a current controlled-name preview before upload", async () => {
    previewIpDocumentNameMock.mockResolvedValue({
      pattern: "[ClientCode]_[AssetType]_[Mark]_[DocumentType]_[YYYY-MM-DD]_[Version]",
      requested_name: "ACME_Trademark_ASTER_evidence_2026-08-09_1.txt",
      resolved_name: "ACME_Trademark_ASTER_evidence_2026-08-09_1.txt",
      conflict_detected: false,
      conflict_suffix: null,
      sanitized_components: [],
      omitted_components: [],
      warnings: [],
      export_safe_name: "ACME_Trademark_ASTER_evidence_2026-08-09_1.txt",
    });
    render(withClient(
      <IpDocumentWorkspace
        dockets={dockets}
        canUpload
        canManage
        canReview
        canConfigure={false}
      />,
    ));

    const upload = screen.getByRole("button", { name: "Upload reviewed document" });
    expect(upload).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Original file"), {
      target: { files: [new File(["evidence"], "unsafe:name.txt", { type: "text/plain" })] },
    });
    fireEvent.change(screen.getByLabelText("Client code"), { target: { value: "ACME" } });
    fireEvent.change(screen.getByLabelText("Mark"), { target: { value: "ASTER" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview controlled name" }));

    expect(await screen.findByText("ACME_Trademark_ASTER_evidence_2026-08-09_1.txt")).toBeVisible();
    expect(upload).toBeEnabled();
    expect(previewIpDocumentNameMock).toHaveBeenCalledWith(
      expect.objectContaining({
        clientCode: "ACME",
        mark: "ASTER",
        taxonomyKey: "evidence",
        extension: "txt",
      }),
    );

    fireEvent.change(screen.getByLabelText("Mark"), { target: { value: "ASTER PLUS" } });
    expect(upload).toBeDisabled();
    expect(screen.queryByText("Controlled name preview")).not.toBeInTheDocument();
  });

  it("previews and applies a tenant alias import", async () => {
    importIpDocumentAliasesMock
      .mockResolvedValueOnce({
        dry_run: true,
        imported_count: 2,
        unchanged_count: 0,
        conflicts: [],
      })
      .mockResolvedValueOnce({
        dry_run: false,
        imported_count: 2,
        unchanged_count: 0,
        conflicts: [],
      });
    render(withClient(
      <IpDocumentWorkspace
        dockets={dockets}
        canUpload
        canManage
        canReview
        canConfigure
      />,
    ));

    fireEvent.change(screen.getByLabelText("Supplied document names"), {
      target: { value: "Affidavit Evidence\nEvidence Affidavit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview alias import" }));
    expect(await screen.findByRole("status")).toHaveTextContent("2 new, 0 unchanged, 0 conflicts");
    expect(importIpDocumentAliasesMock).toHaveBeenNthCalledWith(1, {
      taxonomyKey: "evidence",
      aliases: ["Affidavit Evidence", "Evidence Affidavit"],
      dryRun: true,
    });

    fireEvent.click(screen.getByRole("button", { name: "Import reviewed aliases" }));
    await waitFor(() => expect(importIpDocumentAliasesMock).toHaveBeenCalledTimes(2));
    expect(importIpDocumentAliasesMock).toHaveBeenNthCalledWith(2, {
      taxonomyKey: "evidence",
      aliases: ["Affidavit Evidence", "Evidence Affidavit"],
      dryRun: false,
    });
  });

  it("opens original bytes through the authenticated API download owner", async () => {
    fetchIpDocumentsMock.mockResolvedValue({
      items: [{
        id: "document-1",
        taxonomy_key: "evidence",
        taxonomy_label: "Evidence",
        title: "Evidence affidavit",
        confidentiality: "internal",
        is_privileged: false,
        current_version: 1,
        created_by_membership_id: "membership-1",
        created_at: "2026-08-09T00:00:00Z",
        updated_at: "2026-08-09T00:00:00Z",
        links: [],
        versions: [{
          id: "version-1",
          version: 1,
          original_filename: "original evidence.txt",
          display_name: "ACME_Trademark_ASTER_evidence_2026-08-09_1.txt",
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
          uploaded_by_membership_id: "membership-1",
          locked_by_membership_id: null,
          locked_at: null,
          created_at: "2026-08-09T00:00:00Z",
        }],
      }],
      total: 1,
    });
    downloadApiFileMock.mockResolvedValue(undefined);
    render(withClient(
      <IpDocumentWorkspace
        dockets={dockets}
        canUpload
        canManage
        canReview
        canConfigure={false}
      />,
    ));

    fireEvent.click(await screen.findByRole("button", { name: "Download original" }));
    await waitFor(() => expect(downloadApiFileMock).toHaveBeenCalledWith(
      "/api/ip/documents/document-1/versions/1/download",
      "original evidence.txt",
    ));
  });
});
