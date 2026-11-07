import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import type {
  AssistantActionPreview,
  AssistantAskResponse,
  AssistantCitation,
  AssistantProposedAction,
  AssistantSessionExport,
  AssistantSessionRecord,
  AssistantTurn,
  AssistantTurnPage,
} from "@/lib/api/workspace-assistant";

type AssistantApi = typeof import("@/lib/api/workspace-assistant");

const api = vi.hoisted(() => ({
  archiveAssistantSession: vi.fn<AssistantApi["archiveAssistantSession"]>(),
  askWorkspaceAssistant: vi.fn<AssistantApi["askWorkspaceAssistant"]>(),
  confirmAssistantAction: vi.fn<AssistantApi["confirmAssistantAction"]>(),
  createAssistantSession: vi.fn<AssistantApi["createAssistantSession"]>(),
  deleteAssistantSession: vi.fn<AssistantApi["deleteAssistantSession"]>(),
  exportAssistantSession: vi.fn<AssistantApi["exportAssistantSession"]>(),
  getAssistantSession: vi.fn<AssistantApi["getAssistantSession"]>(),
  listAssistantSessions: vi.fn<AssistantApi["listAssistantSessions"]>(),
  listAssistantTurns: vi.fn<AssistantApi["listAssistantTurns"]>(),
  openAssistantCitation: vi.fn<AssistantApi["openAssistantCitation"]>(),
  previewAssistantAction: vi.fn<AssistantApi["previewAssistantAction"]>(),
  replaceAssistantScopes: vi.fn<AssistantApi["replaceAssistantScopes"]>(),
  searchAssistantScopes: vi.fn<AssistantApi["searchAssistantScopes"]>(),
}));
const unmockedRequest = vi.hoisted(() => vi.fn(() => {
  throw new Error("Epoch tests must not make an unmocked API request.");
}));

vi.mock("@/lib/api/client", () => ({ apiRequest: unmockedRequest }));
vi.mock("@/lib/api/workspace-assistant", async (importOriginal) => ({
  ...await importOriginal<AssistantApi>(),
  ...api,
}));

import { WorkspaceAssistant } from "@/components/assistant/WorkspaceAssistant";

const SOURCE_VERSION = "2026-11-07T06:00:00Z";
const MATTER_A = "10000000-0000-4000-8000-000000000001";
const MATTER_B = "10000000-0000-4000-8000-000000000002";
const SESSION_A: AssistantSessionRecord = {
  id: "20000000-0000-4000-8000-000000000001",
  title: "Conversation A",
  status: "active",
  version: 7,
  policy_version: 2,
  scope_state: "current",
  scopes: [{ scope_type: "matter", scope_id: MATTER_A, resource_version: SOURCE_VERSION, ordinal: 0 }],
  retention_expires_at: "2026-12-07T06:00:00Z",
  archived_at: null,
  created_at: SOURCE_VERSION,
  updated_at: SOURCE_VERSION,
};
const SESSION_B: AssistantSessionRecord = {
  ...SESSION_A,
  id: "20000000-0000-4000-8000-000000000002",
  title: "Conversation B",
  version: 19,
  scopes: [{ scope_type: "matter", scope_id: MATTER_B, resource_version: SOURCE_VERSION, ordinal: 0 }],
};
const ACTION: AssistantProposedAction = {
  proposal_id: "30000000-0000-4000-8000-000000000001",
  action_type: "task",
  label: "Prepare a task proposal",
  href: null,
  target_type: "matter",
  target_id: MATTER_A,
  target_version: SOURCE_VERSION,
  target_label: "Source Matter A",
  instruction: "Review source evidence",
  requires_confirmation: true,
  execution_available: true,
  unavailable_reason: null,
};
const CITATION: AssistantCitation = {
  id: "40000000-0000-4000-8000-000000000001",
  ordinal: 0,
  source_type: "matter",
  source_id: MATTER_A,
  source_version: SOURCE_VERSION,
  source_sha256: "a".repeat(64),
  source_url: `/app/matters/${MATTER_A}`,
  label: "Source Matter A",
  excerpt: "Recorded source evidence",
  verified_at: SOURCE_VERSION,
};

function turn(prefix: string, sequence: number, content: string): AssistantTurn {
  return {
    id: `${prefix}-turn-${sequence}`,
    sequence,
    role: sequence % 2 ? "user" : "assistant",
    status: "completed",
    render_status: "visible",
    content,
    citations: [],
    model: null,
    suggested_searches: [],
    proposed_actions: [],
    created_at: SOURCE_VERSION,
  };
}

