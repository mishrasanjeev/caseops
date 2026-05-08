import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  uploadMock,
  updateMetadataMock,
  retryMock,
  reindexMock,
  workspaceData,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  updateMetadataMock: vi.fn(),
  retryMock: vi.fn(),
  reindexMock: vi.fn(),
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

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function attachments(list: Array<Record<string, unknown>>) {
  workspaceData.current = { ...(workspaceData.current as object), attachments: list };
}

describe("MatterDocumentsPage", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    updateMetadataMock.mockReset();
    retryMock.mockReset();
    reindexMock.mockReset();
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    workspaceData.current = { ...(workspaceData.current as object), court_orders: [] };
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
    });
    expect(toastSuccess).toHaveBeenCalled();
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
});
