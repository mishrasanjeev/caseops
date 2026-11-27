import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NoticeRecord } from "@/lib/api/notices";

const {
  createNoticeMock,
  downloadNoticeFileMock,
  getNoticeMock,
  getNoticeUploadPolicyMock,
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
  // The API's allow-list and cap, as GET /api/notices/upload-policy returns them.
  getNoticeUploadPolicyMock: vi.fn(async () => ({
    allowed_upload_extensions: [".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png", ".txt"],
    max_upload_size_bytes: 26214400,
  })),
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
  getNoticeUploadPolicy: getNoticeUploadPolicyMock,
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
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
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
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    expect(await screen.findByText(created.subject)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("create-notice-dialog")).not.toBeInTheDocument(),
    );
    expect(toastSuccessMock).toHaveBeenCalledWith("Notice created.");
  });

  it("keeps a committed notice when an older register read resolves after creation", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const created = notice({
      id: "committed-after-stale-read",
      subject: "Committed after stale register read",
      created_at: "2026-09-03T05:00:00Z",
      updated_at: "2026-09-03T05:00:00Z",
    });
    createNoticeMock.mockResolvedValue(created);
    render(
      <QueryClientProvider client={client}>
        <NoticesPage />
      </QueryClientProvider>,
    );

    await screen.findByText("No received notices");

    let resolveStaleRegister!: (value: {
      notices: NoticeRecord[];
      total: number;
      next_cursor: null;
    }) => void;
    let markStaleRegisterStarted!: () => void;
    const staleRegisterStarted = new Promise<void>((resolve) => {
      markStaleRegisterStarted = resolve;
    });
    listNoticesMock.mockImplementation(
      async (params: { limit?: number; direction?: "received" | "sent" } = {}) => {
        if (params.limit === 100 && params.direction === "received") {
          markStaleRegisterStarted();
          return new Promise((resolve) => {
            resolveStaleRegister = resolve;
          });
        }
        return { notices: [], total: 0, next_cursor: null };
      },
    );
    const staleRefetch = client.refetchQueries({
      queryKey: ["notices", "register"],
    });
    await staleRegisterStarted;

    fireEvent.click(screen.getByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), {
      target: { value: created.subject },
    });
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    const committedRow = await screen.findByTestId(`notice-row-${created.id}`);
    expect(committedRow).toHaveTextContent(created.subject);

    resolveStaleRegister({ notices: [], total: 0, next_cursor: null });
    await staleRefetch;
    await Promise.resolve();
    expect(screen.getByTestId(`notice-row-${created.id}`)).toHaveTextContent(
      created.subject,
    );
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
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /MAT-001/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-002/ }));
    const file = new File(["notice bytes"], "sent-notice.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(within(dialog).getByLabelText("Notice document (optional)"), {
      target: { files: [file] },
    });

    const listCallsBeforeCreate = listNoticesMock.mock.calls.length;
    listNoticesMock.mockImplementation(() => new Promise(() => undefined));
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
    });
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
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
    });
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
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /MAT-001/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /MAT-002/ }));
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
    });
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
    // A notice needs its type (notice_rules); the date defaults to today.
    fireEvent.change(within(dialog).getByLabelText("Notice type"), {
      target: { value: "Legal notice" },
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

    // The matter filter is a server-searched MatterPicker with "All matters".
    const matterFilter = screen.getByLabelText("Filter by matter");
    await waitFor(() => expect(within(matterFilter).getByRole("option", { name: /MAT-001/ })).toBeInTheDocument());
    fireEvent.change(matterFilter, { target: { value: "matter-1" } });
    await screen.findByText("Alpha demand");
    expect(screen.queryByText("Beta summons")).not.toBeInTheDocument();
    fireEvent.change(matterFilter, { target: { value: "" } });
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
    fireEvent.change(within(dialog).getByLabelText("Received on"), {
      target: { value: "2026-07-15" },
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
    listMattersMock.mockImplementation(async ({ q, cursor }: { q?: string; cursor?: string }) =>
      q === "NO SUCH MATTER"
        ? { matters: [], next_cursor: null }
        : q
        ? {
            matters: [
              { id: "matter-101", matter_code: "MAT-101", title: "Later page matter" },
            ],
            next_cursor: null,
          }
        : cursor === "page-2"
          ? { matters: [{ ...matterOptions[0], id: "matter-150", matter_code: "MAT-150", title: "Oldest matter" }], next_cursor: null }
          : { matters: [matterOptions[0]], next_cursor: "page-2" },
    );
    render(withClient(<NoticesPage />));

    fireEvent.click(
      await screen.findByRole("button", { name: "Manage details & links" }),
    );
    const dialog = await screen.findByTestId("create-notice-dialog");
    const first = await within(dialog).findByRole("checkbox", { name: /MAT-001/ });
    expect(first).toBeChecked();
    // B4-ADJ-03: the list states its cap and reaches the next server page.
    expect(within(dialog).getByTestId("notice-matter-count")).toHaveTextContent(
      "Showing the 1 most recently updated matches. Search, or load more.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Load more matters" }));
    expect(await within(dialog).findByRole("checkbox", { name: /MAT-150/ })).toBeVisible();
    expect(listMattersMock).toHaveBeenCalledWith({ limit: 50, q: undefined, cursor: "page-2" });
    expect(within(dialog).getByTestId("notice-matter-count")).toHaveTextContent("2 matters.");
    fireEvent.click(first);
    fireEvent.change(within(dialog).getByLabelText("Search accessible matters"), {
      target: { value: "MAT-101" },
    });
    await within(dialog).findByRole("checkbox", { name: /MAT-101/ });
    // B4-ADJ-03 review: the count is the server's answer for the search; the
    // notice's existing link is listed apart and is not counted as a match.
    expect(within(dialog).getByTestId("notice-matter-count")).toHaveTextContent("1 matter matches this search.");
    const linkedGroup = within(dialog).getByRole("group", { name: "Linked to this notice (1)" });
    expect(within(linkedGroup).getByRole("checkbox", { name: /MAT-001/ })).not.toBeChecked();
    fireEvent.change(within(dialog).getByLabelText("Search accessible matters"), {
      target: { value: "NO SUCH MATTER" },
    });
    expect(await within(dialog).findByText("No accessible matters match this search.")).toBeVisible();
    expect(within(dialog).getByTestId("notice-matter-count")).toHaveTextContent("0 matters match this search.");
    expect(within(linkedGroup).getByRole("checkbox", { name: /MAT-001/ })).toBeVisible();
    fireEvent.change(within(dialog).getByLabelText("Search accessible matters"), {
      target: { value: "MAT-101" },
    });
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /MAT-101/ }));
    fireEvent.change(within(dialog).getByLabelText("Remarks"), {
      target: { value: "Corrected links" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(1));
    expect(listMattersMock).toHaveBeenCalledWith({ limit: 50, q: undefined, cursor: undefined });
    expect(listMattersMock).toHaveBeenCalledWith({ limit: 50, q: "MAT-101", cursor: undefined });
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
    const matterFilter = screen.getByLabelText("Filter by matter");
    await waitFor(() => expect(within(matterFilter).getByRole("option", { name: /MAT-001/ })).toBeInTheDocument());
    fireEvent.change(matterFilter, {
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
  // Aishwarya 2026-11-27 rows 2/3: the register is the second notice writer and
  // must refuse the same incomplete or contradictory notices inline.
  it("refuses an incomplete register notice inline and focuses the first problem", async () => {
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Received on"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByLabelText("Reply required"));
    fireEvent.change(within(dialog).getByLabelText("Amount"), { target: { value: "-10" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    const date = within(dialog).getByLabelText("Received on");
    await waitFor(() => expect(date).toHaveFocus());
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(date).toHaveAttribute("aria-describedby", "new-notice-date-error");
    expect(within(dialog).getByTestId("new-notice-date-error")).toHaveTextContent("Enter the date of receipt.");
    expect(within(dialog).getByTestId("new-notice-subject-error")).toHaveTextContent("Enter the notice subject.");
    expect(within(dialog).getByTestId("new-notice-type-error")).toHaveTextContent("Enter the type of notice.");
    expect(within(dialog).getByTestId("new-notice-amount-error")).toHaveTextContent("Amount cannot be negative.");
    expect(within(dialog).getByTestId("new-notice-reply-due-error")).toHaveTextContent(
      "Enter the reply due date, or clear Reply required.",
    );
    expect(within(dialog).getByTestId("notice-form-error")).toBeInTheDocument();
    expect(createNoticeMock).not.toHaveBeenCalled();
  });

  it("refuses sent recovered above dispute, a future date and an unsupported file", async () => {
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Direction"), { target: { value: "sent" } });
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Recovery" } });
    fireEvent.change(within(dialog).getByLabelText("Notice type"), { target: { value: "Recovery notice" } });
    fireEvent.change(within(dialog).getByLabelText("Sent on"), { target: { value: "2099-01-01" } });
    fireEvent.change(within(dialog).getByLabelText("Dispute amount"), { target: { value: "100" } });
    fireEvent.change(within(dialog).getByLabelText("Recovered amount"), { target: { value: "100.01" } });
    await waitFor(() => expect(getNoticeUploadPolicyMock).toHaveBeenCalled());
    const picker = within(dialog).getByLabelText("Notice document (optional)");
    await waitFor(() => expect(picker).toHaveAttribute("accept", ".doc,.docx,.jpeg,.jpg,.pdf,.png,.txt"));
    fireEvent.change(picker, {
      target: { files: [new File(["MZ"], "notice.exe", { type: "application/octet-stream" })] },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    expect(await within(dialog).findByTestId("new-notice-date-error")).toHaveTextContent(
      "Notice sent date cannot be in the future.",
    );
    expect(within(dialog).getByTestId("new-notice-recovered-amount-error")).toHaveTextContent(
      "Recovered amount cannot exceed the dispute amount.",
    );
    expect(within(dialog).getByTestId("new-notice-file-error")).toHaveTextContent(
      ".exe files are not supported.",
    );
    expect(createNoticeMock).not.toHaveBeenCalled();
  });

  it("shows a duplicate refusal with the existing notice and saves anyway only on request", async () => {
    const { ApiError } = await import("@/lib/api/config");
    createNoticeMock
      .mockRejectedValueOnce(
        new ApiError(409, "A notice with the same direction, date, subject and counterparty already exists.", {
          duplicate_kind: "same_details",
          override_allowed: true,
          existing_notice: { id: "existing-1", subject: "Tax demand", direction: "received", notice_date: "2026-07-10", filename: null },
        }),
      )
      .mockResolvedValueOnce(notice({ id: "second", subject: "Tax demand" }));
    getNoticeMock.mockResolvedValue(notice({ id: "existing-1", subject: "Tax demand" }));
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "New notice" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Tax demand" } });
    fireEvent.change(within(dialog).getByLabelText("Notice type"), { target: { value: "Tax" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create notice" }));

    const panel = await within(dialog).findByTestId("notice-duplicate");
    expect(panel).toHaveTextContent("Existing notice: Tax demand");
    expect(createNoticeMock.mock.calls[0][0].allow_duplicate).toBeUndefined();
    fireEvent.click(within(panel).getByTestId("notice-duplicate-create-anyway"));
    await waitFor(() => expect(createNoticeMock).toHaveBeenCalledTimes(2));
    expect(createNoticeMock.mock.calls[1][0].allow_duplicate).toBe(true);
  });

  it("lets a legacy notice without a date take an unrelated edit, but not a new violation", async () => {
    const legacy = notice({ id: "legacy-1", received_on: null, type: null, reply_required: false, reply_due_on: null });
    mockNoticeRegister([legacy]);
    updateNoticeMock.mockResolvedValue({ ...legacy, status: "Closed" });
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "Manage details & links" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Amount"), { target: { value: "-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByTestId("new-notice-amount-error")).toHaveTextContent(
      "Amount cannot be negative.",
    );
    expect(within(dialog).queryByTestId("new-notice-date-error")).toBeNull();
    expect(updateNoticeMock).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Amount"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(1));
  });

  it("keeps an edit that duplicates another notice open with the match named, and saves anyway only on request", async () => {
    const { ApiError } = await import("@/lib/api/config");
    const editing = notice({ id: "second", subject: "Second demand" });
    mockNoticeRegister([editing]);
    updateNoticeMock
      .mockRejectedValueOnce(
        new ApiError(409, "A notice with the same direction, date, subject and counterparty already exists.", {
          duplicate_kind: "same_details",
          override_allowed: true,
          existing_notice: { id: "existing-1", subject: "Income tax demand", direction: "received", notice_date: "2026-07-10", filename: null, source_kind: "standalone", matter_id: null },
        }),
      )
      .mockResolvedValueOnce({ ...editing, subject: "Income tax demand" });
    getNoticeMock.mockResolvedValue(notice({ id: "existing-1" }));
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "Manage details & links" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Income tax demand" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    // The refusal stays in the dialog with the user's edit, not as a toast.
    const panel = await within(dialog).findByTestId("notice-duplicate");
    expect(panel).toHaveTextContent("A notice with the same direction, date, subject and counterparty already exists.");
    expect(panel).toHaveTextContent("Existing notice: Income tax demand");
    expect(within(dialog).getByLabelText("Subject")).toHaveValue("Income tax demand");
    expect(updateNoticeMock.mock.calls[0][1].allow_duplicate).toBeUndefined();
    expect(updateNoticeMock.mock.calls[0][1].expected_updated_at).toBe(editing.updated_at);
    expect(getNoticeMock).not.toHaveBeenCalled();

    fireEvent.click(within(panel).getByRole("button", { name: "Save changes anyway" }));
    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(2));
    expect(updateNoticeMock.mock.calls[1][0]).toBe("second");
    expect(updateNoticeMock.mock.calls[1][1]).toMatchObject({ subject: "Income tax demand", allow_duplicate: true });
    await waitFor(() => expect(screen.queryByTestId("create-notice-dialog")).toBeNull());
  });

  it("opens the notice named by ?notice= (the matter Notices duplicate link)", async () => {
    window.history.pushState({}, "", "/app/notices?notice=existing-1");
    try {
      mockNoticeRegister([]);
      getNoticeMock.mockResolvedValue(notice({ id: "existing-1", subject: "Linked register notice" }));
      render(withClient(<NoticesPage />));
      const dialog = await screen.findByTestId("create-notice-dialog");
      expect(getNoticeMock).toHaveBeenCalledWith("existing-1");
      expect(within(dialog).getByLabelText("Subject")).toHaveValue("Linked register notice");
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  it("opens a matched register notice in place and a matched matter notice on its matter", async () => {
    const { ApiError } = await import("@/lib/api/config");
    const editing = notice({ id: "second", subject: "Second demand" });
    mockNoticeRegister([editing]);
    const refusal = (existing: Record<string, unknown>) =>
      new ApiError(409, "A notice with the same direction, date, subject and counterparty already exists.", {
        duplicate_kind: "same_details",
        override_allowed: true,
        existing_notice: { subject: "Income tax demand", direction: "received", notice_date: "2026-07-10", filename: "n.pdf", ...existing },
      });
    updateNoticeMock
      .mockRejectedValueOnce(refusal({ id: "attachment-9", source_kind: "legacy_attachment", matter_id: "matter-7" }))
      .mockRejectedValueOnce(refusal({ id: "existing-1", source_kind: "standalone", matter_id: null }));
    getNoticeMock.mockResolvedValue(notice({ id: "existing-1", subject: "Income tax demand" }));
    render(withClient(<NoticesPage />));
    fireEvent.click(await screen.findByRole("button", { name: "Manage details & links" }));
    const dialog = await screen.findByTestId("create-notice-dialog");
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Income tax demand" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    const legacyOpen = await within(dialog).findByTestId("notice-duplicate-open");
    expect(legacyOpen).toHaveAttribute("href", "/app/matters/matter-7/documents/attachment-9/view");

    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateNoticeMock).toHaveBeenCalledTimes(2));
    const registerOpen = await within(dialog).findByRole("button", { name: "Open the existing notice" });
    fireEvent.click(registerOpen);
    await waitFor(() => expect(getNoticeMock).toHaveBeenCalledWith("existing-1"));
    await waitFor(() => expect(within(screen.getByTestId("create-notice-dialog")).getByLabelText("Subject")).toHaveValue("Income tax demand"));
  });
});

