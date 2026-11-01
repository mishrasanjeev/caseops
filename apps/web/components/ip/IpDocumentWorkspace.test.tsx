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
  seedIpDocumentTaxonomyMock,
  uploadIpDocumentMock,
} = vi.hoisted(() => ({
  downloadApiFileMock: vi.fn(),
  fetchIpDocumentsMock: vi.fn(),
  fetchIpDocumentTaxonomyMock: vi.fn(),
  importIpDocumentAliasesMock: vi.fn(),
  previewIpDocumentNameMock: vi.fn(),
  seedIpDocumentTaxonomyMock: vi.fn(),
  uploadIpDocumentMock: vi.fn(),
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
  seedIpDocumentTaxonomy: seedIpDocumentTaxonomyMock,
  transitionIpDocument: vi.fn(),
  uploadIpDocument: uploadIpDocumentMock,
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
  access_policy_version: 0,
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
    const classification = await screen.findByRole("combobox", { name: "Classification" });
    await waitFor(() => expect(classification).toBeEnabled());
    fireEvent.change(classification, { target: { value: "evidence" } });
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
    const aliasClassification = screen.getByRole("combobox", { name: "Alias classification" });
    await waitFor(() => expect(aliasClassification).toBeEnabled());
    fireEvent.change(aliasClassification, { target: { value: "evidence" } });
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

  it("disables upload and offers admins the standard classifications when none exist", async () => {
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [],
    });
    seedIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [
        { key: "assignment", label: "Assignment", is_active: true, version: 1 },
        { key: "licence", label: "Licence", is_active: true, version: 1 },
      ],
    });
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage canReview canConfigure />,
    ));

    const status = await screen.findByText("No document classifications are configured");
    const notice = status.closest("[role=status]");
    expect(notice).toHaveAttribute("id", "ip-document-taxonomy-status");
    const classification = screen.getByRole("combobox", { name: "Classification" });
    expect(classification).toBeDisabled();
    expect(classification).toHaveAttribute("aria-describedby", "ip-document-taxonomy-status");
    expect(classification).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Alias classification" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Original file"), {
      target: { files: [new File(["deed"], "deed.txt", { type: "text/plain" })] },
    });
    for (const name of ["Preview controlled name", "Upload reviewed document"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-describedby", "ip-document-taxonomy-status");
    }
    expect(screen.queryByText(/Ask an IP workspace admin/)).not.toBeInTheDocument();

    // After the seed, the refetched server list is what the select offers.
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [
        { key: "assignment", label: "Assignment", is_active: true, version: 1 },
        { key: "licence", label: "Licence", is_active: true, version: 1 },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Load standard classifications" }));
    await waitFor(() => expect(seedIpDocumentTaxonomyMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(classification).toBeEnabled());
    expect(screen.queryByText("No document classifications are configured")).not.toBeInTheDocument();
    expect(Array.from((classification as HTMLSelectElement).options).map((option) => option.value))
      .toEqual(["", "assignment", "licence"]);
    expect(classification).toHaveValue("");
    expect(screen.getByRole("button", { name: "Preview controlled name" })).toBeDisabled();
    expect(screen.getByText("Choose a classification before upload.")).toBeVisible();
    expect(previewIpDocumentNameMock).not.toHaveBeenCalled();
  });

  it("tells members without taxonomy admin to ask an IP workspace admin", async () => {
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [],
    });
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage={false} canReview={false} canConfigure={false} />,
    ));

    expect(await screen.findByText(
      "Ask an IP workspace admin to load the standard document classifications.",
    )).toBeVisible();
    expect(screen.queryByRole("button", { name: "Load standard classifications" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Classification" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Upload reviewed document" })).toBeDisabled();
    expect(seedIpDocumentTaxonomyMock).not.toHaveBeenCalled();
  });

  it("does not offer the standard set when every classification was deactivated", async () => {
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [{ key: "evidence", label: "Evidence", is_active: false, version: 2 }],
    });
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage canReview canConfigure />,
    ));

    expect(await screen.findByText("Every document classification is inactive")).toBeVisible();
    expect(screen.getByText(/reactivate a classification/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Load standard classifications" })).not.toBeInTheDocument();
    const classification = screen.getByRole("combobox", { name: "Classification" });
    expect(Array.from((classification as HTMLSelectElement).options).map((option) => option.value))
      .toEqual([""]);
  });

  it("shows the seed failure next to the action that failed", async () => {
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [],
    });
    seedIpDocumentTaxonomyMock.mockRejectedValue(new Error("Capability 'ip:taxonomy_admin' is required."));
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage canReview canConfigure />,
    ));

    fireEvent.click(await screen.findByRole("button", { name: "Load standard classifications" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Capability 'ip:taxonomy_admin' is required.",
    );
    expect(screen.getByRole("combobox", { name: "Classification" })).toBeDisabled();
  });

  it("keeps classification-dependent actions disabled while loading and retries a failed load", async () => {
    let resolveTaxonomy: (value: unknown) => void = () => undefined;
    fetchIpDocumentTaxonomyMock
      .mockReturnValueOnce(new Promise((resolve) => { resolveTaxonomy = resolve; }))
      .mockResolvedValueOnce({
        taxonomy_version: "ip-document-taxonomy-v1",
        entries: [{ key: "assignment", label: "Assignment", is_active: true, version: 1 }],
      });
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage canReview canConfigure={false} />,
    ));

    expect(screen.getByText("Loading document classifications…")).toBeVisible();
    const classification = screen.getByRole("combobox", { name: "Classification" });
    expect(classification).toBeDisabled();
    expect(classification).toHaveDisplayValue("Loading classifications…");

    resolveTaxonomy(Promise.reject(new Error("Taxonomy service unavailable")));
    expect(await screen.findByText("Could not load document classifications")).toBeVisible();
    expect(screen.getByText("Taxonomy service unavailable")).toBeVisible();
    expect(classification).toBeDisabled();
    expect(screen.getByRole("button", { name: "Upload reviewed document" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(classification).toBeEnabled());
    expect(fetchIpDocumentTaxonomyMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Could not load document classifications")).not.toBeInTheDocument();
  });

  it("never sends a classification the server did not list as active", async () => {
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [
        { key: "assignment", label: "Assignment", is_active: true, version: 1 },
        { key: "evidence", label: "Evidence", is_active: false, version: 2 },
      ],
    });
    previewIpDocumentNameMock.mockImplementation(async (input: { taxonomyKey: string }) => ({
      pattern: "[DocumentType]",
      requested_name: `ACME_${input.taxonomyKey}_1.txt`,
      resolved_name: `ACME_${input.taxonomyKey}_1.txt`,
      conflict_detected: false,
      conflict_suffix: null,
      sanitized_components: [],
      omitted_components: [],
      warnings: [],
      export_safe_name: `ACME_${input.taxonomyKey}_1.txt`,
    }));
    uploadIpDocumentMock.mockResolvedValue({ outcome: "created", document: null });
    render(withClient(
      <IpDocumentWorkspace dockets={dockets} canUpload canManage canReview canConfigure />,
    ));

    const classification = screen.getByRole("combobox", { name: "Classification" });
    await waitFor(() => expect(classification).toBeEnabled());
    // The inactive entry and the former hidden "evidence" default are not offered.
    expect(Array.from((classification as HTMLSelectElement).options).map((option) => option.value))
      .toEqual(["", "assignment"]);
    expect(classification).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Original file"), {
      target: { files: [new File(["deed"], "deed.txt", { type: "text/plain" })] },
    });
    expect(screen.getByRole("button", { name: "Preview controlled name" })).toBeDisabled();
    expect(screen.getByText("Choose a classification before upload.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview controlled name" }))
      .toHaveAttribute("aria-describedby", "ip-document-upload-requirements");

    fireEvent.change(classification, { target: { value: "assignment" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview controlled name" }));
    expect(await screen.findByText("ACME_assignment_1.txt")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Upload reviewed document" }));
    await waitFor(() => expect(uploadIpDocumentMock).toHaveBeenCalledOnce());

    const listed = new Set(["assignment"]);
    for (const [input] of previewIpDocumentNameMock.mock.calls) expect(listed).toContain(input.taxonomyKey);
    for (const [input] of uploadIpDocumentMock.mock.calls) expect(listed).toContain(input.taxonomyKey);
    expect(uploadIpDocumentMock).toHaveBeenCalledWith(
      expect.objectContaining({ taxonomyKey: "assignment", docketId: "docket-1" }),
    );
  });

  it("BUG-002 says the docket list is loading or failed instead of claiming no docket exists", async () => {
    const { ApiError } = await import("@/lib/api/config");
    const retry = vi.fn();
    const { rerender } = render(withClient(
      <IpDocumentWorkspace dockets={[]} docketsLoading canUpload canManage canReview canConfigure />,
    ));
    const linked = screen.getByRole("combobox", { name: "Linked docket" });
    expect(linked).toBeDisabled();
    expect(document.getElementById(linked.getAttribute("aria-describedby")!)).toHaveTextContent("Loading dockets…");
    expect(screen.queryByText(/No IP record to link yet/)).not.toBeInTheDocument();

    rerender(withClient(
      <IpDocumentWorkspace
        dockets={[]}
        docketsError={new ApiError(503, "The IP service is unavailable.", null)}
        onRetryDockets={retry}
        canUpload
        canManage
        canReview
        canConfigure
      />,
    ));
    const failed = screen.getByRole("combobox", { name: "Linked docket" });
    expect(document.getElementById(failed.getAttribute("aria-describedby")!)).toHaveTextContent("The IP service is unavailable.");
    expect(screen.queryByText(/No IP record to link yet/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();

    rerender(withClient(
      <IpDocumentWorkspace dockets={[]} canUpload canManage canReview canConfigure />,
    ));
    expect(screen.getByText(/No IP record to link yet\. Create the record first/)).toBeVisible();
  });

  it("preselects a deep-linked record and closes the docket list when there is none", async () => {
    const two = [dockets[0], { ...dockets[0], id: "docket-pine", title: "PINE LABS" }];
    const view = render(withClient(
      <IpDocumentWorkspace dockets={two} preferredDocketId="docket-pine" canUpload canManage canReview canConfigure />,
    ));
    expect(await screen.findByLabelText("Linked docket")).toHaveValue("docket-pine");
    view.unmount();

    render(withClient(
      <IpDocumentWorkspace dockets={[]} canUpload canManage canReview canConfigure />,
    ));
    const linked = await screen.findByLabelText("Linked docket");
    expect(linked).toBeDisabled();
    expect(linked).toHaveAttribute("aria-describedby", "ip-document-docket-empty");
    expect(screen.getByText(/No IP record to link yet/)).toBeVisible();
  });
});
