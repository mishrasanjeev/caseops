import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  uploadMock,
  retryMock,
  reindexMock,
  workspaceData,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  uploadMock: vi.fn(),
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
    retryMock.mockReset();
    reindexMock.mockReset();
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
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
    const input = screen.getByTestId("matter-attachment-file-input") as HTMLInputElement;
    const file = new File(["hello"], "order.pdf", { type: "application/pdf" });
    await userEvent.upload(input, file);

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    expect(uploadMock).toHaveBeenCalledWith({ matterId: "m1", file });
    expect(toastSuccess).toHaveBeenCalled();
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
