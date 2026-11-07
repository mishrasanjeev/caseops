import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError } from "@/lib/api/config";
import type { AssistantSessionExport, AssistantTurn, AssistantTurnPage } from "@/lib/api/workspace-assistant";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

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
  openAssistantCitation: vi.fn(),
  previewAssistantAction: vi.fn(),
  replaceAssistantScopes: vi.fn(),
  searchAssistantScopes: vi.fn(),
}));

vi.mock("@/lib/api/workspace-assistant", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api/workspace-assistant")>(),
  ...api,
}));

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function historyTurns(count: number, first = 1) {
  return Array.from({ length: count }, (_, index) => ({
    ...USER_TURN,
    id: `history-${first + index}`,
    sequence: first + index,
    role: (first + index) % 2 ? "user" as const : "assistant" as const,
    content: `Private message ${first + index}`,
  }));
}

function historySnapshot(items: AssistantTurn[]): AssistantTurnPage {
  return { items, limit: 200, offset: 0, has_more: false };
}

function hiddenTurn(sequence = 52): AssistantTurn {
  return {
    ...ASSISTANT_TURN, id: `hidden-${sequence}`, sequence,
    render_status: "permission_changed", content: "This answer is hidden because source access changed.",
    citations: [], proposed_actions: [], suggested_searches: [], model: null,
  };
}

function downloadSpies() {
  const prior = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  const priorRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
  const create = vi.fn((_blob: Blob) => "blob:assistant-export");
  const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  return { create, revoke, restore() {
    click.mockRestore();
    if (prior) Object.defineProperty(URL, "createObjectURL", prior);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (priorRevoke) Object.defineProperty(URL, "revokeObjectURL", priorRevoke);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  } };
}

async function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

async function openStoredConversation(user: ReturnType<typeof userEvent.setup>) {
  render(<WorkspaceAssistant />);
  await user.click(await screen.findByRole("button", { name: SESSION.title }));
  await screen.findByRole("textbox", { name: "Ask this workspace" });
}

