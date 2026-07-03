import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  uploadMock,
  updateMetadataMock,
  retryMock,
  reindexMock,
  askMatterFileQuestionMock,
  fetchMatterFileQAHistoryMock,
  exportMatterFileQANoteMock,
  fetchAffidavitMock,
  analyzeAffidavitMock,
  bulkDownloadUrlMock,
  fetchGoogleDriveStatusMock,
  listGoogleDriveFilesMock,
  revokeGoogleDriveConnectionMock,
  startGoogleDriveConnectionMock,
  workspaceData,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  updateMetadataMock: vi.fn(),
  retryMock: vi.fn(),
  reindexMock: vi.fn(),
  askMatterFileQuestionMock: vi.fn(),
  fetchMatterFileQAHistoryMock: vi.fn(),
  exportMatterFileQANoteMock: vi.fn(),
  fetchAffidavitMock: vi.fn(),
  analyzeAffidavitMock: vi.fn(),
  bulkDownloadUrlMock: vi.fn(),
  fetchGoogleDriveStatusMock: vi.fn(),
  listGoogleDriveFilesMock: vi.fn(),
  revokeGoogleDriveConnectionMock: vi.fn(),
  startGoogleDriveConnectionMock: vi.fn(),
  workspaceData: {
    current: {
      matter: { id: "m1", matter_code: "X", title: "T", status: "active" },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [],
      storage_governance: {
        company_id: "company-1",
        used_bytes: 1024,
        quota_bytes: 4096,
        remaining_bytes: 3072,
        max_upload_size_bytes: 26214400,
        state: "ok",
        warning_threshold_percent: 90,
      },
    } as unknown,
  },
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  uploadMatterAttachment: uploadMock,
  updateMatterAttachmentMetadata: updateMetadataMock,
  retryMatterAttachment: retryMock,
  reindexMatterAttachment: reindexMock,
  askMatterFileQuestion: askMatterFileQuestionMock,
  fetchMatterFileQAHistory: fetchMatterFileQAHistoryMock,
  exportMatterFileQANote: exportMatterFileQANoteMock,
  fetchAffidavitIntelligence: fetchAffidavitMock,
  analyzeAffidavitIntelligence: analyzeAffidavitMock,
  matterAttachmentBulkDownloadUrl: bulkDownloadUrlMock,
  fetchGoogleDriveStatus: fetchGoogleDriveStatusMock,
  listGoogleDriveFiles: listGoogleDriveFilesMock,
  revokeGoogleDriveConnection: revokeGoogleDriveConnectionMock,
  startGoogleDriveConnection: startGoogleDriveConnectionMock,
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: () => ({ data: workspaceData.current }),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterDocumentsPage from "@/app/app/matters/[id]/documents/page";
import {
  matterFileQAExportNoteResponse,
  matterFileQAHistoryResponse,
  matterFileQAResponse,
} from "@/lib/api/schemas";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function attachments(list: Array<Record<string, unknown>>) {
  workspaceData.current = { ...(workspaceData.current as object), attachments: list };
}

function storageGovernance(value: Record<string, unknown>) {
  workspaceData.current = {
    ...(workspaceData.current as object),
    storage_governance: value,
  };
}

