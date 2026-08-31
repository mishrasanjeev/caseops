import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NoticeRecord } from "@/lib/api/notices";

const {
  createNoticeMock,
  downloadNoticeFileMock,
  getNoticeMock,
  getStoredContextMock,
  listNoticeOwnersMock,
  listMattersMock,
  listNoticesMock,
  toastErrorMock,
  toastSuccessMock,
  updateNoticeMock,
  uploadNoticeFileMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createNoticeMock: vi.fn(),
  downloadNoticeFileMock: vi.fn(),
  getNoticeMock: vi.fn(),
  getStoredContextMock: vi.fn(),
  listNoticeOwnersMock: vi.fn(),
  listMattersMock: vi.fn(),
  listNoticesMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
  updateNoticeMock: vi.fn(),
  uploadNoticeFileMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/notices", () => ({
  createNotice: createNoticeMock,
  downloadNoticeFile: downloadNoticeFileMock,
  getNotice: getNoticeMock,
  listNotices: listNoticesMock,
  listNoticeOwners: listNoticeOwnersMock,
  updateNotice: updateNoticeMock,
  uploadNoticeFile: uploadNoticeFileMock,
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatters: listMattersMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("@/lib/session", () => ({
  getStoredContext: getStoredContextMock,
}));

vi.mock("sonner", () => ({
  toast: { error: toastErrorMock, success: toastSuccessMock },
}));

import NoticesPage from "@/app/app/notices/page";

function notice(overrides: Partial<NoticeRecord> = {}): NoticeRecord {
  return {
    id: "notice-1",
    source_kind: "standalone",
    read_only: false,
    direction: "received",
    subject: "Income tax demand",
    type: "Tax",
    status: "Open",
    authority: "Income Tax Department",
    received_from: "Assessing Officer",
    department: "Tax",
    mode: "Email",
    owner_membership_id: "owner-1",
    owner_name: "Asha Rao",
    owner_email: "asha@example.test",
    received_on: "2026-07-10",
    sent_on: null,
    reply_due_on: "2026-07-20",
    reply_required: true,
    reply_sent: false,
    reply_sent_on: null,
    summary: "Demand for assessment year 2025-26.",
    remarks: null,
    response: null,
    internal_spoc: null,
    internal_remarks: null,
    counsel_engaged: null,
    currency: "INR",
    amount_minor: null,
    dispute_amount_minor: null,
    recovered_amount_minor: null,
    matter_links: [],
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_at: "2026-07-10T09:00:00Z",
    updated_at: "2026-07-10T09:00:00Z",
    ...overrides,
  };
}

function mockNoticeRegister(records: NoticeRecord[]) {
  listNoticesMock.mockImplementation(
    async (
      params: {
        limit?: number;
        cursor?: string | null;
        query?: string;
        direction?: "received" | "sent";
        status?: string;
        matter_id?: string;
        owner_membership_id?: string;
        due_from?: string;
        due_to?: string;
      } = {},
    ) => {
      let filtered = records;
      if (params.direction) {
        filtered = filtered.filter((item) => item.direction === params.direction);
      }
      if (params.status) {
        filtered = filtered.filter((item) => item.status === params.status);
      }
      if (params.matter_id) {
        filtered = filtered.filter((item) =>
          item.matter_links.some((matter) => matter.matter_id === params.matter_id),
        );
      }
      if (params.owner_membership_id) {
        filtered = filtered.filter(
          (item) => item.owner_membership_id === params.owner_membership_id,
        );
      }
      if (params.due_from) {
        filtered = filtered.filter(
          (item) => Boolean(item.reply_due_on && item.reply_due_on >= params.due_from!),
        );
      }
      if (params.due_to) {
        filtered = filtered.filter(
          (item) => Boolean(item.reply_due_on && item.reply_due_on <= params.due_to!),
        );
      }
      if (params.query) {
        const query = params.query.toLowerCase();
        filtered = filtered.filter((item) =>
          [
            item.subject,
            item.authority,
            item.owner_name,
            ...item.matter_links.flatMap((matter) => [
              matter.matter_code,
              matter.matter_title,
            ]),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(query),
        );
      }
      return {
        notices: filtered.slice(0, params.limit ?? 100),
        total: filtered.length,
        next_cursor: null,
      };
    },
  );
}

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const matterOptions = [
  { id: "matter-1", matter_code: "MAT-001", title: "Alpha v State" },
  { id: "matter-2", matter_code: "MAT-002", title: "Beta v Board" },
];

describe("centralized notice management", () => {
  beforeEach(() => {
    createNoticeMock.mockReset();
    downloadNoticeFileMock.mockReset();
    getNoticeMock.mockReset();
    getStoredContextMock.mockReset();
    listNoticeOwnersMock.mockReset();
    listMattersMock.mockReset();
    listNoticesMock.mockReset();
    toastErrorMock.mockReset();
    toastSuccessMock.mockReset();
    updateNoticeMock.mockReset();
    uploadNoticeFileMock.mockReset();
    useCapabilityMock.mockReset();

    useCapabilityMock.mockReturnValue(true);
    mockNoticeRegister([]);
    listMattersMock.mockResolvedValue({ matters: matterOptions, next_cursor: null });
    listNoticeOwnersMock.mockResolvedValue([
      {
        membership_id: "owner-1",
        name: "Asha Rao",
        email: "asha@example.test",
      },
      {
        membership_id: "owner-2",
        name: "Vikram Sen",
        email: "vikram@example.test",
      },
    ]);
    createNoticeMock.mockResolvedValue(notice());
    uploadNoticeFileMock.mockResolvedValue(
      notice({ filename: "notice.pdf", has_file: true }),
    );
    updateNoticeMock.mockResolvedValue(notice());
    downloadNoticeFileMock.mockResolvedValue(undefined);
    getNoticeMock.mockResolvedValue(notice());
    getStoredContextMock.mockReturnValue(null);
  });

  it("creates a standalone received notice without forcing a matter or owner", async () => {
    render(withClient(<NoticesPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: "Standalone regulator notice" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    await waitFor(() => expect(createNoticeMock).toHaveBeenCalledTimes(1));
    expect(createNoticeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: "received",
        subject: "Standalone regulator notice",
        matter_ids: [],
        owner_membership_id: null,
      }),
    );
    expect(uploadNoticeFileMock).not.toHaveBeenCalled();
  });

  it("shows a committed notice and closes the dialog while register reconciliation is slow", async () => {
    const created = notice({
      id: "committed-notice",
      subject: "Committed production notice",
      created_at: "2026-08-02T09:00:00Z",
      updated_at: "2026-08-02T09:00:00Z",
    });
    createNoticeMock.mockResolvedValue(created);
    render(withClient(<NoticesPage />));

    await screen.findByText("No received notices");
    fireEvent.click(screen.getByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: created.subject },
    });

    // Reconciliation can be materially slower than the successful mutation in
    // a production-shaped register. A committed record must still be visible.
    listNoticesMock.mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    expect(await screen.findByText(created.subject)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("create-notice-dialog")).not.toBeInTheDocument(),
    );
    expect(toastSuccessMock).toHaveBeenCalledWith("Notice created.");
  });

  it("keeps a committed sent notice visible across tabs while reconciliation is slow", async () => {
    const created = notice({
      id: "committed-sent-notice",
      direction: "sent",
      subject: "Committed sent production notice",
      received_on: null,
      sent_on: "2026-08-02",
      matter_links: [
        { matter_id: "matter-1", matter_code: "MAT-001", matter_title: "Alpha v State" },
        { matter_id: "matter-2", matter_code: "MAT-002", matter_title: "Beta v Board" },
      ],
      filename: null,
      has_file: false,
      created_at: "2026-08-02T09:00:00Z",
      updated_at: "2026-08-02T09:00:00Z",
    });
    const uploaded = notice({
      ...created,
      filename: "sent-notice.pdf",
      has_file: true,
      content_type: "application/pdf",
      size_bytes: 12,
      updated_at: "2026-08-02T09:01:00Z",
    });
    createNoticeMock.mockResolvedValue(created);
    uploadNoticeFileMock.mockResolvedValue(uploaded);
    render(withClient(<NoticesPage />));

    await screen.findByText("No received notices");
    fireEvent.click(screen.getByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Direction"), {
      target: { value: "sent" },
    });
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: uploaded.subject },
    });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-001/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-002/ }));
    const file = new File(["notice bytes"], "sent-notice.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(within(dialog).getByLabelText("Notice document (optional)"), {
      target: { files: [file] },
    });

    const listCallsBeforeCreate = listNoticesMock.mock.calls.length;
    listNoticesMock.mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    await waitFor(() => expect(uploadNoticeFileMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByTestId("create-notice-dialog")).not.toBeInTheDocument(),
    );
    expect(listNoticesMock).toHaveBeenCalledTimes(listCallsBeforeCreate);

    fireEvent.click(screen.getByTestId("notices-sent-tab"));
    const sentRow = await screen.findByTestId(`notice-row-${uploaded.id}`);
    expect(sentRow).toHaveTextContent(uploaded.subject);
    expect(sentRow).toHaveTextContent("MAT-001");
    expect(sentRow).toHaveTextContent("MAT-002");
    expect(
      within(sentRow).getByRole("button", { name: "Download sent-notice.pdf" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(listNoticesMock).toHaveBeenCalledTimes(listCallsBeforeCreate + 1),
    );
  });

  it("keeps a file-less committed notice actionable when its upload fails", async () => {
    const created = notice({
      id: "upload-failed-notice",
      subject: "Committed notice with failed upload",
      filename: null,
      has_file: false,
      created_at: "2026-08-02T10:00:00Z",
      updated_at: "2026-08-02T10:00:00Z",
    });
    createNoticeMock.mockResolvedValue(created);
    uploadNoticeFileMock.mockRejectedValue(new Error("scanner unavailable"));
    render(withClient(<NoticesPage />));

    await screen.findByText("No received notices");
    fireEvent.click(screen.getByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: created.subject },
    });
    fireEvent.change(within(dialog).getByLabelText("Notice document (optional)"), {
      target: {
        files: [
          new File(["notice bytes"], "failed-upload.pdf", {
            type: "application/pdf",
          }),
        ],
      },
    });

    listNoticesMock.mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    const row = await screen.findByTestId(`notice-row-${created.id}`);
    expect(row).toHaveTextContent(created.subject);
    expect(
      within(row).getByRole("button", {
        name: `Attach document for ${created.subject}`,
      }),
    ).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Download/i })).toBeNull();
    expect(toastErrorMock).toHaveBeenCalledWith(
      expect.stringContaining("Notice saved, but its document was not attached"),
    );
  });

  it("creates a sent notice linked to multiple matters with an optional owner", async () => {
    render(withClient(<NoticesPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
    await waitFor(() => expect(listNoticeOwnersMock).toHaveBeenCalled());

    fireEvent.change(within(dialog).getByLabelText("Direction"), {
      target: { value: "sent" },
    });
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: "Reply to show-cause notice" },
    });
    fireEvent.change(within(dialog).getByLabelText("Owner"), {
      target: { value: "owner-2" },
    });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-001/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-002/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    await waitFor(() => expect(createNoticeMock).toHaveBeenCalledTimes(1));
    expect(createNoticeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: "sent",
        owner_membership_id: "owner-2",
        matter_ids: ["matter-1", "matter-2"],
        received_on: null,
        sent_on: expect.any(String),
      }),
    );
  });

  it("saves JSON before uploading an optional file to the created notice id", async () => {
    const order: string[] = [];
    const created = notice({ id: "created-id" });
    createNoticeMock.mockImplementation(async () => {
      order.push("create");
      return created;
    });
    uploadNoticeFileMock.mockImplementation(async () => {
      order.push("upload");
      return notice({ id: "created-id", filename: "demand.pdf", has_file: true });
    });
    render(withClient(<NoticesPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: "Notice with document" },
    });
    const file = new File(["test"], "demand.pdf", { type: "application/pdf" });
    fireEvent.change(within(dialog).getByLabelText("Notice document (optional)"), {
      target: { files: [file] },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    await waitFor(() => expect(uploadNoticeFileMock).toHaveBeenCalledTimes(1));
    expect(uploadNoticeFileMock).toHaveBeenCalledWith(
      "created-id",
      file,
      "2026-07-10T09:00:00Z",
    );
    expect(order).toEqual(["create", "upload"]);
  });

  it("searches and filters the register by direction, status, matter, owner, and due date", async () => {
    mockNoticeRegister([
        notice({
          id: "alpha",
          subject: "Alpha demand",
          matter_links: [
            { matter_id: "matter-1", matter_code: "MAT-001", matter_title: "Alpha v State" },
          ],
        }),
        notice({
          id: "beta",
          subject: "Beta summons",
          status: "Closed",
          owner_membership_id: "owner-2",
          owner_name: "Vikram Sen",
          reply_due_on: "2026-08-20",
          matter_links: [
            { matter_id: "matter-2", matter_code: "MAT-002", matter_title: "Beta v Board" },
          ],
        }),
        notice({
          id: "sent",
          direction: "sent",
          subject: "Outbound response",
          received_on: null,
          sent_on: "2026-07-12",
          reply_required: false,
          reply_due_on: null,
        }),
    ]);
    render(withClient(<NoticesPage />));

    expect(await screen.findByText("Alpha demand")).toBeInTheDocument();
    expect(screen.getByText("Beta summons")).toBeInTheDocument();
    expect(screen.queryByText("Outbound response")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "Alpha" } });
    await screen.findByText("Alpha demand");
    expect(screen.queryByText("Beta summons")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await screen.findByText("Beta summons");

    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "Closed" } });
    await screen.findByText("Beta summons");
    expect(screen.queryByText("Alpha demand")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "" } });
    await screen.findByText("Alpha demand");

    fireEvent.change(screen.getByLabelText("Filter by matter"), { target: { value: "matter-1" } });
    await screen.findByText("Alpha demand");
    expect(screen.queryByText("Beta summons")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by matter"), { target: { value: "all" } });
    await screen.findByText("Beta summons");

    fireEvent.change(screen.getByLabelText("Filter by owner"), { target: { value: "owner-2" } });
    await screen.findByText("Beta summons");
    expect(screen.queryByText("Alpha demand")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by owner"), { target: { value: "all" } });
    await screen.findByText("Alpha demand");

    fireEvent.change(screen.getByLabelText("Due from"), {
      target: { value: "2026-07-01" },
    });
    await screen.findByText("Alpha demand");
    fireEvent.change(screen.getByLabelText("Due to"), {
      target: { value: "2026-07-31" },
    });
    await screen.findByText("Alpha demand");
    expect(screen.queryByText("Beta summons")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    fireEvent.click(await screen.findByTestId("notices-sent-tab"));
    await screen.findByText("Outbound response");
    expect(screen.queryByText("Alpha demand")).not.toBeInTheDocument();
  });

  it("renders legacy matter attachments as explicitly read-only with matter and file links", async () => {
    mockNoticeRegister([
        notice({
          id: "legacy-1",
          source_kind: "legacy_attachment",
          read_only: true,
          subject: "Legacy excise notice",
          filename: "legacy.pdf",
          has_file: true,
          matter_links: [
            { matter_id: "matter-1", matter_code: "MAT-001", matter_title: "Alpha v State" },
          ],
        }),
    ]);
    render(withClient(<NoticesPage />));

    expect(await screen.findByText("Legacy excise notice")).toBeInTheDocument();
    expect(screen.getByText(/Legacy matter attachment - read-only/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[\u00c2\u00e2\ufffd]/);
    expect(screen.queryByLabelText("Status for Legacy excise notice")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Owner for Legacy excise notice")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /MAT-001/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1",
    );
    expect(screen.getByRole("button", { name: "Download legacy.pdf" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Replace document for Legacy excise notice/ }),
    ).not.toBeInTheDocument();
  });

  it("lets an uploader recover a file-less standalone notice by attaching a document", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "documents:upload",
    );
    mockNoticeRegister([notice({ filename: null, has_file: false })]);
    render(withClient(<NoticesPage />));

    expect(
      await screen.findByRole("button", {
        name: "Attach document for Income tax demand",
      }),
    ).toBeInTheDocument();
    const file = new File(["recovery"], "recovery.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Document for Income tax demand"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(uploadNoticeFileMock).toHaveBeenCalledTimes(1));
    expect(uploadNoticeFileMock).toHaveBeenCalledWith(
      "notice-1",
      file,
      "2026-07-10T09:00:00Z",
    );
  });

  it("offers replacement only when an uploader also has document management permission", async () => {
    mockNoticeRegister([notice({ filename: "current.pdf", has_file: true })]);
    render(withClient(<NoticesPage />));

    expect(
      await screen.findByRole("button", {
        name: "Replace document for Income tax demand",
      }),
    ).toBeInTheDocument();
    const file = new File(["replacement"], "replacement.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Document for Income tax demand"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(uploadNoticeFileMock).toHaveBeenCalledTimes(1));
    expect(uploadNoticeFileMock).toHaveBeenCalledWith(
      "notice-1",
      file,
      "2026-07-10T09:00:00Z",
    );
  });

  it("does not expose file replacement to upload-only users", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "documents:upload",
    );
    mockNoticeRegister([notice({ filename: "current.pdf", has_file: true })]);
    render(withClient(<NoticesPage />));

    expect(await screen.findByText("Income tax demand")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Replace document for Income tax demand",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download current.pdf" })).toBeInTheDocument();
  });

  it("uses capability-driven read-only behavior without probing the employee directory", async () => {
    useCapabilityMock.mockReturnValue(false);
    mockNoticeRegister([notice()]);
    render(withClient(<NoticesPage />));

    expect(await screen.findByTestId("notices-read-only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New notice" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Status for Income tax demand")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Owner for Income tax demand")).not.toBeInTheDocument();
    expect(listNoticeOwnersMock).not.toHaveBeenCalled();
  });

  it("tracks status changes through PATCH for editable standalone records", async () => {
    mockNoticeRegister([notice()]);
    render(withClient(<NoticesPage />));

    fireEvent.change(await screen.findByLabelText("Status for Income tax demand"), {
      target: { value: "Under Review" },
    });

    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(1));
    expect(updateNoticeMock).toHaveBeenCalledWith("notice-1", {
      status: "Under Review",
      expected_updated_at: "2026-07-10T09:00:00Z",
    });
  });

  it("re-enables row controls after PATCH even while background refresh is slow", async () => {
    mockNoticeRegister([notice()]);
    let resolveUpdate!: (record: NoticeRecord) => void;
    updateNoticeMock.mockImplementationOnce(
      () =>
        new Promise<NoticeRecord>((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    render(withClient(<NoticesPage />));

    const status = await screen.findByLabelText("Status for Income tax demand");
    fireEvent.change(status, { target: { value: "Under Review" } });
    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(1));
    expect(status).toBeDisabled();

    listNoticesMock.mockImplementation(
      () => new Promise(() => undefined),
    );
    resolveUpdate(notice({ status: "Under Review" }));

    await waitFor(() => expect(status).toBeEnabled());
    expect(status).toHaveValue("Under Review");
  });

  it("submits every standalone metadata family from the create form", async () => {
    render(withClient(<NoticesPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: "Complete tax demand" },
    });
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Tax" },
    });
    fireEvent.change(within(dialog).getByLabelText("Mode"), {
      target: { value: "Portal" },
    });
    fireEvent.change(within(dialog).getByLabelText("Internal SPOC"), {
      target: { value: "Asha" },
    });
    fireEvent.change(within(dialog).getByLabelText("Amount"), {
      target: { value: "1250.50" },
    });
    fireEvent.click(within(dialog).getByLabelText("Reply required"));
    fireEvent.change(within(dialog).getByLabelText("Reply due on"), {
      target: { value: "2026-07-30" },
    });
    fireEvent.click(within(dialog).getByLabelText("Reply sent"));
    fireEvent.change(within(dialog).getByLabelText("Reply sent on"), {
      target: { value: "2026-07-20" },
    });
    fireEvent.change(within(dialog).getByLabelText("Response / reply plan"), {
      target: { value: "File a reasoned response" },
    });
    fireEvent.change(within(dialog).getByLabelText("Remarks"), {
      target: { value: "Externally shared" },
    });
    fireEvent.change(within(dialog).getByLabelText("Internal remarks"), {
      target: { value: "Privilege applies" },
    });
    fireEvent.change(within(dialog).getByLabelText("Counsel engaged"), {
      target: { value: "Rao & Co" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    await waitFor(() => expect(createNoticeMock).toHaveBeenCalledTimes(1));
    expect(createNoticeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        subject: "Complete tax demand",
        type: "Tax",
        mode: "Portal",
        internal_spoc: "Asha",
        amount_minor: 125050,
        reply_required: true,
        reply_due_on: "2026-07-30",
        reply_sent: true,
        reply_sent_on: "2026-07-20",
        response: "File a reasoned response",
        remarks: "Externally shared",
        internal_remarks: "Privilege applies",
        counsel_engaged: "Rao & Co",
      }),
    );
  });

  it("searches bounded matter options and preserves multi-link CAS edits", async () => {
    mockNoticeRegister([
        notice({
          matter_links: [
            {
              matter_id: "matter-1",
              matter_code: "MAT-001",
              matter_title: "Alpha v State",
            },
          ],
        }),
    ]);
    listMattersMock.mockImplementation(async ({ q }: { q?: string }) =>
      q
        ? {
            matters: [
              { id: "matter-101", matter_code: "MAT-101", title: "Later page matter" },
            ],
            next_cursor: null,
          }
        : { matters: [matterOptions[0]], next_cursor: "page-2" },
    );
    render(withClient(<NoticesPage />));

    fireEvent.click(
      await screen.findByRole("button", { name: "Manage details & links" }),
    );
    const dialog = await screen.findByTestId("create-notice-dialog");
    const first = await within(dialog).findByRole("checkbox", { name: /MAT-001/ });
    expect(first).toBeChecked();
    fireEvent.click(first);
    fireEvent.change(within(dialog).getByLabelText("Search accessible matters"), {
      target: { value: "MAT-101" },
    });
    const later = await within(dialog).findByRole("checkbox", { name: /MAT-101/ });
    fireEvent.click(later);
    fireEvent.change(within(dialog).getByLabelText("Remarks"), {
      target: { value: "Corrected links" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(1));
    expect(listMattersMock).toHaveBeenNthCalledWith(1, { limit: 100, q: undefined });
    expect(listMattersMock).toHaveBeenLastCalledWith({
      limit: 100,
      q: "MAT-101",
    });
    expect(updateNoticeMock).toHaveBeenCalledWith(
      "notice-1",
      expect.objectContaining({
        matter_ids: ["matter-101"],
        remarks: "Corrected links",
        expected_updated_at: "2026-07-10T09:00:00Z",
      }),
    );
  });

  it("lets a Partner use the notice owner directory without employee-admin permission", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) =>
        capability === "documents:upload" || capability === "documents:manage",
    );
    mockNoticeRegister([notice()]);
    render(withClient(<NoticesPage />));

    const owner = await screen.findByLabelText("Owner for Income tax demand");
    expect(owner).toBeEnabled();
    expect(owner).toHaveTextContent("Asha Rao");
    expect(owner).toHaveTextContent("Vikram Sen");
    expect(listNoticeOwnersMock).toHaveBeenCalledTimes(1);
  });

  it("limits an upload-only creator to self-assignment without probing owners", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "documents:upload",
    );
    getStoredContextMock.mockReturnValue({
      membership: { id: "self-membership" },
      user: { full_name: "Hari Gupta" },
    });
    render(withClient(<NoticesPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const owner = within(await screen.findByTestId("create-notice-dialog")).getByLabelText(
      "Owner",
    );
    expect(owner).toBeEnabled();
    expect(owner).toHaveTextContent("Hari Gupta");
    expect(owner).not.toHaveTextContent("Vikram Sen");
    expect(listNoticeOwnersMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("notice-owner-filter-scope")).toHaveTextContent(
      "limited to you and owners in the loaded results",
    );
  });

  it("sends every register filter to page one and displays the server total", async () => {
    const firstPageOnly = notice({
      id: "unfiltered-first-page",
      subject: "Unfiltered first-page row",
      matter_links: [
        { matter_id: "matter-1", matter_code: "MAT-001", matter_title: "Alpha v State" },
      ],
    });
    const serverMatch = notice({
      id: "deep-server-match",
      subject: "Deep server match",
      status: "Awaiting tribunal review",
      owner_membership_id: "owner-2",
      owner_name: "Vikram Sen",
      reply_due_on: "2026-07-15",
      matter_links: [
        { matter_id: "matter-1", matter_code: "MAT-001", matter_title: "Alpha v State" },
      ],
    });
    listNoticesMock.mockImplementation(async (params: Record<string, unknown>) => {
      if (params.limit === 1) {
        return { notices: [], total: 1, next_cursor: null };
      }
      const finalFilter =
        params.query === "deep server" &&
        params.status === "Awaiting tribunal review" &&
        params.matter_id === "matter-1" &&
        params.owner_membership_id === "owner-2" &&
        params.due_from === "2026-07-01" &&
        params.due_to === "2026-07-31";
      return finalFilter
        ? { notices: [serverMatch], total: 41, next_cursor: "filtered-next" }
        : { notices: [firstPageOnly], total: 1000, next_cursor: "unfiltered-next" };
    });
    render(withClient(<NoticesPage />));

    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "deep server" },
    });
    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Filter by status"), {
      target: { value: "Awaiting tribunal review" },
    });
    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Filter by matter"), {
      target: { value: "matter-1" },
    });
    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Filter by owner"), {
      target: { value: "owner-2" },
    });
    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Due from"), {
      target: { value: "2026-07-01" },
    });
    await screen.findByText("Unfiltered first-page row");
    fireEvent.change(screen.getByLabelText("Due to"), {
      target: { value: "2026-07-31" },
    });

    await waitFor(() =>
      expect(listNoticesMock).toHaveBeenCalledWith(
        {
          limit: 100,
          cursor: null,
          direction: "received",
          query: "deep server",
          status: "Awaiting tribunal review",
          matter_id: "matter-1",
          owner_membership_id: "owner-2",
          due_from: "2026-07-01",
          due_to: "2026-07-31",
        },
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
    expect(await screen.findByText("Deep server match")).toBeInTheDocument();
    expect(screen.queryByText("Unfiltered first-page row")).not.toBeInTheDocument();
    expect(screen.getByTestId("notice-summary-matching-results")).toHaveTextContent(
      "41",
    );
    expect(screen.getByTestId("notice-summary-rows-loaded")).toHaveTextContent("1");
    expect(screen.getByText("1 of 41 loaded")).toBeInTheDocument();
  });

  it("loads later cursor pages without silently truncating the register", async () => {
    listNoticesMock.mockImplementation(
      async ({
        cursor,
        direction,
        limit,
        query,
      }: {
        cursor?: string | null;
        direction?: "received" | "sent";
        limit?: number;
        query?: string;
      }) => {
        if (limit === 1) {
          return {
            notices: [],
            total: direction === "received" ? 101 : 0,
            next_cursor: null,
          };
        }
        if (query === "server-only match") {
          return {
            notices: [
              notice({ id: "notice-filtered", subject: "Server-only match" }),
            ],
            total: 1,
            next_cursor: null,
          };
        }
        return cursor
          ? {
              notices: [notice({ id: "notice-101", subject: "Later page notice" })],
              total: 101,
              next_cursor: null,
            }
          : {
              notices: [notice({ id: "notice-1", subject: "First page notice" })],
              total: 101,
              next_cursor: "notice-page-2",
            };
      },
    );
    render(withClient(<NoticesPage />));

    expect(await screen.findByText("First page notice")).toBeInTheDocument();
    expect(screen.queryByText("Later page notice")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more notices" }));

    expect(await screen.findByText("Later page notice")).toBeInTheDocument();
    expect(listNoticesMock).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 100,
        cursor: "notice-page-2",
        direction: "received",
      }),
      expect.objectContaining({ signal: expect.anything() }),
    );

    // Changing a server filter creates a new query key: the old first and
    // second cursor pages must disappear, and the replacement starts at a
    // null cursor rather than continuing the stale chain.
    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "server-only match" },
    });
    expect(await screen.findByText("Server-only match")).toBeInTheDocument();
    expect(screen.queryByText("First page notice")).not.toBeInTheDocument();
    expect(screen.queryByText("Later page notice")).not.toBeInTheDocument();
    expect(listNoticesMock).toHaveBeenCalledWith(
      {
        limit: 100,
        cursor: null,
        direction: "received",
        query: "server-only match",
        status: undefined,
        matter_id: undefined,
        owner_membership_id: undefined,
        due_from: undefined,
        due_to: undefined,
      },
      expect.objectContaining({ signal: expect.anything() }),
    );
  });
});