describe("WorkspaceAssistant", () => {
  beforeEach(() => {
    for (const mock of Object.values(api)) mock.mockReset();
    router.push.mockReset();
    api.listAssistantSessions.mockResolvedValue({ items: [], limit: 25, offset: 0, has_more: false });
    api.searchAssistantScopes.mockResolvedValue({ query: "TM-42", items: [SCOPE], truncated: false });
    api.createAssistantSession.mockResolvedValue(SESSION);
    api.getAssistantSession.mockResolvedValue(SESSION);
    api.listAssistantTurns.mockResolvedValue({ items: [USER_TURN, ASSISTANT_TURN], limit: 50, offset: 0, has_more: false });
    api.openAssistantCitation.mockResolvedValue({ citation_id: "citation-1", source_url: "/app/matters/matter-1" });
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
    expect(screen.getByTestId("workspace-assistant-feedback-turn-2")).toBeVisible();
    expect(screen.queryByTestId("workspace-assistant-feedback-turn-1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" })).not.toHaveAttribute("href");
    expect(api.openAssistantCitation).not.toHaveBeenCalled();
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

    expect(
      await screen.findByText(/Workspace AI policy has not enabled this assistant/),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Admin → AI controls" })).toHaveAttribute(
      "href",
      "/app/admin",
    );
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

  it("removes cached history and session labels when a later scope search reports disabled policy", async () => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    await openStoredConversation(user);
    expect(screen.getByText(ASSISTANT_TURN.content)).toBeVisible();
    api.searchAssistantScopes.mockRejectedValue(new ApiError(403, "Assistant disabled by policy.", null, "workspace_assistant_disabled"));
    await user.type(screen.getByRole("textbox", { name: "Find workspace records" }), "workspace");
    await user.click(screen.getByRole("button", { name: "Find permitted records" }));
    expect(await screen.findByText(/Workspace AI policy has not enabled this assistant/)).toBeVisible();
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: SESSION.title })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    await waitFor(() => expect(api.archiveAssistantSession).toHaveBeenCalledWith("session-1", 1));
    expect(screen.getByText("No scope selected")).toBeVisible();
  });

  it("opens only the exact reauthorized destination after the POST resolves", async () => {
    const user = userEvent.setup();
    const opened = deferred<{ citation_id: string; source_url: string }>();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.openAssistantCitation.mockReturnValue(opened.promise);
    await openStoredConversation(user);
    const source = screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" });
    await user.click(source);
    expect(api.openAssistantCitation).toHaveBeenCalledExactlyOnceWith("session-1", "citation-1");
    expect(source).toBeDisabled();
    expect(router.push).not.toHaveBeenCalled();
    const destination = "/app/matters/matter-1?view=documents&source=retained%2Fversion#evidence";
    await act(async () => opened.resolve({ citation_id: "citation-1", source_url: destination }));
    expect(router.push).toHaveBeenCalledExactlyOnceWith(destination);
  });

  it.each([
    new ApiError(401, "Your session has expired.", null),
    new ApiError(403, "This source is no longer permitted.", null),
    new ApiError(409, "Citation access or source version changed. Ask again before opening it.", null),
    new NetworkError("The citation request timed out.", null),
    new Error("The citation destination is unavailable. Reopen the conversation and try again."),
  ])("never falls back to a cached source after $message", async (error) => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.openAssistantCitation.mockRejectedValue(error);
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" }));
    expect((await screen.findByRole("alert")).textContent).toBe(error.message);
    expect(router.push).not.toHaveBeenCalled();
    expect(api.openAssistantCitation).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: SESSION.title })).toBeEnabled();
  });

  it.each([
    "javascript:alert(document.domain)",
    "data:text/html,unsafe",
    "//attacker.example/app/matters/matter-1",
    "https://attacker.example/app/matters/matter-1",
    "/app/../admin",
    "/native/sign-in",
    "/app/unknown-route",
  ])("rejects an unsafe successful destination before router navigation: %s", async (source_url) => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.openAssistantCitation.mockResolvedValue({ citation_id: "citation-1", source_url });
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The citation destination is unavailable. Reopen the conversation and try again.",
    );
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(api.openAssistantCitation).toHaveBeenCalledTimes(1);
  });

  it("never renders a legacy source Open href alongside the audited citation", async () => {
    const user = userEvent.setup();
    const legacy = {
      ...ASSISTANT_TURN,
      proposed_actions: [
        {
          ...ASSISTANT_TURN.proposed_actions[0],
          proposal_id: "legacy-open", action_type: "navigation" as const,
          label: "Open private source", href: "/app/matters/matter-1",
          requires_confirmation: false,
        },
        {
          ...ASSISTANT_TURN.proposed_actions[0],
          proposal_id: "safe-search", action_type: "search" as const,
          href: "/app/research?query=review", requires_confirmation: false,
        },
      ],
    };
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN, legacy], limit: 50, offset: 0, has_more: false });
    await openStoredConversation(user);
    expect(screen.queryByText("Open private source")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" })).not.toHaveAttribute("href");
    expect(screen.getByRole("link", { name: "Search verified legal sources" })).toHaveAttribute(
      "href", "/app/research?query=review",
    );
  });

  it("continues past 50 retained turns using one bounded reauthorized snapshot", async () => {
    const user = userEvent.setup();
    const turns = historyTurns(52);
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: turns.slice(0, 50), limit: 50, offset: 0, has_more: true })
      .mockResolvedValueOnce(historySnapshot(turns));
    await openStoredConversation(user);
    expect(screen.queryByText("Private message 52")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(await screen.findByText("Private message 52")).toBeVisible();
    expect(api.listAssistantTurns).toHaveBeenNthCalledWith(2, SESSION.id, { snapshot: true });
    expect([...screen.getByTestId("assistant-turns").querySelectorAll("article")].map((row) => row.getAttribute("data-turn-id")))
      .toEqual(turns.map((turn) => turn.id));
    expect(screen.queryByRole("button", { name: "Load more messages" })).not.toBeInTheDocument();
  });

  it("replaces a revoked prefix even when later turns concern an independent source", async () => {
    const user = userEvent.setup();
    const first = [USER_TURN, ASSISTANT_TURN, ...historyTurns(48, 3)];
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: first, limit: 50, offset: 0, has_more: true })
      .mockResolvedValueOnce(historySnapshot([
        USER_TURN, hiddenTurn(2), ...first.slice(2),
        ...historyTurns(2, 51),
      ]))
      .mockResolvedValueOnce({ items: [hiddenTurn()], limit: 50, offset: 0, has_more: false });
    await openStoredConversation(user);
    expect(screen.getByText("Private message 50")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/sources or permissions changed/i);
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.getByText("Private message 50")).toBeVisible();
    expect(screen.getByText("Private message 52")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare a task proposal" })).not.toBeInTheDocument();
    expect(screen.getByText(hiddenTurn().content)).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), "A new question");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    api.getAssistantSession.mockResolvedValue({ ...SESSION, scope_state: "permission_changed", scopes: [] });
    await user.click(screen.getByRole("button", { name: SESSION.title }));
    expect(await screen.findByText(hiddenTurn().content)).toBeVisible();
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(api.listAssistantTurns.mock.calls).toEqual([[SESSION.id], [SESSION.id, { snapshot: true }], [SESSION.id]]);
  });

  it.each(["session", "user", "assistant"] as const)("invalidates cached turns for a successful ask with a changed %s", async (changed) => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.askWorkspaceAssistant.mockResolvedValue({
      session: { ...SESSION, version: 2, scope_state: changed === "session" ? "permission_changed" : "current" },
      user_turn: { ...USER_TURN, id: "followup-user", sequence: 3, content: "A fresh follow-up question", render_status: changed === "user" ? "permission_changed" : "visible" },
      assistant_turn: { ...hiddenTurn(4), render_status: changed === "assistant" ? "permission_changed" : "visible", status: "abstained", content: changed === "assistant" ? hiddenTurn().content : "Fresh authorized abstention" },
    });
    await openStoredConversation(user);
    await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), "A follow-up question");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/sources or permissions changed/i);
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
  });

  it("does not download an older export after a continuation revokes cached source access", async () => {
    const user = userEvent.setup();
    const page = deferred<AssistantTurnPage>();
    const exported = deferred<AssistantSessionExport>();
    const download = downloadSpies();
    try {
      api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
      api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN, ASSISTANT_TURN], limit: 2, offset: 0, has_more: true }).mockReturnValueOnce(page.promise);
      api.exportAssistantSession.mockReturnValue(exported.promise);
      await openStoredConversation(user);
      await user.click(screen.getByRole("button", { name: "Load more messages" }));
      await user.click(screen.getByRole("button", { name: "Export conversation" }));
      expect(api.exportAssistantSession).toHaveBeenCalledWith(SESSION.id);
      await act(async () => page.resolve(historySnapshot([USER_TURN, hiddenTurn()])));
      await act(async () => exported.resolve({ schema_version: 1, exported_at: SESSION.updated_at, session: SESSION, turns: [USER_TURN, ASSISTANT_TURN], retention_disposition: "retained" }));
      expect(download.create).not.toHaveBeenCalled();
    } finally { download.restore(); }
  });

  it.each(["session", "turn"] as const)("replaces cached turns with the current redacted export when %s access changed", async (changed) => {
    const user = userEvent.setup();
    const download = downloadSpies();
    try {
      api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
      const exported: AssistantSessionExport = {
        schema_version: 1, exported_at: SESSION.updated_at, retention_disposition: "retained",
        session: { ...SESSION, scopes: [], scope_state: changed === "session" ? "permission_changed" : "current" },
        turns: changed === "turn" ? [hiddenTurn()] : [{ ...USER_TURN, content: "Current permitted question" }],
      };
      api.exportAssistantSession.mockResolvedValue(exported);
      await openStoredConversation(user);
      await user.click(screen.getByRole("button", { name: "Export conversation" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/sources or permissions changed/i);
      expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
      expect(download.create).toHaveBeenCalledOnce();
      expect(JSON.parse(await blobText(download.create.mock.calls[0][0]))).toEqual(exported);
      expect(download.revoke).toHaveBeenCalledWith("blob:assistant-export");
    } finally { download.restore(); }
  });

  it("keeps a currently authorized export usable", async () => {
    const user = userEvent.setup();
    const download = downloadSpies();
    const exported: AssistantSessionExport = { schema_version: 1, exported_at: SESSION.updated_at, session: SESSION, turns: [USER_TURN, ASSISTANT_TURN], retention_disposition: "retained" };
    try {
      api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
      api.exportAssistantSession.mockResolvedValue(exported);
      await openStoredConversation(user);
      await user.click(screen.getByRole("button", { name: "Export conversation" }));
      expect(download.create).toHaveBeenCalledOnce();
      expect(JSON.parse(await blobText(download.create.mock.calls[0][0]))).toEqual(exported);
      expect(screen.getByText(ASSISTANT_TURN.content)).toBeVisible();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } finally { download.restore(); }
  });

  it("does not restore private scope labels from a search pending across source invalidation", async () => {
    const user = userEvent.setup();
    const page = deferred<AssistantTurnPage>();
    const search = deferred<{ query: string; items: typeof SCOPE[]; truncated: boolean }>();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN, ASSISTANT_TURN], limit: 2, offset: 0, has_more: true }).mockReturnValueOnce(page.promise);
    api.searchAssistantScopes.mockReturnValue(search.promise);
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    await user.type(screen.getByRole("textbox", { name: "Find workspace records" }), "TM-42");
    await user.click(screen.getByRole("button", { name: "Find permitted records" }));
    expect(api.searchAssistantScopes).toHaveBeenCalledOnce();
    await act(async () => page.resolve(historySnapshot([USER_TURN, hiddenTurn()])));
    await act(async () => search.resolve({ query: "TM-42", items: [{ ...SCOPE, scope_id: "late-private", label: "Late private source" }], truncated: false }));
    expect(screen.queryByRole("button", { name: "Add Late private source" })).not.toBeInTheDocument();
  });

  it("starts with 50 and reaches all 200 retained turns in one continuation", async () => {
    const user = userEvent.setup();
    const turns = historyTurns(200);
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: turns.slice(0, 50), limit: 50, offset: 0, has_more: true })
      .mockResolvedValueOnce(historySnapshot(turns));
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    await screen.findByText("Private message 200");
    expect(api.listAssistantTurns.mock.calls).toEqual([[SESSION.id], [SESSION.id, { snapshot: true }]]);
    expect(screen.getByTestId("assistant-turns").querySelectorAll("article")).toHaveLength(200);
    expect(screen.queryByRole("button", { name: "Load more messages" })).not.toBeInTheDocument();
  });

  it("replaces rather than duplicating new answers when expanding history", async () => {
    const user = userEvent.setup();
    const turns = historyTurns(4);
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: turns.slice(0, 2), limit: 2, offset: 0, has_more: true })
      .mockResolvedValueOnce(historySnapshot(turns));
    api.askWorkspaceAssistant.mockResolvedValue({ session: { ...SESSION, version: 2 }, user_turn: turns[2], assistant_turn: turns[3] });
    await openStoredConversation(user);
    await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), "A follow-up question");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Private message 4");
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    await waitFor(() => expect(api.listAssistantTurns).toHaveBeenLastCalledWith(SESSION.id, { snapshot: true }));
    expect(screen.getByTestId("assistant-turns").querySelectorAll("article")).toHaveLength(4);
    expect(screen.getAllByText("Private message 4")).toHaveLength(1);
  });

  it("discards an authorized old-session citation response after switching sessions", async () => {
    const user = userEvent.setup();
    const opened = deferred<{ citation_id: string; source_url: string }>();
    const other = { ...SESSION, id: "session-2", title: "Conversation B" };
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION, other] });
    api.getAssistantSession.mockImplementation(async (id) => id === other.id ? other : SESSION);
    api.openAssistantCitation.mockReturnValue(opened.promise);
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Open source: TM-42 · Aster mark" }));
    await user.click(screen.getByRole("button", { name: other.title }));
    await waitFor(() => expect(api.getAssistantSession).toHaveBeenLastCalledWith(other.id));
    await act(async () => opened.resolve({ citation_id: "citation-1", source_url: "/app/matters/matter-1" }));
    expect(router.push).not.toHaveBeenCalled();
  });

  it("hides previous history even when reopening fails with a transient error", async () => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN, ASSISTANT_TURN], limit: 50, offset: 0, has_more: false })
      .mockRejectedValueOnce(new NetworkError("History refresh timed out.", null));
    await openStoredConversation(user);
    expect(screen.getByText(ASSISTANT_TURN.content)).toBeVisible();
    await user.click(screen.getByRole("button", { name: SESSION.title }));
    expect((await screen.findByRole("alert")).textContent).toBe("History refresh timed out.");
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
  });

  it("hides cached rows rather than looping on a nonadvancing continuation", async () => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN], limit: 1, offset: 0, has_more: true })
      .mockResolvedValueOnce({ items: [], limit: 1, offset: 1, has_more: true });
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Conversation history could not be read safely. Reopen the conversation.");
    expect(screen.queryByText(USER_TURN.content)).not.toBeInTheDocument();
    expect(api.listAssistantTurns).toHaveBeenCalledTimes(2);
  });

  it.each(["resolve", "reject"] as const)("ignores an old-session next-page %s after switching", async (outcome) => {
    const user = userEvent.setup();
    const oldPage = deferred<AssistantTurnPage>();
    const other = { ...SESSION, id: "session-2", title: "Conversation B" };
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION, other] });
    api.getAssistantSession.mockImplementation(async (id) => id === other.id ? other : SESSION);
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN], limit: 1, offset: 0, has_more: true })
      .mockReturnValueOnce(oldPage.promise)
      .mockResolvedValueOnce({ items: [{ ...USER_TURN, id: "b-turn", content: "Private B only" }], limit: 50, offset: 0, has_more: false });
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(screen.getByRole("button", { name: "Load more messages" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: other.title }));
    await screen.findByText("Private B only");
    await act(async () => {
      if (outcome === "resolve") oldPage.resolve(historySnapshot([{ ...USER_TURN, id: "late-a", content: "Late private A" }]));
      else oldPage.reject(new ApiError(403, "Old-session denial", null));
    });
    expect(screen.getByText("Private B only")).toBeVisible();
    expect(screen.queryByText("Late private A")).not.toBeInTheDocument();
    expect(screen.queryByText(USER_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    new ApiError(503, "History temporarily unavailable.", null),
    new NetworkError("Connection lost while loading history.", null),
  ])("clears an unverified prefix on transient $message and allows a fresh retry", async (error) => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN], limit: 1, offset: 0, has_more: true })
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(historySnapshot([USER_TURN, ASSISTANT_TURN]));
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect((await screen.findByRole("alert")).textContent).toBe(error.message);
    expect(screen.queryByText(USER_TURN.content)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    await screen.findByText(ASSISTANT_TURN.content);
    expect(screen.getByText(USER_TURN.content)).toBeVisible();
    expect(api.listAssistantTurns.mock.calls.slice(1)).toEqual([
      [SESSION.id, { snapshot: true }], [SESSION.id, { snapshot: true }],
    ]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    { error: new ApiError(401, "Sign in again.", null), detail: "Sign in again." },
    { error: new ApiError(403, "History access was revoked.", null), detail: "History access was revoked." },
    { error: new ApiError(409, "The retained source changed.", null), detail: "The retained source changed." },
    { error: new ApiError(503, "Private verification is no longer current.", null, "private_manifest_changed"), detail: "Private verification is no longer current." },
    { error: new Error("Unexpected history payload."), detail: "Unexpected history payload." },
    { error: { status: 503 }, detail: "Could not load more conversation messages." },
    { error: { name: "ApiError", status: 503, detail: "Unknown failure type.", problemType: {} }, detail: "Unknown failure type." },
  ])("hides all cached private turns for a next-page $detail", async ({ error, detail }) => {
    const user = userEvent.setup();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION] });
    api.listAssistantTurns.mockResolvedValueOnce({ items: [USER_TURN, ASSISTANT_TURN], limit: 2, offset: 0, has_more: true })
      .mockRejectedValueOnce(error);
    await openStoredConversation(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect((await screen.findByRole("alert")).textContent).toBe(detail);
    expect(screen.queryByText(USER_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByText(ASSISTANT_TURN.content)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open source:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more messages" })).not.toBeInTheDocument();
  });
});
