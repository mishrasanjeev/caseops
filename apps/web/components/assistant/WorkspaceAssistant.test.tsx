import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

const api = vi.hoisted(() => ({
  archiveAssistantSession: vi.fn(),
  askWorkspaceAssistant: vi.fn(),
  confirmAssistantAction: vi.fn(),
  createAssistantSession: vi.fn(),
  deleteAssistantSession: vi.fn(),
  exportAssistantSession: vi.fn(),
  getAssistantSession: vi.fn(),
  listAssistantSessions: vi.fn(),
  listAssistantTurns: vi.fn(),
  previewAssistantAction: vi.fn(),
  replaceAssistantScopes: vi.fn(),
  searchAssistantScopes: vi.fn(),
}));

vi.mock("@/lib/api/workspace-assistant", () => api);

import { WorkspaceAssistant } from "@/components/assistant/WorkspaceAssistant";

const SCOPE = {
  scope_type: "matter" as const,
  scope_id: "matter-1",
  label: "TM-42 · Aster mark",
  secondary_text: "Matter TM-42 · Active",
  href: "/app/matters/matter-1",
  resource_version: "2026-08-27T12:00:00",
};

const SESSION = {
  id: "session-1",
  title: "Ask · TM-42 · Aster mark",
  status: "active" as const,
  version: 1,
  policy_version: 2,
  scope_state: "current" as const,
  scopes: [{ ...SCOPE, ordinal: 0 }],
  retention_expires_at: "2026-10-11T12:00:00Z",
  archived_at: null,
  created_at: "2026-08-27T12:00:00Z",
  updated_at: "2026-08-27T12:00:00Z",
};

const USER_TURN = {
  id: "turn-1",
  sequence: 1,
  role: "user" as const,
  status: "completed" as const,
  render_status: "visible" as const,
  content: "What is the matter status?",
  citations: [],
  model: null,
  suggested_searches: [],
  proposed_actions: [],
  created_at: "2026-08-27T12:01:00Z",
};

const ASSISTANT_TURN = {
  id: "turn-2",
  sequence: 2,
  role: "assistant" as const,
  status: "completed" as const,
  render_status: "visible" as const,
  content: "The matter is Active.",
  citations: [
    {
      id: "citation-1",
      ordinal: 0,
      source_type: "matter",
      source_id: "matter-1",
      source_version: "2026-08-27T12:00:00",
      source_sha256: "a".repeat(64),
      source_url: "/app/matters/matter-1",
      label: "TM-42 · Aster mark",
      excerpt: "Matter status Active",
      verified_at: "2026-08-27T12:01:00Z",
    },
  ],
  model: {
    run_id: "run-1",
    provider: "mock",
    model: "caseops-mock-1",
    purpose: "assistant",
    prompt_tokens: 40,
    completion_tokens: 12,
    latency_ms: 1,
    status: "ok",
  },
  suggested_searches: [],
  proposed_actions: [
    {
      proposal_id: "proposal-1",
      action_type: "task" as const,
      label: "Prepare a task proposal",
      href: null,
      target_type: "matter",
      target_id: "matter-1",
      target_version: "2026-08-27T12:00:00",
      target_label: "TM-42 · Aster mark",
      instruction: "Create a task",
      requires_confirmation: true,
      execution_available: false,
      unavailable_reason: "Action unavailable in this fixture",
    },
  ],
  created_at: "2026-08-27T12:01:01Z",
};

