import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  uploadMock,
  updateMock,
  listNoticesMock,
  downloadNoticeFileMock,
  useCapabilityMock,
  workspaceData,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  updateMock: vi.fn(),
  listNoticesMock: vi.fn(),
  downloadNoticeFileMock: vi.fn(),
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
  updateMatterAttachmentMetadata: updateMock,
}));

vi.mock("@/lib/api/notices", () => ({
  listNotices: listNoticesMock,
  downloadNoticeFile: downloadNoticeFileMock,
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
    updateMock.mockReset();
    listNoticesMock.mockReset();
    downloadNoticeFileMock.mockReset();
    listNoticesMock.mockResolvedValue({ notices: [], total: 0 });
    downloadNoticeFileMock.mockResolvedValue(undefined);
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    workspaceData.current = {
      ...(workspaceData.current as object),
      attachments: [],
    };
  });

  it("lists received notices with reply tracking and related documents", () => {
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
          notice_direction: "received",
          notice_document_role: "notice",
          notice_type: "Legal demand",
          notice_authority: "Delhi Police",
          notice_received_from: "Opposing counsel",
          notice_source: "Opposing counsel",
          notice_subject: "Demand notice",
          notice_received_on: "2026-07-01",
          notice_summary: "Prepare reply by Friday.",
          notice_status: "Open",
          notice_department: "Finance",
          notice_internal_spoc: "Asha Mehta",
          notice_reply_due_on: "2026-07-04",
          notice_reply_required: true,
          notice_reply_sent: false,
          notice_reply_status: "reply_overdue",
          notice_reply_days_remaining: -2,
          notice_reminder_offsets: [7, 3, 1],
          sequence_index: 1,
          created_at: "2026-07-01T10:00:00Z",
        },
        {
          id: "reply-1",
          original_filename: "Reply notice.pdf",
          filename: "reply-notice.pdf",
          mime_type: "application/pdf",
          size_bytes: 1024,
          processing_status: "indexed",
          document_type: "notice",
          notice_direction: "received",
          notice_document_role: "reply",
          notice_parent_attachment_id: "notice-1",
          document_date: "2026-07-03",
          created_at: "2026-07-03T10:00:00Z",
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
      "Reply Overdue",
    );
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Delhi Police",
    );
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Finance",
    );
    expect(screen.getByTestId("matter-notice-row")).toHaveTextContent(
      "Reply notice.pdf",
    );
    expect(screen.queryByText("Order.pdf")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("matter-notice-row")).toHaveLength(1);
  });

  it("uploads a received notice with structured metadata", async () => {
    useCapabilityMock.mockImplementation((capability: string) =>
      ["documents:upload", "documents:manage"].includes(capability),
    );
    uploadMock.mockResolvedValue({ id: "notice-2" });
    render(withClient(<MatterNoticesPage />));

    await userEvent.type(screen.getByTestId("matter-notice-type"), "Legal demand");
    await userEvent.type(screen.getByTestId("matter-notice-department"), "Finance");
    await userEvent.type(screen.getByTestId("matter-notice-subject"), "Lease default notice");
    await userEvent.type(screen.getByTestId("matter-notice-authority"), "Rent Controller");
    await userEvent.type(screen.getByTestId("matter-notice-internal-spoc"), "Asha Mehta");
    await userEvent.type(screen.getByTestId("matter-notice-received-on"), "2026-07-03");
    await userEvent.type(screen.getByTestId("matter-notice-mode"), "Email");
    await userEvent.type(screen.getByTestId("matter-notice-source"), "Client");
    await userEvent.type(screen.getByTestId("matter-notice-amount"), "12500");
    await userEvent.type(screen.getByTestId("matter-notice-reply-due-on"), "2026-07-10");
    await userEvent.type(
      screen.getByTestId("matter-notice-summary"),
      "Lease arrears disputed by client.",
    );
    await userEvent.type(
      screen.getByTestId("matter-notice-response"),
      "Send response denying default.",
    );
    await userEvent.type(screen.getByTestId("matter-notice-remarks"), "Urgent.");
    await userEvent.type(
      screen.getByTestId("matter-notice-internal-remarks"),
      "Check ledger.",
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
          noticeDirection: "received",
          noticeDocumentRole: "notice",
          noticeType: "Legal demand",
          noticeMode: "Email",
          noticeSource: "Client",
          noticeSubject: "Lease default notice",
          noticeReceivedOn: "2026-07-03",
          noticeAuthority: "Rent Controller",
          noticeReceivedFrom: "Client",
          noticeSummary: "Lease arrears disputed by client.",
          noticeRemarks: "Urgent.",
          noticeStatus: "Open",
          noticeDepartment: "Finance",
          noticeInternalSpoc: "Asha Mehta",
          noticeInternalRemarks: "Check ledger.",
          noticeAmountMinor: 1250000,
          noticeCurrency: "INR",
          noticeReplyDueOn: "2026-07-10",
          noticeReplyRequired: true,
          noticeReplySent: false,
          noticeResponse: "Send response denying default.",
          sequenceIndex: null,
          linkedCourtOrderId: null,
          hearingId: null,
        }),
      );
    });
  });

  it("uploads a sent notice from the sent tab", async () => {
    useCapabilityMock.mockImplementation((capability: string) =>
      ["documents:upload", "documents:manage"].includes(capability),
    );
    uploadMock.mockResolvedValue({ id: "sent-1" });
    render(withClient(<MatterNoticesPage />));

    await userEvent.click(screen.getByTestId("notice-sent-tab"));
    await userEvent.type(screen.getByTestId("matter-notice-sent-on"), "2026-07-04");
    await userEvent.type(screen.getByTestId("matter-notice-type"), "Recovery notice");
    await userEvent.clear(screen.getByTestId("matter-notice-status"));
    await userEvent.type(screen.getByTestId("matter-notice-status"), "Dispatched");
    await userEvent.type(screen.getByTestId("matter-notice-subject"), "Payment notice");
    await userEvent.type(screen.getByTestId("matter-notice-counsel"), "Rao & Co.");
    await userEvent.type(screen.getByTestId("matter-notice-dispute-amount"), "15000");
    await userEvent.type(screen.getByTestId("matter-notice-recovered-amount"), "2500");
    const file = new File(["sent notice"], "sent-notice.txt", {
      type: "text/plain",
    });
    await userEvent.upload(screen.getByTestId("matter-notice-file-input"), file);

    await waitFor(() => {
      expect(uploadMock).toHaveBeenCalledWith(
        expect.objectContaining({
          matterId: "m1",
          file,
          documentType: "notice",
          documentDate: "2026-07-04",
          noticeDirection: "sent",
          noticeDocumentRole: "notice",
          noticeSentOn: "2026-07-04",
          noticeType: "Recovery notice",
          noticeStatus: "Dispatched",
          noticeSubject: "Payment notice",
          noticeCounselEngaged: "Rao & Co.",
          noticeDisputeAmountMinor: 1500000,
          noticeRecoveredAmountMinor: 250000,
          noticeReplyRequired: false,
        }),
      );
    });
  });

  it("shows a linked standalone notice without duplicating it as a matter attachment", async () => {
    useCapabilityMock.mockImplementation(() => false);
    const firstNotice = {
      id: "global-1",
      source_kind: "standalone",
      read_only: false,
      direction: "received",
      subject: "Global regulator notice",
      type: "Regulatory",
      status: "Open",
      authority: "Regulator",
      received_from: "Portal",
      department: "Compliance",
      mode: "Portal",
      owner_membership_id: null,
      owner_name: null,
      owner_email: null,
      received_on: "2026-07-15",
      sent_on: null,
      reply_due_on: "2026-07-20",
      reply_required: true,
      reply_sent: false,
      reply_sent_on: null,
      summary: "Linked once from the global register.",
      remarks: null,
      response: null,
      internal_spoc: null,
      internal_remarks: null,
      counsel_engaged: null,
      currency: "INR",
      amount_minor: null,
      dispute_amount_minor: null,
      recovered_amount_minor: null,
      matter_links: [
        { matter_id: "m1", matter_code: "N-1", matter_title: "Notice Matter" },
      ],
      filename: "regulator.txt",
      has_file: true,
      content_type: "text/plain",
      size_bytes: 20,
      created_at: "2026-07-15T10:00:00Z",
      updated_at: "2026-07-15T10:00:00Z",
    };
    const firstPageNotices = Array.from({ length: 100 }, (_, index) =>
      index === 0
        ? firstNotice
        : {
            ...firstNotice,
            id: `global-${index + 1}`,
            subject: `Linked notice ${index + 1}`,
            filename: null,
            has_file: false,
          },
    );
    listNoticesMock.mockImplementation(async ({ cursor }: { cursor: string | null }) => {
      if (cursor === "matter-notices-page-2") {
        return {
          notices: [
            {
              ...firstNotice,
              id: "global-101",
              subject: "Later linked notice",
              filename: null,
              has_file: false,
            },
          ],
          total: 101,
          // A bad/repeated backend cursor must not create an infinite loop.
          next_cursor: "matter-notices-page-2",
        };
      }
      return {
        notices: firstPageNotices,
        total: 101,
        next_cursor: "matter-notices-page-2",
      };
    });
    render(withClient(<MatterNoticesPage />));

    expect(await screen.findByTestId("linked-global-notices")).toHaveTextContent(
      "Global regulator notice",
    );
    expect(screen.getByTestId("linked-global-notices")).toHaveTextContent(
      "Later linked notice",
    );
    expect(screen.getAllByTestId(/^matter-global-notice-/)).toHaveLength(101);
    expect(screen.queryByTestId("matter-notice-row")).not.toBeInTheDocument();
    expect(listNoticesMock).toHaveBeenNthCalledWith(1, {
      matter_id: "m1",
      limit: 100,
      cursor: null,
    });
    expect(listNoticesMock).toHaveBeenNthCalledWith(2, {
      matter_id: "m1",
      limit: 100,
      cursor: "matter-notices-page-2",
    });
    expect(listNoticesMock).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("button", { name: "Download linked regulator.txt" }),
    );
    expect(downloadNoticeFileMock).toHaveBeenCalledWith(
      "global-1",
      "regulator.txt",
    );
  });
});