describe("MatterDocumentsPage", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    updateMetadataMock.mockReset();
    retryMock.mockReset();
    reindexMock.mockReset();
    askMatterFileQuestionMock.mockReset();
    fetchMatterFileQAHistoryMock.mockReset();
    exportMatterFileQANoteMock.mockReset();
    fetchAffidavitMock.mockReset();
    analyzeAffidavitMock.mockReset();
    bulkDownloadUrlMock.mockReset();
    bulkDownloadUrlMock.mockImplementation(
      ({ matterId, attachmentIds }: { matterId: string; attachmentIds: string[] }) =>
        `http://localhost:8000/api/matters/${matterId}/attachments/bulk-download?${attachmentIds
          .map((id) => `attachment_ids=${id}`)
          .join("&")}`,
    );
    fetchGoogleDriveStatusMock.mockReset();
    listGoogleDriveFilesMock.mockReset();
    revokeGoogleDriveConnectionMock.mockReset();
    startGoogleDriveConnectionMock.mockReset();
    fetchMatterFileQAHistoryMock.mockResolvedValue({
      matter_id: "m1",
      entries: [],
    });
    exportMatterFileQANoteMock.mockResolvedValue({
      matter_id: "m1",
      entry_id: "h1",
      note_id: "note1",
      already_exported: false,
      exported_at: "2026-05-13T10:15:00Z",
    });
    fetchAffidavitMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Affidavit intelligence is source-backed hearing-preparation decision support. It is not legal advice.",
      runs: [],
      latest_run: null,
    });
    fetchGoogleDriveStatusMock.mockResolvedValue({
      provider: "google_drive",
      configured: true,
      missing_config_names: [],
      connections: [],
    });
    listGoogleDriveFilesMock.mockResolvedValue({
      provider: "google_drive",
      connection_id: "drive-1",
      files: [],
    });
    revokeGoogleDriveConnectionMock.mockResolvedValue({
      id: "drive-1",
      company_id: "company-1",
      membership_id: "member-1",
      provider: "google_drive",
      provider_account_id: "google-user-1",
      display_email: "lawyer@example.com",
      status: "revoked",
      scopes: ["https://www.googleapis.com/auth/drive.readonly"],
      connected_at: "2026-06-08T10:00:00Z",
      last_list_at: null,
      created_at: "2026-06-08T10:00:00Z",
      updated_at: "2026-06-08T10:00:00Z",
    });
    startGoogleDriveConnectionMock.mockResolvedValue({
      provider: "google_drive",
      provider_available: true,
      auth_url: "https://accounts.google.com/o/oauth2/v2/auth",
      unavailable_reason: null,
    });
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    workspaceData.current = { ...(workspaceData.current as object), court_orders: [] };
    storageGovernance({
      company_id: "company-1",
      used_bytes: 1024,
      quota_bytes: 4096,
      remaining_bytes: 3072,
      max_upload_size_bytes: 26214400,
      state: "ok",
      warning_threshold_percent: 90,
    });
    attachments([]);
  });

  it("hides the upload control for users without documents:upload", () => {
    useCapabilityMock.mockImplementation(() => false);
    render(withClient(<MatterDocumentsPage />));
    expect(screen.queryByTestId("matter-attachment-upload")).toBeNull();
    expect(screen.getByText(/No documents attached yet/i)).toBeInTheDocument();
  });

  it("uploads a selected file when the user has documents:upload", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    uploadMock.mockResolvedValue({ id: "a1" });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.selectOptions(
      screen.getByTestId("matter-attachment-document-type"),
      "order_judgment",
    );
    expect(screen.getByTestId("matter-attachment-lifecycle-stage")).toHaveValue("orders");
    await userEvent.type(screen.getByLabelText("Document date"), "2026-05-03");
    await userEvent.type(screen.getByLabelText("Sequence"), "5");
    const input = screen.getByTestId("matter-attachment-file-input") as HTMLInputElement;
    const file = new File(["hello"], "order.pdf", { type: "application/pdf" });
    await userEvent.upload(input, file);

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    expect(uploadMock).toHaveBeenCalledWith({
      matterId: "m1",
      file,
      documentType: "order_judgment",
      lifecycleStage: "orders",
      documentDate: "2026-05-03",
      sequenceIndex: 5,
      linkedCourtOrderId: null,
      hearingId: null,
    });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("lets document uploaders list and revoke their own Google Drive metadata safely", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    fetchGoogleDriveStatusMock.mockResolvedValue({
      provider: "google_drive",
      configured: true,
      missing_config_names: [],
      connections: [
        {
          id: "drive-1",
          company_id: "company-1",
          membership_id: "member-1",
          provider: "google_drive",
          provider_account_id: "google-user-1",
          display_email: "lawyer@example.com",
          status: "connected",
          scopes: ["https://www.googleapis.com/auth/drive.readonly"],
          connected_at: "2026-06-08T10:00:00Z",
          last_list_at: null,
          created_at: "2026-06-08T10:00:00Z",
          updated_at: "2026-06-08T10:00:00Z",
        },
      ],
    });
    listGoogleDriveFilesMock.mockResolvedValue({
      provider: "google_drive",
      connection_id: "drive-1",
      files: [
        {
          provider_file_id: "file-1",
          name: "Signed vakalatnama.pdf",
          mime_type: "application/pdf",
          size_bytes: 2048,
          modified_time: "2026-06-08T09:00:00Z",
          web_url: "https://drive.google.com/file/d/file-1/view",
        },
      ],
    });

    render(withClient(<MatterDocumentsPage />));

    const panel = await screen.findByTestId("matter-google-drive-panel");
    expect(await screen.findByText("Connected as lawyer@example.com")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Connected as lawyer@example.com");
    expect(panel.textContent).not.toMatch(
      /access_token|refresh_token|client_secret|encrypted_token_ref|provider payload|gross profit|gross margin|internal cost/i,
    );

    await userEvent.click(screen.getByTestId("matter-google-drive-list"));
    await waitFor(() =>
      expect(listGoogleDriveFilesMock).toHaveBeenCalledWith({ limit: 10 }),
    );
    expect(await screen.findByText("Signed vakalatnama.pdf")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("matter-google-drive-revoke"));
    await waitFor(() =>
      expect(revokeGoogleDriveConnectionMock).toHaveBeenCalledTimes(1),
    );
    expect(revokeGoogleDriveConnectionMock.mock.calls[0][0]).toBe("drive-1");
  });

  it("groups documents by lifecycle and shows unclassified legacy documents", () => {
    useCapabilityMock.mockImplementation(() => false);
    attachments([
      {
        id: "a1",
        original_filename: "evidence.pdf",
        document_type: "evidence",
        lifecycle_stage: "evidence",
        document_date: "2026-05-02",
        sequence_index: 20,
        processing_status: "indexed",
        created_at: "2026-05-04T10:00:00Z",
        size_bytes: 2048,
      },
      {
        id: "a2",
        original_filename: "legacy.pdf",
        document_type: null,
        lifecycle_stage: null,
        processing_status: "indexed",
        created_at: "2026-05-05T10:00:00Z",
        size_bytes: 1024,
      },
    ]);

    render(withClient(<MatterDocumentsPage />));

    expect(screen.getByTestId("matter-document-group-evidence")).toBeInTheDocument();
    expect(screen.getByTestId("matter-document-group-unclassified")).toBeInTheDocument();
    expect(screen.getByText("Seq 20")).toBeInTheDocument();
    expect(screen.getAllByText("Unclassified").length).toBeGreaterThan(0);
  });

  it("builds a bulk ZIP download link for selected documents", async () => {
    useCapabilityMock.mockImplementation(() => false);
    attachments([
      {
        id: "a1",
        original_filename: "pleading.txt",
        document_type: "pleading_reply",
        lifecycle_stage: "pleadings",
        processing_status: "indexed",
        created_at: "2026-07-03T10:00:00Z",
        size_bytes: 100,
      },
      {
        id: "a2",
        original_filename: "evidence.txt",
        document_type: "evidence",
        lifecycle_stage: "evidence",
        processing_status: "indexed",
        created_at: "2026-07-03T10:05:00Z",
        size_bytes: 200,
      },
    ]);

    render(withClient(<MatterDocumentsPage />));

    expect(screen.getByTestId("matter-documents-bulk-download")).toBeDisabled();
    await userEvent.click(screen.getByTestId("matter-document-select-a1"));

    expect(screen.getByTestId("matter-documents-selected-count")).toHaveTextContent(
      "1 selected",
    );
    expect(bulkDownloadUrlMock).toHaveBeenCalledWith({
      matterId: "m1",
      attachmentIds: ["a1"],
    });
    expect(screen.getByTestId("matter-documents-bulk-download")).toHaveAttribute(
      "href",
      "http://localhost:8000/api/matters/m1/attachments/bulk-download?attachment_ids=a1",
    );

    await userEvent.click(screen.getByTestId("matter-documents-select-visible"));
    expect(screen.getByTestId("matter-documents-selected-count")).toHaveTextContent(
      "2 selected",
    );
    expect(screen.getByTestId("matter-documents-bulk-download")).toHaveAttribute(
      "href",
      "http://localhost:8000/api/matters/m1/attachments/bulk-download?attachment_ids=a1&attachment_ids=a2",
    );
  });

  it("lets document managers edit lifecycle metadata", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:manage");
    updateMetadataMock.mockResolvedValue({ id: "a1" });
    workspaceData.current = {
      ...(workspaceData.current as object),
      court_orders: [{ id: "o1", title: "Interim order", order_date: "2026-05-03" }],
      attachments: [
        {
          id: "a1",
          original_filename: "legacy.pdf",
          document_type: null,
          lifecycle_stage: null,
          processing_status: "indexed",
          created_at: "2026-05-05T10:00:00Z",
          size_bytes: 1024,
        },
      ],
    };

    render(withClient(<MatterDocumentsPage />));
    await userEvent.click(screen.getByTestId("matter-attachment-edit-a1"));
    await userEvent.selectOptions(screen.getAllByLabelText("Document type")[0], "pleading_reply");
    await userEvent.type(screen.getAllByLabelText("Document date")[0], "2026-05-01");
    await userEvent.type(screen.getAllByLabelText("Sequence")[0], "12");
    await userEvent.selectOptions(screen.getAllByLabelText("Linked order")[0], "o1");
    await userEvent.click(screen.getByTestId("matter-attachment-save-a1"));

    await waitFor(() => expect(updateMetadataMock).toHaveBeenCalledTimes(1));
    expect(updateMetadataMock).toHaveBeenCalledWith({
      matterId: "m1",
      attachmentId: "a1",
      document_type: "pleading_reply",
      lifecycle_stage: "pleadings",
      document_date: "2026-05-01",
      sequence_index: 12,
      linked_court_order_id: "o1",
      hearing_id: null,
    });
    expect(toastSuccess).toHaveBeenCalledWith("Document metadata updated.");
  });

  it("shows retry for failed attachments when the user can manage", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:manage");
    retryMock.mockResolvedValue({ id: "a1" });
    attachments([
      {
        id: "a1",
        original_filename: "failed.pdf",
        mime_type: "application/pdf",
        size_bytes: 1024,
        processing_status: "failed",
        created_at: new Date().toISOString(),
      },
    ]);

    render(withClient(<MatterDocumentsPage />));
    const retryButton = screen.getByTestId("matter-attachment-retry-a1");
    await userEvent.click(retryButton);

    await waitFor(() => expect(retryMock).toHaveBeenCalledTimes(1));
    expect(retryMock).toHaveBeenCalledWith({ matterId: "m1", attachmentId: "a1" });
    expect(toastSuccess).toHaveBeenCalledWith("Retry queued.");
  });

  it("shows reindex for indexed attachments and fires the mutation", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:manage");
    reindexMock.mockResolvedValue({ id: "a1" });
    attachments([
      {
        id: "a1",
        original_filename: "indexed.pdf",
        mime_type: "application/pdf",
        size_bytes: 1024,
        processing_status: "indexed",
        created_at: new Date().toISOString(),
      },
    ]);

    render(withClient(<MatterDocumentsPage />));
    expect(screen.queryByTestId("matter-attachment-retry-a1")).toBeNull();
    await userEvent.click(screen.getByTestId("matter-attachment-reindex-a1"));

    await waitFor(() => expect(reindexMock).toHaveBeenCalledTimes(1));
    expect(reindexMock).toHaveBeenCalledWith({ matterId: "m1", attachmentId: "a1" });
  });

  it("BUG-038: PDF attachments are opened through the dedicated viewer route", () => {
    useCapabilityMock.mockImplementation(() => false);
    attachments([
      {
        id: "a1",
        original_filename: "court-order.pdf",
        mime_type: "application/pdf",
        size_bytes: 2048,
        processing_status: "indexed",
        created_at: new Date().toISOString(),
      },
    ]);

    render(withClient(<MatterDocumentsPage />));

    const nameLink = screen.getByTestId("matter-attachment-name-a1");
    const viewLink = screen.getByTestId("matter-attachment-view-a1");
    expect(nameLink).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/a1/view",
    );
    expect(viewLink).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/a1/view",
    );
  });

  it("hides action column entirely for members without documents:manage", () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    attachments([
      {
        id: "a1",
        original_filename: "failed.pdf",
        processing_status: "failed",
        created_at: new Date().toISOString(),
        size_bytes: 100,
      },
    ]);

    render(withClient(<MatterDocumentsPage />));
    expect(screen.queryByTestId("matter-attachment-retry-a1")).toBeNull();
    expect(screen.queryByTestId("matter-attachment-reindex-a1")).toBeNull();
  });

  it("renders Ask case file with safe disclaimer copy", () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");

    render(withClient(<MatterDocumentsPage />));

    const section = screen.getByTestId("matter-file-qa-section");
    expect(section).toHaveTextContent("Ask case file");
    expect(section).toHaveTextContent(
      "Answers use uploaded matter documents only and require lawyer review.",
    );
    expect(screen.getByTestId("matter-file-qa-empty")).toHaveTextContent(
      "Ask a question about uploaded matter documents.",
    );
  });

  it("submits a Matter File Q&A question and renders answer sources", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    attachments([
      {
        id: "a1",
        filename: "fir.pdf",
        original_filename: "fir.pdf",
        created_at: "2026-05-13T10:00:00Z",
      },
    ]);
    askMatterFileQuestionMock.mockResolvedValue({
      matter_id: "m1",
      question: "Which IPC sections are invoked?",
      status: "answered",
      answer: "The uploaded FIR refers to IPC Sections 420 and 406.",
      confidence: "medium",
      sources: [
        {
          source_id: "src_1",
          attachment_id: "a1",
          attachment_name: "fir.pdf",
          chunk_id: "chunk1",
          chunk_index: 0,
          document_type: "complaint_petition",
          page_number: 3,
          snippet: "The FIR invokes IPC Sections 420 and 406 against Party B.",
          score: 87,
          matched_terms: ["IPC", "420"],
        },
      ],
      structured_items: [
        {
          item_type: "section",
          label: "IPC Section 420",
          value: "The FIR invokes IPC Sections 420 and 406 against Party B.",
          source_ids: ["src_1"],
          confidence: "medium",
          evidence_status: "supported",
        },
      ],
      limitations: [
        "Only uploaded matter document chunks were used.",
        "This is decision support for lawyer review, not legal advice.",
      ],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(
      screen.getByTestId("matter-file-qa-question"),
      "Which IPC sections are invoked?",
    );
    await userEvent.selectOptions(screen.getByTestId("matter-file-qa-mode"), "sections");
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    await waitFor(() => expect(askMatterFileQuestionMock).toHaveBeenCalledTimes(1));
    expect(askMatterFileQuestionMock).toHaveBeenCalledWith({
      matterId: "m1",
      question: "Which IPC sections are invoked?",
      answerMode: "sections",
      analysisLanguage: "en",
      limit: 8,
    });
    expect(await screen.findByTestId("matter-file-qa-result-answered")).toHaveTextContent(
      "IPC Sections 420 and 406",
    );
    expect(screen.getByTestId("matter-file-qa-sources")).toHaveTextContent("fir.pdf");
    expect(screen.getByTestId("matter-file-qa-structured-items")).toHaveTextContent(
      "IPC Section 420",
    );
    expect(screen.getByTestId("matter-file-qa-source-src_1")).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/a1/view",
    );
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    expect(screen.getByTestId("matter-file-qa-section").textContent).not.toMatch(
      /legal advice/i,
    );
  });

  it("sends a local-language Matter File Q&A request and renders the labelled aid", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    askMatterFileQuestionMock.mockResolvedValue({
      matter_id: "m1",
      question: "Which payment default is recorded?",
      status: "answered",
      answer: "The uploaded file records non-payment under Invoice A-12.",
      analysis_language: "hi",
      local_language_analysis:
        "अपलोड की गई फ़ाइल Invoice A-12 के तहत भुगतान न होने को दर्ज करती है.",
      translation_status: "provided",
      translation_warning: null,
      confidence: "medium",
      sources: [
        {
          source_id: "src_1",
          attachment_id: "a1",
          attachment_name: "complaint.pdf",
          chunk_id: "chunk1",
          chunk_index: 0,
          document_type: "complaint_petition",
          page_number: null,
          snippet: "The complaint records non-payment under Invoice A-12.",
          score: 82,
          matched_terms: ["payment"],
        },
      ],
      structured_items: [],
      limitations: ["Only uploaded matter document chunks were used."],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(
      screen.getByTestId("matter-file-qa-question"),
      "Which payment default is recorded?",
    );
    await userEvent.selectOptions(screen.getByTestId("matter-file-qa-language"), "hi");
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    await waitFor(() => expect(askMatterFileQuestionMock).toHaveBeenCalledTimes(1));
    expect(askMatterFileQuestionMock).toHaveBeenCalledWith({
      matterId: "m1",
      question: "Which payment default is recorded?",
      answerMode: "direct",
      analysisLanguage: "hi",
      limit: 8,
    });
    expect(await screen.findByTestId("matter-file-qa-result-answered")).toHaveTextContent(
      "English authoritative answer",
    );
    expect(screen.getByTestId("matter-file-qa-local-language-analysis")).toHaveTextContent(
      "Hindi translation aid",
    );
    expect(screen.getByTestId("matter-file-qa-local-language-analysis")).toHaveTextContent(
      "Invoice A-12",
    );
    expect(screen.getByTestId("matter-file-qa-sources")).toHaveTextContent(
      "The complaint records non-payment under Invoice A-12.",
    );
  });

  it("renders Matter File Q&A history and exports a saved answer", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    attachments([
      {
        id: "a1",
        filename: "complaint.pdf",
        original_filename: "complaint.pdf",
        created_at: "2026-05-13T10:00:00Z",
      },
    ]);
    fetchMatterFileQAHistoryMock.mockResolvedValue({
      matter_id: "m1",
      entries: [
        {
          id: "h1",
          matter_id: "m1",
          question: "What allegation appears?",
          answer_status: "answered",
          answer: "The uploaded complaint alleges non-payment under Invoice A-12.",
          confidence: "medium",
          answer_mode: "allegations",
          sources: [
            {
              source_id: "src_history",
              attachment_id: "a1",
              attachment_name: "complaint.pdf",
              chunk_id: "chunk1",
              chunk_index: 0,
              document_type: "complaint_petition",
              page_number: null,
              snippet: "The complaint alleges non-payment under Invoice A-12.",
              score: 81,
              matched_terms: ["complaint"],
            },
          ],
          structured_items: [],
          limitations: ["Only uploaded matter document chunks were used."],
          model_run_id: "run1",
          exported_note_id: null,
          exported_at: null,
          created_at: "2026-05-13T10:10:00Z",
        },
      ],
    });

    render(withClient(<MatterDocumentsPage />));

    const history = await screen.findByTestId("matter-file-qa-history");
    expect(history).toHaveTextContent("Recent Q&A");
    await waitFor(() => expect(history).toHaveTextContent("What allegation appears?"));
    expect(history).toHaveTextContent("What allegation appears?");
    expect(history).toHaveTextContent("non-payment under Invoice A-12");
    expect(screen.getByTestId("matter-file-qa-history-source-src_history")).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/a1/view",
    );

    await userEvent.click(screen.getByTestId("matter-file-qa-history-reopen-h1"));
    expect(screen.getByTestId("matter-file-qa-question")).toHaveValue(
      "What allegation appears?",
    );
    expect(await screen.findByTestId("matter-file-qa-result-answered")).toHaveTextContent(
      "non-payment under Invoice A-12",
    );

    await userEvent.click(screen.getByTestId("matter-file-qa-history-export-h1"));
    await waitFor(() => expect(exportMatterFileQANoteMock).toHaveBeenCalledTimes(1));
    expect(exportMatterFileQANoteMock).toHaveBeenCalledWith({
      matterId: "m1",
      entryId: "h1",
    });
    expect(toastSuccess).toHaveBeenCalledWith("Matter File Q&A note exported.");
  });

  it("does not link saved Matter File Q&A history sources for unknown attachments", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    attachments([
      {
        id: "a1",
        filename: "known.pdf",
        original_filename: "known.pdf",
        created_at: "2026-05-13T10:00:00Z",
      },
    ]);
    fetchMatterFileQAHistoryMock.mockResolvedValue({
      matter_id: "m1",
      entries: [
        {
          id: "h2",
          matter_id: "m1",
          question: "What does the missing source say?",
          answer_status: "answered",
          answer: "The uploaded chunks mention a notice.",
          confidence: "medium",
          answer_mode: "direct",
          sources: [
            {
              source_id: "src_missing",
              attachment_id: "missing",
              attachment_name: "missing.pdf",
              chunk_id: "chunk1",
              chunk_index: 0,
              document_type: null,
              page_number: null,
              snippet: "A notice appears in the uploaded chunks.",
              score: 70,
              matched_terms: ["notice"],
            },
          ],
          structured_items: [],
          limitations: ["Only uploaded matter document chunks were used."],
          model_run_id: null,
          exported_note_id: null,
          exported_at: null,
          created_at: "2026-05-13T10:10:00Z",
        },
      ],
    });

    render(withClient(<MatterDocumentsPage />));

    const sourceLabel = await screen.findByTestId(
      "matter-file-qa-history-source-src_missing",
    );
    expect(sourceLabel.tagName.toLowerCase()).toBe("span");
    expect(sourceLabel).not.toHaveAttribute("href");
    expect(screen.getByText("Source link unavailable")).toBeInTheDocument();
  });

  it("renders Matter File Q&A gap structured items without advice copy", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    askMatterFileQuestionMock.mockResolvedValue({
      matter_id: "m1",
      question: "What record gaps appear?",
      status: "partial_answer",
      answer: "The uploaded chunks identify a record gap for review.",
      confidence: "low",
      sources: [],
      structured_items: [
        {
          item_type: "gap",
          label: "Record gap",
          value: "Record gap identified in source: No supporting invoice is attached.",
          source_ids: ["src_1"],
          confidence: "low",
          evidence_status: "partial",
        },
      ],
      limitations: ["Only uploaded matter document chunks were used."],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(screen.getByTestId("matter-file-qa-question"), "What record gaps appear?");
    await userEvent.selectOptions(screen.getByTestId("matter-file-qa-mode"), "gaps");
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    const items = await screen.findByTestId("matter-file-qa-structured-items");
    expect(items).toHaveTextContent("Record gap");
    expect(items).toHaveTextContent("No supporting invoice is attached");
    expect(items.textContent).not.toMatch(/legal[- ]advice|will win|will lose|win probability/i);
  });

  it("renders partial Matter File Q&A answers", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    askMatterFileQuestionMock.mockResolvedValue({
      matter_id: "m1",
      question: "Summarise the uploaded record.",
      status: "partial_answer",
      answer: "The uploaded chunks partially address the timeline.",
      confidence: "low",
      sources: [],
      limitations: ["Only uploaded matter document chunks were used."],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(
      screen.getByTestId("matter-file-qa-question"),
      "Summarise the uploaded record.",
    );
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    expect(await screen.findByTestId("matter-file-qa-result-partial_answer")).toHaveTextContent(
      "Partial answer prepared from the available uploaded chunks.",
    );
    expect(screen.getByTestId("matter-file-qa-result-partial_answer")).toHaveTextContent(
      "partially address the timeline",
    );
  });

  it("renders Matter File Q&A loading state", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    let resolveQuestion: (value: unknown) => void = () => {};
    askMatterFileQuestionMock.mockReturnValue(
      new Promise((resolve) => {
        resolveQuestion = resolve;
      }),
    );

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(screen.getByTestId("matter-file-qa-question"), "What is alleged?");
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    expect(await screen.findByTestId("matter-file-qa-loading")).toHaveTextContent(
      "Reading indexed matter chunks",
    );

    await act(async () => {
      resolveQuestion({
        matter_id: "m1",
        question: "What is alleged?",
        status: "answered",
        answer: "The uploaded chunks refer to a payment dispute.",
        confidence: "medium",
        sources: [],
        limitations: ["Only uploaded matter document chunks were used."],
        provider: "caseops-matter-file-qa-v1",
        generated_at: "2026-05-13T10:00:00Z",
        model_run_id: "run1",
      });
    });
    expect(await screen.findByTestId("matter-file-qa-result-answered")).toHaveTextContent(
      "payment dispute",
    );
  });

  it("does not link Matter File Q&A sources for unknown attachment IDs", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    attachments([
      {
        id: "a1",
        filename: "known.pdf",
        original_filename: "known.pdf",
        created_at: "2026-05-13T10:00:00Z",
      },
    ]);
    askMatterFileQuestionMock.mockResolvedValue({
      matter_id: "m1",
      question: "What does the unknown source say?",
      status: "answered",
      answer: "The uploaded chunks refer to a notice.",
      confidence: "medium",
      sources: [
        {
          source_id: "src_unknown",
          attachment_id: "missing-attachment",
          attachment_name: "unknown.pdf",
          chunk_id: "chunk1",
          chunk_index: 0,
          document_type: null,
          page_number: null,
          snippet: "A notice was issued on 1 May.",
          score: 75,
          matched_terms: ["notice"],
        },
      ],
      limitations: ["Only uploaded matter document chunks were used."],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    });

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(
      screen.getByTestId("matter-file-qa-question"),
      "What does the unknown source say?",
    );
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    const sourceLabel = await screen.findByTestId("matter-file-qa-source-src_unknown");
    expect(sourceLabel.tagName.toLowerCase()).toBe("span");
    expect(sourceLabel).not.toHaveAttribute("href");
    expect(screen.getByText("Source link unavailable")).toBeInTheDocument();
  });

  it("renders insufficient evidence, processing required, and no documents states", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    const refusals = [
      {
        status: "insufficient_evidence",
        expected: "The uploaded chunks did not provide enough support",
      },
      {
        status: "processing_required",
        expected: "usable indexed chunks are not ready",
      },
      {
        status: "no_documents",
        expected: "Upload matter documents before asking",
      },
    ] as const;

    for (const refusal of refusals) {
      askMatterFileQuestionMock.mockResolvedValueOnce({
        matter_id: "m1",
        question: "What does the file say?",
        status: refusal.status,
        answer: null,
        confidence: "insufficient",
        sources: [],
        limitations: ["Only uploaded matter document chunks were used."],
        provider: "caseops-matter-file-qa-v1",
        generated_at: "2026-05-13T10:00:00Z",
        model_run_id: null,
      });

      const { unmount } = render(withClient(<MatterDocumentsPage />));
      await userEvent.type(
        screen.getByTestId("matter-file-qa-question"),
        "What does the file say?",
      );
      await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

      expect(
        await screen.findByTestId(`matter-file-qa-result-${refusal.status}`),
      ).toHaveTextContent(refusal.expected);
      unmount();
    }
  });

  it("renders Matter File Q&A error state", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    askMatterFileQuestionMock.mockRejectedValue(new Error("Provider unavailable"));

    render(withClient(<MatterDocumentsPage />));
    await userEvent.type(screen.getByTestId("matter-file-qa-question"), "What is alleged?");
    await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

    expect(await screen.findByTestId("matter-file-qa-error")).toHaveTextContent(
      "Provider unavailable",
    );
  });

  it("keeps Ask case file copy within safety boundaries", () => {
    useCapabilityMock.mockImplementation(() => false);

    render(withClient(<MatterDocumentsPage />));

    const section = screen.getByTestId("matter-file-qa-section");
    expect(section.textContent).not.toMatch(
      /legal[- ]advice|guaranteed outcome|guaranteed to win|will win|will lose|success probability|outcome prediction|win probability|loss probability|win\s*(?:[/-]|\s+)\s*loss|judge reputation|judge shopping|best judge|most suitable judge|judge likes|judge dislikes|favorable judge|emotion|psychological|biometric|mental[- ]health|lie detection/i,
    );
  });

  it("withholds unsafe generated Matter File Q&A copy variants", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    const unsafePhrases = [
      "legal advice",
      "legal-advice",
      "guaranteed outcome",
      "guaranteed to win",
      "will win",
      "will lose",
      "success probability",
      "outcome prediction",
      "win probability",
      "loss probability",
      "win/loss",
      "win loss",
      "judge reputation",
      "judge shopping",
      "best judge",
      "most suitable judge",
      "judge likes",
      "judge dislikes",
      "judge likes/dislikes",
      "favorable judge",
      "emotion",
      "psychological",
      "biometric",
      "mental-health",
      "mental-health scoring",
      "lie detection",
      "reveal all tenant documents",
    ];

    for (const phrase of unsafePhrases) {
      fetchMatterFileQAHistoryMock.mockResolvedValueOnce({
        matter_id: "m1",
        entries: [
          {
            id: `hist-${phrase.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
            matter_id: "m1",
            question: "What does the saved file answer say?",
            answer_status: "answered",
            answer: `Saved answer contains ${phrase}.`,
            confidence: "medium",
            answer_mode: "direct",
            sources: [],
            structured_items: [],
            limitations: [`Saved limitation contains ${phrase}.`],
            model_run_id: "run-history",
            created_at: "2026-05-13T09:45:00Z",
            exported_note_id: null,
          },
        ],
      });
      askMatterFileQuestionMock.mockResolvedValueOnce({
        matter_id: "m1",
        question: "What does the file say?",
        status: "answered",
        answer: `This answer contains ${phrase}.`,
        confidence: "medium",
        sources: [],
        limitations: [`Limitation contains ${phrase}.`],
        provider: "caseops-matter-file-qa-v1",
        generated_at: "2026-05-13T10:00:00Z",
        model_run_id: "run1",
      });

      const { unmount } = render(withClient(<MatterDocumentsPage />));
      await userEvent.type(
        screen.getByTestId("matter-file-qa-question"),
        "What does the file say?",
      );
      await userEvent.click(screen.getByTestId("matter-file-qa-submit"));

      const section = await screen.findByTestId("matter-file-qa-result-answered");
      expect(section).toHaveTextContent(
        "The answer was withheld because it did not meet Matter File Q&A display rules.",
      );
      expect(screen.getByTestId("matter-file-qa-section").textContent?.toLowerCase()).not.toContain(
        phrase.toLowerCase(),
      );
      unmount();
    }
  }, 60000);

  it("rejects invalid Matter File Q&A API shapes in the frontend schema", () => {
    const validResponse = {
      matter_id: "m1",
      question: "What is alleged?",
      status: "answered",
      answer: "The complaint alleges non-payment.",
      confidence: "medium",
      sources: [
        {
          source_id: "src_1",
          attachment_id: "a1",
          attachment_name: "complaint.pdf",
          chunk_id: "chunk1",
          chunk_index: 0,
          document_type: "complaint_petition",
          page_number: null,
          snippet: "The complaint alleges non-payment under Invoice A-12.",
          score: 80,
          matched_terms: ["complaint"],
        },
      ],
      structured_items: [
        {
          item_type: "section",
          label: "IPC Section 420",
          value: "The complaint alleges non-payment.",
          source_ids: ["src_1"],
          confidence: "medium",
          evidence_status: "supported",
        },
      ],
      limitations: ["Only uploaded matter document chunks were used."],
      provider: "caseops-matter-file-qa-v1",
      generated_at: "2026-05-13T10:00:00Z",
      model_run_id: "run1",
    };

    expect(matterFileQAResponse.parse(validResponse).status).toBe("answered");
    expect(
      matterFileQAHistoryResponse.parse({
        matter_id: "m1",
        entries: [
          {
            id: "h1",
            matter_id: "m1",
            question: "What is alleged?",
            answer_status: "answered",
            answer: "The complaint alleges non-payment.",
            confidence: "medium",
            answer_mode: "direct",
            sources: validResponse.sources,
            structured_items: validResponse.structured_items,
            limitations: validResponse.limitations,
            model_run_id: "run1",
            exported_note_id: null,
            exported_at: null,
            created_at: "2026-05-13T10:00:00Z",
          },
        ],
      }).entries[0].id,
    ).toBe("h1");
    expect(
      matterFileQAExportNoteResponse.parse({
        matter_id: "m1",
        entry_id: "h1",
        note_id: "note1",
        already_exported: false,
        exported_at: "2026-05-13T10:10:00Z",
      }).note_id,
    ).toBe("note1");
    expect(() =>
      matterFileQAResponse.parse({ ...validResponse, status: "unsupported" }),
    ).toThrow();
    expect(() =>
      matterFileQAHistoryResponse.parse({
        matter_id: "m1",
        entries: [
          {
            id: "",
            matter_id: "m1",
            question: "What is alleged?",
            answer_status: "answered",
            answer: "The complaint alleges non-payment.",
            confidence: "medium",
            answer_mode: "direct",
            sources: validResponse.sources,
            structured_items: [],
            limitations: [],
            model_run_id: null,
            exported_note_id: null,
            exported_at: null,
            created_at: "2026-05-13T10:00:00Z",
          },
        ],
      }),
    ).toThrow();
    expect(() =>
      matterFileQAExportNoteResponse.parse({
        matter_id: "m1",
        entry_id: "",
        note_id: "note1",
        already_exported: false,
        exported_at: "2026-05-13T10:10:00Z",
      }),
    ).toThrow();
    expect(() =>
      matterFileQAResponse.parse({
        ...validResponse,
        sources: [{ ...validResponse.sources[0], chunk_id: undefined }],
      }),
    ).toThrow();
    expect(() =>
      matterFileQAResponse.parse({
        ...validResponse,
        sources: [{ ...validResponse.sources[0], attachment_id: "" }],
      }),
    ).toThrow();
    expect(() =>
      matterFileQAResponse.parse({
        ...validResponse,
        sources: [{ ...validResponse.sources[0], chunk_id: "" }],
      }),
    ).toThrow();
    expect(() =>
      matterFileQAResponse.parse({
        ...validResponse,
        structured_items: [
          { ...validResponse.structured_items[0], source_ids: [""] },
        ],
      }),
    ).toThrow();
    expect(() =>
      matterFileQAResponse.parse({
        ...validResponse,
        structured_items: [
          { ...validResponse.structured_items[0], item_type: "prediction" },
        ],
      }),
    ).toThrow();
  });

  it("renders affidavit statements, question bank, review state, and source links", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "hearing_packs:generate");
    attachments([
      {
        id: "aff1",
        original_filename: "chief-affidavit.pdf",
        document_type: "chief_affidavit",
        lifecycle_stage: "pleadings",
        processing_status: "indexed",
        created_at: "2026-05-05T10:00:00Z",
        size_bytes: 1024,
      },
    ]);
    fetchAffidavitMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Affidavit intelligence is source-backed hearing-preparation decision support. It is not legal advice.",
      runs: [
        {
          id: "run1",
          matter_id: "m1",
          attachment_id: "aff1",
          status: "completed",
          extraction_method: "deterministic",
          parser_version: "caseops-affidavit-deterministic-v1",
          source_hash: "hash",
          source_char_count: 180,
          missing_data: [],
          model_run_id: null,
          created_by_membership_id: "mem1",
          created_at: "2026-05-11T10:00:00Z",
          updated_at: "2026-05-11T10:00:00Z",
          statements: [
            {
              id: "stmt1",
              run_id: "run1",
              matter_id: "m1",
              attachment_id: "aff1",
              source_chunk_id: "chunk1",
              source_chunk_index: 0,
              page_reference: "page 2",
              statement_type: "evidence_gap",
              statement_text: "Supporting document should be reviewed.",
              source_quote: "I state that respondent paid Rs. 10,000 in cash.",
              confidence_label: "low",
              review_status: "review_required",
              created_at: "2026-05-11T10:00:00Z",
              updated_at: "2026-05-11T10:00:00Z",
            },
          ],
          questions: [
            {
              id: "q1",
              run_id: "run1",
              matter_id: "m1",
              attachment_id: "aff1",
              statement_id: "stmt1",
              source_chunk_id: "chunk1",
              source_chunk_index: 0,
              page_reference: "page 2",
              category: "document_support",
              question_text:
                "What primary document supports this assertion, and why is it not identified here?",
              reason:
                "The statement appears to require supporting evidence but does not name a clear exhibit.",
              source_quote: "I state that respondent paid Rs. 10,000 in cash.",
              confidence_label: "low",
              review_required: true,
              review_status: "review_required",
              created_at: "2026-05-11T10:00:00Z",
              updated_at: "2026-05-11T10:00:00Z",
            },
          ],
        },
      ],
      latest_run: {
        id: "run1",
        matter_id: "m1",
        attachment_id: "aff1",
        status: "completed",
        extraction_method: "deterministic",
        parser_version: "caseops-affidavit-deterministic-v1",
        source_hash: "hash",
        source_char_count: 180,
        missing_data: [],
        model_run_id: null,
        created_by_membership_id: "mem1",
        created_at: "2026-05-11T10:00:00Z",
        updated_at: "2026-05-11T10:00:00Z",
        statements: [
          {
            id: "stmt1",
            run_id: "run1",
            matter_id: "m1",
            attachment_id: "aff1",
            source_chunk_id: "chunk1",
            source_chunk_index: 0,
            page_reference: "page 2",
            statement_type: "evidence_gap",
            statement_text: "Supporting document should be reviewed.",
            source_quote: "I state that respondent paid Rs. 10,000 in cash.",
            confidence_label: "low",
            review_status: "review_required",
            created_at: "2026-05-11T10:00:00Z",
            updated_at: "2026-05-11T10:00:00Z",
          },
        ],
        questions: [
          {
            id: "q1",
            run_id: "run1",
            matter_id: "m1",
            attachment_id: "aff1",
            statement_id: "stmt1",
            source_chunk_id: "chunk1",
            source_chunk_index: 0,
            page_reference: "page 2",
            category: "document_support",
            question_text:
              "What primary document supports this assertion, and why is it not identified here?",
            reason:
              "The statement appears to require supporting evidence but does not name a clear exhibit.",
            source_quote: "I state that respondent paid Rs. 10,000 in cash.",
            confidence_label: "low",
            review_required: true,
            review_status: "review_required",
            created_at: "2026-05-11T10:00:00Z",
            updated_at: "2026-05-11T10:00:00Z",
          },
        ],
      },
    });

    render(withClient(<MatterDocumentsPage />));

    expect(await screen.findByTestId("affidavit-intelligence-section")).toBeInTheDocument();
    expect(await screen.findByText("Extracted statements")).toBeInTheDocument();
    expect(screen.getByText("Cross-examination question bank")).toBeInTheDocument();
    expect(screen.getAllByText("Review required").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("I state that respondent paid Rs. 10,000 in cash.").length,
    ).toBeGreaterThan(0);
    expect(screen.getByTestId("affidavit-source-link-aff1")).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/aff1/view",
    );
  });

  it("shows empty and insufficient affidavit intelligence states", async () => {
    useCapabilityMock.mockImplementation(() => false);
    attachments([
      {
        id: "aff1",
        original_filename: "affidavit.pdf",
        document_type: "affidavit",
        lifecycle_stage: "pleadings",
        processing_status: "indexed",
        created_at: "2026-05-05T10:00:00Z",
        size_bytes: 1024,
      },
    ]);
    fetchAffidavitMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Affidavit intelligence is source-backed hearing-preparation decision support. It is not legal advice.",
      runs: [],
      latest_run: {
        id: "run2",
        matter_id: "m1",
        attachment_id: "aff1",
        status: "insufficient_source_text",
        extraction_method: "deterministic",
        parser_version: "caseops-affidavit-deterministic-v1",
        source_hash: "hash",
        source_char_count: 0,
        missing_data: ["raw_attachment_text_chunks"],
        model_run_id: null,
        created_by_membership_id: "mem1",
        created_at: "2026-05-11T10:00:00Z",
        updated_at: "2026-05-11T10:00:00Z",
        statements: [],
        questions: [],
      },
    });

    render(withClient(<MatterDocumentsPage />));

    expect(await screen.findByTestId("affidavit-insufficient-state")).toHaveTextContent(
      "raw_attachment_text_chunks",
    );
    expect(screen.getByText("No extracted statements are available.")).toBeInTheDocument();
  });

  it("runs affidavit analysis from the document workflow without duplicate actions", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "hearing_packs:generate");
    analyzeAffidavitMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Affidavit intelligence is source-backed hearing-preparation decision support. It is not legal advice.",
      runs: [],
      latest_run: null,
    });
    attachments([
      {
        id: "aff1",
        original_filename: "affidavit.pdf",
        document_type: "affidavit",
        lifecycle_stage: "pleadings",
        processing_status: "indexed",
        created_at: "2026-05-05T10:00:00Z",
        size_bytes: 1024,
      },
    ]);

    const { rerender } = render(withClient(<MatterDocumentsPage />));
    expect(await screen.findByTestId("affidavit-analyze-aff1")).toBeInTheDocument();
    rerender(withClient(<MatterDocumentsPage />));
    expect(screen.getAllByTestId("affidavit-analyze-aff1")).toHaveLength(1);
    await userEvent.click(screen.getByTestId("affidavit-analyze-aff1"));

    await waitFor(() => expect(analyzeAffidavitMock).toHaveBeenCalledTimes(1));
    expect(analyzeAffidavitMock).toHaveBeenCalledWith({
      matterId: "m1",
      attachmentId: "aff1",
    });
  });

  it("shows storage upload limits to document uploaders", () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");

    render(withClient(<MatterDocumentsPage />));

    expect(screen.getByTestId("matter-storage-upload-policy")).toHaveTextContent(
      "Max file 25.0 MB",
    );
    expect(screen.getByTestId("matter-storage-upload-policy")).toHaveTextContent(
      "Firm quota remaining 3.0 KB",
    );
  });

  it("blocks the upload control when the firm storage hard limit is reached", () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    storageGovernance({
      company_id: "company-1",
      used_bytes: 4096,
      quota_bytes: 4096,
      remaining_bytes: 0,
      max_upload_size_bytes: 26214400,
      state: "hard_limit",
      warning_threshold_percent: 90,
    });

    render(withClient(<MatterDocumentsPage />));

    expect(screen.getByTestId("matter-storage-upload-blocked")).toHaveTextContent(
      "Firm storage quota reached",
    );
    expect(screen.getByTestId("matter-attachment-upload")).toBeDisabled();
  });

  it("keeps affidavit prep copy within legal-safety boundaries", async () => {
    useCapabilityMock.mockImplementation(() => false);
    render(withClient(<MatterDocumentsPage />));

    const section = await screen.findByTestId("affidavit-intelligence-section");
    expect(section).toHaveTextContent("not legal advice");
    expect(section.textContent).not.toMatch(
      /guaranteed|will win|emotional|psychological|mental state|biometric|voice stress/i,
    );
  });
});