describe("WorkspaceAssistant", () => {
  beforeEach(() => {
    for (const mock of Object.values(api)) mock.mockReset();
    api.listAssistantSessions.mockResolvedValue({ items: [], limit: 25, offset: 0, has_more: false });
    api.searchAssistantScopes.mockResolvedValue({ query: "TM-42", items: [SCOPE], truncated: false });
    api.createAssistantSession.mockResolvedValue(SESSION);
    api.askWorkspaceAssistant.mockResolvedValue({
      session: { ...SESSION, version: 2 },
      user_turn: USER_TURN,
      assistant_turn: ASSISTANT_TURN,
    });
  });

  it("requires an explicit scope and renders exact citations without executing a proposal", async () => {
    const user = userEvent.setup();
    render(<WorkspaceAssistant />);

    await user.type(screen.getByRole("textbox", { name: "Find workspace records" }), "TM-42");
    await user.click(screen.getByRole("button", { name: "Find permitted records" }));
    await user.click(await screen.findByRole("button", { name: "Add TM-42 · Aster mark" }));
    await user.click(screen.getByRole("button", { name: "Start conversation" }));

    await waitFor(() =>
      expect(api.createAssistantSession).toHaveBeenCalledWith("Ask · TM-42 · Aster mark", [SCOPE]),
    );
    expect(screen.getByTestId("assistant-active-scope")).toHaveTextContent("TM-42 · Aster mark");

    await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), "What is the matter status?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("The matter is Active.")).toBeVisible();
    expect(screen.getByRole("link", { name: /TM-42 · Aster mark/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1",
    );
    expect(screen.getByRole("button", { name: "Prepare a task proposal" })).toBeDisabled();
    expect(api.askWorkspaceAssistant).toHaveBeenCalledWith(
      "session-1",
      1,
      "What is the matter status?",
    );
  });

  it("surfaces the fail-closed tenant policy state", async () => {
    const user = userEvent.setup();
    api.searchAssistantScopes.mockRejectedValue(
      new ApiError(
        403,
        "Ask this Workspace is disabled by workspace AI policy.",
        null,
        "workspace_assistant_disabled",
      ),
    );
    render(<WorkspaceAssistant />);

    await user.type(screen.getByRole("textbox", { name: "Find workspace records" }), "workspace");
    await user.click(screen.getByRole("button", { name: "Find permitted records" }));

    expect(await screen.findByText("Workspace AI policy has not enabled this assistant.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start conversation" })).toBeDisabled();
  });

  it("previews exact task changes before a separate confirmation", async () => {
    const user = userEvent.setup();
    const availableTurn = {
      ...ASSISTANT_TURN,
      proposed_actions: [
        {
          ...ASSISTANT_TURN.proposed_actions[0],
          execution_available: true,
          unavailable_reason: null,
        },
      ],
    };
    const pending = {
      preview_id: "preview-1",
      proposal_id: "proposal-1",
      action_type: "task" as const,
      status: "pending" as const,
      session_version: 2,
      resulting_session_version: null,
      target_type: "matter",
      target_id: "matter-1",
      target_label: "TM-42 · Aster mark",
      summary: "Create one task on TM-42 · Aster mark.",
      changes: [
        { field: "Title", before: null, after: "Review registry evidence" },
        { field: "Priority", before: null, after: "high" },
      ],
      warnings: ["Nothing is written until you confirm this exact preview."],
      required_capabilities: ["matters:write"],
      preview_token: "a".repeat(64),
      expires_at: "2026-08-27T12:16:00Z",
      result_type: null,
      result_id: null,
      result_href: null,
    };
    api.askWorkspaceAssistant.mockResolvedValue({
      session: { ...SESSION, version: 2 },
      user_turn: USER_TURN,
      assistant_turn: availableTurn,
    });
    api.previewAssistantAction.mockResolvedValue(pending);
    api.confirmAssistantAction.mockResolvedValue({
      ...pending,
      status: "confirmed",
      resulting_session_version: 3,
      result_type: "matter_task",
      result_id: "task-1",
      result_href: "/app/matters/matter-1/tasks",
    });
    render(<WorkspaceAssistant />);

    await user.type(screen.getByRole("textbox", { name: "Find workspace records" }), "TM-42");
    await user.click(screen.getByRole("button", { name: "Find permitted records" }));
    await user.click(await screen.findByRole("button", { name: "Add TM-42 · Aster mark" }));
    await user.click(screen.getByRole("button", { name: "Start conversation" }));
    await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), "Create a task");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await user.click(await screen.findByRole("button", { name: "Prepare a task proposal" }));
    expect(api.previewAssistantAction).not.toHaveBeenCalled();
    const title = screen.getByRole("textbox", { name: "Task title" });
    await user.clear(title);
    await user.type(title, "Review registry evidence");
    await user.click(screen.getByRole("combobox", { name: "Priority" }));
    await user.click(screen.getByRole("option", { name: "High" }));
    await user.click(screen.getByRole("button", { name: "Review changes" }));

    await waitFor(() =>
      expect(api.previewAssistantAction).toHaveBeenCalledWith(
        "session-1",
        2,
        "turn-2",
        "proposal-1",
        expect.objectContaining({ title: "Review registry evidence", priority: "high" }),
      ),
    );
    expect(await screen.findByText("Create one task on TM-42 · Aster mark.")).toBeVisible();
    expect(api.confirmAssistantAction).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm action" }));
    await waitFor(() =>
      expect(api.confirmAssistantAction).toHaveBeenCalledWith(
        "session-1",
        "preview-1",
        2,
        "a".repeat(64),
      ),
    );
    expect(await screen.findByText("Action confirmed")).toBeVisible();
    expect(screen.getByRole("link", { name: /Open result/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1/tasks",
    );
  });

  it("shows permission-changed history and clears the active scope through archival", async () => {
    const user = userEvent.setup();
    const changed = { ...SESSION, scope_state: "permission_changed" as const, scopes: [] };
    const hidden = {
      ...ASSISTANT_TURN,
      render_status: "permission_changed" as const,
      content: "This answer is hidden because access changed.",
      citations: [],
    };
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION], limit: 25, offset: 0, has_more: false });
    api.getAssistantSession.mockResolvedValue(changed);
    api.listAssistantTurns.mockResolvedValue({ items: [USER_TURN, hidden], limit: 50, offset: 0, has_more: false });
    api.archiveAssistantSession.mockResolvedValue({ ...changed, status: "archived", version: 2 });
    render(<WorkspaceAssistant />);

    await user.click(await screen.findByRole("button", { name: /Ask · TM-42/ }));
    expect(await screen.findByText(/Scope permissions changed/)).toBeVisible();
    expect(screen.getByText("This answer is hidden because access changed.")).toBeVisible();
    expect(screen.queryByRole("link", { name: /TM-42 · Aster mark/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    await waitFor(() => expect(api.archiveAssistantSession).toHaveBeenCalledWith("session-1", 1));
    expect(screen.getByText("No scope selected")).toBeVisible();
  });
});
