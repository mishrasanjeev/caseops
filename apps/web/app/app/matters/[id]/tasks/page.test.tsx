import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createMatterDeadlineMock,
  createMatterTaskMock,
  listMatterDeadlinesMock,
  listMatterTasksMock,
  updateMatterDeadlineMock,
  updateMatterTaskMock,
  useMatterWorkspaceMock,
} = vi.hoisted(() => ({
  createMatterDeadlineMock: vi.fn(),
  createMatterTaskMock: vi.fn(),
  listMatterDeadlinesMock: vi.fn(),
  listMatterTasksMock: vi.fn(),
  updateMatterDeadlineMock: vi.fn(),
  updateMatterTaskMock: vi.fn(),
  useMatterWorkspaceMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterDeadline: createMatterDeadlineMock,
  createMatterTask: createMatterTaskMock,
  listMatterDeadlines: listMatterDeadlinesMock,
  listMatterTasks: listMatterTasksMock,
  updateMatterDeadline: updateMatterDeadlineMock,
  updateMatterTask: updateMatterTaskMock,
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import MatterTasksPage from "@/app/app/matters/[id]/tasks/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const WORKSPACE = {
  matter: { id: "m-1", title: "Matter", matter_code: "M-1", status: "intake" },
  assignee: null,
  available_assignees: [
    {
      membership_id: "mem-1",
      user_id: "u-1",
      full_name: "Aditi Associate",
      email: "aditi@example.com",
      role: "member",
      is_active: true,
    },
  ],
  hearings: [],
  attachments: [],
  invoices: [],
  time_entries: [],
  activity: [],
  tasks: [],
  notes: [],
  court_orders: [],
  cause_list_entries: [],
};

const TASKS = {
  matter_id: "m-1",
  tasks: [
    {
      id: "task-1",
      matter_id: "m-1",
      created_by_membership_id: "mem-owner",
      created_by_name: "Owner",
      owner_membership_id: "mem-1",
      owner_name: "Aditi Associate",
      title: "Draft rejoinder",
      description: null,
      due_on: "2026-05-20",
      status: "todo",
      priority: "high",
      source_type: "user",
      source_ref_id: null,
      source_label: null,
      completed_at: null,
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
    },
    {
      id: "task-2",
      matter_id: "m-1",
      created_by_membership_id: null,
      created_by_name: null,
      owner_membership_id: null,
      owner_name: null,
      title: "File reply affidavit",
      description: null,
      due_on: "2026-05-21",
      status: "todo",
      priority: "medium",
      source_type: "proceeding_intelligence",
      source_ref_id: "signal-1",
      source_label: "reply_affidavit_deadline",
      completed_at: null,
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
    },
  ],
};

const DEADLINES = {
  matter_id: "m-1",
  deadlines: [
    {
      id: "deadline-1",
      matter_id: "m-1",
      source: "proceeding",
      kind: "reply_due",
      title: "Reply affidavit due",
      notes: null,
      due_on: "2026-05-21",
      status: "open",
      assignee_membership_id: null,
      source_ref_type: "matter_proceeding_signal",
      source_ref_id: "signal-1",
      created_by_membership_id: null,
      completed_at: null,
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
    },
  ],
};

describe("MatterTasksPage", () => {
  beforeEach(() => {
    useMatterWorkspaceMock.mockReset();
    listMatterTasksMock.mockReset();
    listMatterDeadlinesMock.mockReset();
    createMatterTaskMock.mockReset();
    createMatterDeadlineMock.mockReset();
    updateMatterTaskMock.mockReset();
    updateMatterDeadlineMock.mockReset();

    useMatterWorkspaceMock.mockReturnValue({ data: WORKSPACE });
    listMatterTasksMock.mockResolvedValue(TASKS);
    listMatterDeadlinesMock.mockResolvedValue(DEADLINES);
    createMatterTaskMock.mockResolvedValue(TASKS.tasks[0]);
    createMatterDeadlineMock.mockResolvedValue(DEADLINES.deadlines[0]);
    updateMatterTaskMock.mockResolvedValue({
      ...TASKS.tasks[0],
      status: "completed",
      completed_at: "2026-05-16T01:00:00Z",
    });
    updateMatterDeadlineMock.mockResolvedValue({
      ...DEADLINES.deadlines[0],
      status: "done",
      completed_at: "2026-05-16T01:00:00Z",
    });
  });

  it("renders user-created and source-backed tasks and deadlines", async () => {
    render(withClient(<MatterTasksPage />));

    expect(await screen.findByText("Draft rejoinder")).toBeInTheDocument();
    expect(screen.getByText("File reply affidavit")).toBeInTheDocument();
    expect(screen.getByText("Reply affidavit due")).toBeInTheDocument();
    expect(screen.getAllByText(/Aditi Associate/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Source-backed/)).toHaveLength(2);
  });

  it("creates user-controlled task and deadline records", async () => {
    render(withClient(<MatterTasksPage />));

    fireEvent.change(await screen.findByPlaceholderText("Prepare reply affidavit"), {
      target: { value: "Prepare list of dates" },
    });
    fireEvent.change(screen.getAllByLabelText("Due")[0], {
      target: { value: "2026-05-22" },
    });
    fireEvent.change(screen.getByLabelText("Owner"), {
      target: { value: "mem-1" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);

    await waitFor(() =>
      expect(createMatterTaskMock).toHaveBeenCalledWith(
        "m-1",
        expect.objectContaining({
          title: "Prepare list of dates",
          due_on: "2026-05-22",
          owner_membership_id: "mem-1",
        }),
      ),
    );

    fireEvent.change(screen.getByPlaceholderText("File rejoinder"), {
      target: { value: "File affidavit" },
    });
    fireEvent.change(screen.getAllByLabelText("Due")[1], {
      target: { value: "2026-05-23" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[1]);

    await waitFor(() =>
      expect(createMatterDeadlineMock).toHaveBeenCalledWith(
        "m-1",
        expect.objectContaining({
          source: "custom",
          title: "File affidavit",
          due_on: "2026-05-23",
        }),
      ),
    );
  });

  it("uses existing update endpoints for complete actions", async () => {
    render(withClient(<MatterTasksPage />));

    await screen.findByText("Draft rejoinder");
    const completeButtons = screen.getAllByRole("button", { name: "Complete" });
    fireEvent.click(completeButtons[0]);
    fireEvent.click(completeButtons[completeButtons.length - 1]);

    await waitFor(() =>
      expect(updateMatterTaskMock).toHaveBeenCalledWith("m-1", "task-1", {
        status: "completed",
      }),
    );
    await waitFor(() =>
      expect(updateMatterDeadlineMock).toHaveBeenCalledWith(
        "m-1",
        "deadline-1",
        { status: "done" },
      ),
    );
  });

  it("keeps disposal-cancelled work read-only and hides operational create forms", async () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        ...WORKSPACE,
        matter: { ...WORKSPACE.matter, status: "disposed" },
      },
    });
    listMatterTasksMock.mockResolvedValue({
      matter_id: "m-1",
      tasks: [
        {
          ...TASKS.tasks[0],
          status: "cancelled",
          title: "Cancelled on disposal",
        },
      ],
    });
    listMatterDeadlinesMock.mockResolvedValue({
      matter_id: "m-1",
      deadlines: [
        {
          ...DEADLINES.deadlines[0],
          status: "cancelled",
          title: "Cancelled deadline on disposal",
        },
      ],
    });

    render(withClient(<MatterTasksPage />));

    expect(await screen.findByText("Cancelled on disposal")).toBeInTheDocument();
    expect(screen.getByText("Cancelled deadline on disposal")).toBeInTheDocument();
    expect(screen.getByTestId("disposed-task-write-guard")).toBeInTheDocument();
    expect(screen.getByTestId("disposed-deadline-write-guard")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Prepare reply affidavit")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("File rejoinder")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
  });
});