const PREFIX: AssistantTurn[] = Array.from({ length: 50 }, (_, index) => {
  const item = turn("a", index + 1, `Cached private message ${index + 1}`);
  return index === 1 ? { ...item, citations: [CITATION], proposed_actions: [ACTION] } : item;
});
const FIRST_PAGE: AssistantTurnPage = { items: PREFIX, limit: 50, offset: 0, has_more: true };
const REDACTED_PAGE: AssistantTurnPage = {
  items: [
    turn("a", 51, "Retained continuation question"),
    {
      ...turn("a", 52, "This answer is hidden because source access changed."),
      render_status: "permission_changed",
    },
  ],
  limit: 50,
  offset: 50,
  has_more: false,
};
const B_ANSWER = "Currently authorized conversation B";
const B_PAGE: AssistantTurnPage = {
  items: [turn("b", 1, "Question in conversation B"), turn("b", 2, B_ANSWER)],
  limit: 50,
  offset: 0,
  has_more: false,
};
const FOLLOW_UP = "Read the current record";
const B_RESPONSE: AssistantAskResponse = {
  session: { ...SESSION_B, version: 20 },
  user_turn: turn("b", 3, FOLLOW_UP),
  assistant_turn: turn("b", 4, "Fresh answer in conversation B"),
};
const PREVIEW: AssistantActionPreview = {
  preview_id: "50000000-0000-4000-8000-000000000001",
  proposal_id: ACTION.proposal_id,
  action_type: "task",
  status: "pending",
  session_version: SESSION_A.version,
  resulting_session_version: null,
  target_type: "matter",
  target_id: MATTER_A,
  target_label: "Source Matter A",
  summary: "Create one source-review task",
  changes: [{ field: "Title", before: null, after: "Review source evidence" }],
  warnings: ["Confirm this exact preview before writing."],
  required_capabilities: ["matters:write"],
  preview_token: "b".repeat(64),
  expires_at: "2026-11-07T06:15:00Z",
  result_type: null,
  result_id: null,
  result_href: null,
};
const CONFIRMED: AssistantActionPreview = {
  ...PREVIEW,
  status: "confirmed",
  resulting_session_version: 8,
  result_type: "matter_task",
  result_id: "60000000-0000-4000-8000-000000000001",
  result_href: `/app/matters/${MATTER_A}/tasks`,
};
const SAFE_EXPORT: AssistantSessionExport = {
  schema_version: 1,
  exported_at: "2026-11-07T06:10:00Z",
  session: { ...SESSION_A, version: 23, scope_state: "permission_changed", scopes: [] },
  turns: REDACTED_PAGE.items,
  retention_disposition: "retained",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function openA(user: ReturnType<typeof userEvent.setup>) {
  render(<WorkspaceAssistant />);
  await user.click(await screen.findByRole("button", { name: SESSION_A.title }));
  await screen.findByText(PREFIX[1].content);
}

async function openB(user: ReturnType<typeof userEvent.setup>) {
  const saved = screen.getByRole("button", { name: SESSION_B.title });
  expect(saved).toBeEnabled();
  await user.click(saved);
  expect(await screen.findByText(B_ANSWER)).toBeVisible();
  expect(api.getAssistantSession).toHaveBeenLastCalledWith(SESSION_B.id);
  expect(screen.queryByText(PREFIX[1].content)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
}

async function beginConfirmation(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: ACTION.label }));
  const dialog = await screen.findByRole("dialog", { name: "Review task" });
  await user.click(within(dialog).getByRole("button", { name: "Review changes" }));
  await within(dialog).findByText(PREVIEW.summary);
  expect(api.previewAssistantAction).toHaveBeenCalledExactlyOnceWith(
    SESSION_A.id, 7, PREFIX[1].id, ACTION.proposal_id,
    { title: "Review source evidence", priority: "medium" },
  );
  await user.click(within(dialog).getByRole("button", { name: "Confirm action" }));
  expect(api.confirmAssistantAction).toHaveBeenCalledExactlyOnceWith(
    SESSION_A.id, PREVIEW.preview_id, 7, PREVIEW.preview_token,
  );
  return dialog;
}

