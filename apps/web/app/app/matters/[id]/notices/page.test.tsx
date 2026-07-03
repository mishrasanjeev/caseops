import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  uploadMock,
  useCapabilityMock,
  workspaceData,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  workspaceData: {
    current: {
      matter: { id: "m1", matter_code: "N-1", title: "Notice Matter", status: "active" },
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
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: () => ({ data: workspaceData.current }),
}));

vi.mock("@/lib/api/endpoints", () => ({
  uploadMatterAttachment: uploadMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterNoticesPage from "@/app/app/matters/[id]/notices/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterNoticesPage", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    workspaceData.current = {
      ...(workspaceData.current as object),
      attachments: [],
    };
  });

  it("lists only notice documents for the matter", () => {
    useCapabilityMock.mockImplementation(() => false);
    workspaceData.current = {
      ...(workspaceData.current as object),
      attachments: [
        {
          id: "notice-1",
          original_filename: "Demand notice.pdf",
          filename: "demand-notice.pdf",
          mime_type: "application/pdf",
          size_bytes: 2048,
          processing_status: "indexed",
          document_type: "notice",
          lifecycle_stage: "initiation",
          document_date: "2026-07-01",
          notice_source: "Opposing counsel",
          notice_subject: "Demand notice",
          notice_received_on: "2026-07-01",
          notice_response: "Prepare reply by Friday.",
          sequence_index: 1,
          created_at: "2026-07-01T10:00:00Z",
        },
        {
          id: "order-1",
          original_filename: "Order.pdf",
          filename: "order.pdf",
          mime_type: "application/pdf",
          size_bytes: 1024,
          processing_status: "indexed",
          document_type: "order_judgment",
          lifecycle_stage: "orders",
          created_at: "2026-07-01T11:00:00Z",
        },
      ],
    };

    render(withClient(<MatterNoticesPage />));

    expect(screen.getByRole("heading", { name: "Notices" })).toBeInTheDocument();
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Demand notice",
    );
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Opposing counsel",
    );
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Prepare reply by Friday.",
    );
    expect(screen.queryByText("Order.pdf")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("matter-notice-row")).toHaveLength(1);
  });

  it("uploads a new file as a notice in the initiation lifecycle stage", async () => {
    useCapabilityMock.mockImplementation((capability: string) =>
      ["documents:upload", "documents:manage"].includes(capability),
    );
    uploadMock.mockResolvedValue({ id: "notice-2" });
    render(withClient(<MatterNoticesPage />));

    await userEvent.type(screen.getByTestId("matter-notice-source"), "Client");
    await userEvent.type(screen.getByTestId("matter-notice-subject"), "Lease default notice");
    await userEvent.type(screen.getByTestId("matter-notice-received-on"), "2026-07-03");
    await userEvent.type(
      screen.getByTestId("matter-notice-response"),
      "Send response denying default.",
    );
    const file = new File(["notice body"], "legal-notice.txt", {
      type: "text/plain",
    });
    await userEvent.upload(screen.getByTestId("matter-notice-file-input"), file);

    await waitFor(() => {
      expect(uploadMock).toHaveBeenCalledWith(
        expect.objectContaining({
          matterId: "m1",
          file,
          documentType: "notice",
          lifecycleStage: "initiation",
          documentDate: "2026-07-03",
          noticeSource: "Client",
          noticeSubject: "Lease default notice",
          noticeReceivedOn: "2026-07-03",
          noticeResponse: "Send response denying default.",
          sequenceIndex: null,
          linkedCourtOrderId: null,
          hearingId: null,
        }),
      );
    });
  });
});