function holdContinuation() {
  const page = deferred<AssistantTurnPage>();
  api.listAssistantTurns.mockImplementation((id, options) => {
    if (id === SESSION_A.id && options?.offset === 50) return page.promise;
    if (id === SESSION_A.id && !options?.offset) return Promise.resolve(FIRST_PAGE);
    if (id === SESSION_B.id && !options?.offset) return Promise.resolve(B_PAGE);
    throw new Error("Unexpected history identity or cursor.");
  });
  return page;
}

async function finishRedaction(page: ReturnType<typeof holdContinuation>) {
  await act(async () => page.resolve(REDACTED_PAGE));
  expect(screen.getByText(REDACTED_PAGE.items[1].content)).toBeVisible();
  expect(screen.queryByText(PREFIX[1].content)).not.toBeInTheDocument();
  expect(screen.getByTestId("assistant-active-scope")).toHaveTextContent("No scope selected");
  expect(screen.getByRole("alert")).toHaveTextContent("Cached messages and scope labels were cleared");
}

async function beginBQuestion(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("textbox", { name: "Ask this workspace" }), FOLLOW_UP);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  expect(api.askWorkspaceAssistant).toHaveBeenCalledExactlyOnceWith(SESSION_B.id, 19, FOLLOW_UP);
  expect(screen.getByRole("button", { name: "Working" })).toBeDisabled();
}

describe("WorkspaceAssistant asynchronous epoch isolation", () => {
  let restoreDownloads: (() => void) | undefined;

  beforeEach(() => {
    for (const mock of Object.values(api)) mock.mockReset();
    unmockedRequest.mockClear();
    api.listAssistantSessions.mockResolvedValue({ items: [SESSION_A, SESSION_B], limit: 25, offset: 0, has_more: false });
    api.getAssistantSession.mockImplementation(async (id) => {
      if (id === SESSION_A.id) return SESSION_A;
      if (id === SESSION_B.id) return SESSION_B;
      throw new Error("Unexpected conversation identity.");
    });
    api.listAssistantTurns.mockImplementation(async (id) => {
      if (id === SESSION_A.id) return FIRST_PAGE;
      if (id === SESSION_B.id) return B_PAGE;
      throw new Error("Unexpected conversation identity.");
    });
    api.previewAssistantAction.mockResolvedValue(PREVIEW);
    api.askWorkspaceAssistant.mockResolvedValue(B_RESPONSE);
    api.archiveAssistantSession.mockResolvedValue({ ...SESSION_A, status: "archived", version: 9 });
  });

  afterEach(() => {
    restoreDownloads?.();
    restoreDownloads = undefined;
    vi.restoreAllMocks();
    expect(unmockedRequest).not.toHaveBeenCalled();
  });

  it("applies a current real-dialog confirmation to the current conversation version", async () => {
    const user = userEvent.setup();
    api.confirmAssistantAction.mockResolvedValue(CONFIRMED);
    await openA(user);
    const dialog = await beginConfirmation(user);
    expect(await within(dialog).findByText("Action confirmed")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Close action review" }));
    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    expect(api.archiveAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id, 8);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a late real-dialog confirmation after closing the dialog and switching conversations", async () => {
    const user = userEvent.setup();
    const confirmation = deferred<AssistantActionPreview>();
    const answer = deferred<AssistantAskResponse>();
    api.confirmAssistantAction.mockReturnValue(confirmation.promise);
    api.askWorkspaceAssistant.mockReturnValue(answer.promise);
    await openA(user);
    const dialog = await beginConfirmation(user);
    expect(within(dialog).getByRole("button", { name: "Confirm action" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await openB(user);
    await act(async () => confirmation.resolve(CONFIRMED));
    expect(screen.getByText(B_ANSWER)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await beginBQuestion(user);
    await act(async () => answer.resolve(B_RESPONSE));
    expect(screen.getByText(B_RESPONSE.assistant_turn.content)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a pending real-dialog confirmation after a successful continuation redacts the source", async () => {
    const user = userEvent.setup();
    const page = holdContinuation();
    const confirmation = deferred<AssistantActionPreview>();
    api.confirmAssistantAction.mockReturnValue(confirmation.promise);
    await openA(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(api.listAssistantTurns).toHaveBeenLastCalledWith(SESSION_A.id, { limit: 50, offset: 50 });
    await beginConfirmation(user);
    await finishRedaction(page);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => confirmation.resolve(CONFIRMED));
    expect(screen.getByText(REDACTED_PAGE.items[1].content)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Cached messages and scope labels were cleared");
    api.archiveAssistantSession.mockResolvedValue({ ...SESSION_A, status: "archived", version: 8 });
    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    expect(api.archiveAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id, 7);
  });

  it("cannot overwrite a fresh redacted export version with an old action confirmation", async () => {
    const user = userEvent.setup();
    const confirmation = deferred<AssistantActionPreview>();
    const exported = deferred<AssistantSessionExport>();
    api.confirmAssistantAction.mockReturnValue(confirmation.promise);
    api.exportAssistantSession.mockReturnValue(exported.promise);
    const originals = new Map(["createObjectURL", "revokeObjectURL"].map((key) => [key, Object.getOwnPropertyDescriptor(URL, key)]));
    const create = vi.fn((_blob: Blob) => "blob:epoch-export");
    const revoke = vi.fn();
    Object.defineProperties(URL, {
      createObjectURL: { configurable: true, value: create },
      revokeObjectURL: { configurable: true, value: revoke },
    });
    restoreDownloads = () => {
      for (const [key, original] of originals) {
        if (original) Object.defineProperty(URL, key, original);
        else Reflect.deleteProperty(URL, key);
      }
    };
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await openA(user);
    await user.click(screen.getByRole("button", { name: "Export conversation" }));
    expect(api.exportAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id);
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeDisabled();
    // Action review has its own busy state and is still reachable during export.
    await beginConfirmation(user);
    await act(async () => exported.resolve(SAFE_EXPORT));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(PREFIX[1].content)).not.toBeInTheDocument();
    expect(screen.getByText(REDACTED_PAGE.items[1].content)).toBeVisible();
    expect(screen.getByTestId("assistant-active-scope")).toHaveTextContent("No scope selected");
    expect(create).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:epoch-export");
    await act(async () => confirmation.resolve(CONFIRMED));
    expect(screen.getByRole("alert")).toHaveTextContent("Cached messages and scope labels were cleared");
    api.archiveAssistantSession.mockResolvedValue({ ...SAFE_EXPORT.session, status: "archived", version: 24 });
    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    expect(api.archiveAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id, 23);
  });

  it("does not close the newer conversation or clear its busy state when an old archive resolves", async () => {
    const user = userEvent.setup();
    const page = holdContinuation();
    const archived = deferred<AssistantSessionRecord>();
    const answer = deferred<AssistantAskResponse>();
    api.archiveAssistantSession.mockReturnValue(archived.promise);
    api.askWorkspaceAssistant.mockReturnValue(answer.promise);
    await openA(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(api.listAssistantTurns).toHaveBeenLastCalledWith(SESSION_A.id, { limit: 50, offset: 50 });
    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    expect(api.archiveAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id, 7);
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeDisabled();
    await finishRedaction(page);
    await openB(user);
    await beginBQuestion(user);
    await act(async () => archived.resolve({ ...SESSION_A, status: "archived", version: 8 }));
    expect(screen.getByText(B_ANSWER)).toBeVisible();
    expect(screen.getByRole("button", { name: "Working" })).toBeDisabled();
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => answer.resolve(B_RESPONSE));
    expect(screen.getByText(B_RESPONSE.assistant_turn.content)).toBeVisible();
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not surface an old deletion rejection or clear a newer conversation's busy state", async () => {
    const user = userEvent.setup();
    const page = holdContinuation();
    const deletion = deferred<void>();
    const answer = deferred<AssistantAskResponse>();
    api.deleteAssistantSession.mockReturnValue(deletion.promise);
    api.askWorkspaceAssistant.mockReturnValue(answer.promise);
    await openA(user);
    await user.click(screen.getByRole("button", { name: "Load more messages" }));
    expect(api.listAssistantTurns).toHaveBeenLastCalledWith(SESSION_A.id, { limit: 50, offset: 50 });
    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    expect(api.deleteAssistantSession).toHaveBeenCalledExactlyOnceWith(SESSION_A.id);
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeDisabled();
    await finishRedaction(page);
    await openB(user);
    await beginBQuestion(user);
    await act(async () => deletion.reject(new ApiError(409, "Old conversation retention prevents deletion.", null)));
    expect(screen.getByText(B_ANSWER)).toBeVisible();
    expect(screen.queryByText("Old conversation retention prevents deletion.")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Working" })).toBeDisabled();
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeDisabled();
    await act(async () => answer.resolve(B_RESPONSE));
    expect(screen.getByText(B_RESPONSE.assistant_turn.content)).toBeVisible();
    expect(screen.getByRole("button", { name: SESSION_B.title })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
