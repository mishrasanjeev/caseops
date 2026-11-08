"use client";

import {
  Archive,
  ArrowRight,
  Bot,
  Check,
  ChevronRight,
  Download,
  ExternalLink,
  FileSearch,
  LoaderCircle,
  LockKeyhole,
  MessageSquareText,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AssistantActionDialog } from "@/components/assistant/AssistantActionDialog";
import { AIFeedbackControls } from "@/components/ai/AIFeedbackControls";
import {
  archiveAssistantSession,
  askWorkspaceAssistant,
  createAssistantSession,
  deleteAssistantSession,
  exportAssistantSession,
  getAssistantSession,
  listAssistantSessions,
  listAssistantTurns,
  openAssistantCitation,
  replaceAssistantScopes,
  safeAssistantCitationHref,
  searchAssistantScopes,
  type AssistantScopeInput,
  type AssistantScopeOption,
  type AssistantActionPreview,
  type AssistantProposedAction,
  type AssistantSessionRecord,
  type AssistantSessionSummary,
  type AssistantTurn,
  type AssistantTurnPage,
} from "@/lib/api/workspace-assistant";
import { apiErrorMessage, isApiErrorShape, isNetworkError } from "@/lib/api/config";

const TRANSIENT_HISTORY_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const TRANSIENT_HISTORY_PROBLEMS = new Set([
  "request_timeout", "rate_limited", "too_many_requests", "internal_server_error",
  "bad_gateway", "service_unavailable", "gateway_timeout",
]);
const SOURCE_ACCESS_CHANGED = "Conversation sources or permissions changed. Cached messages and scope labels were cleared. Reload this conversation to recheck earlier messages.";

function hasChangedSourceAccess(turns: AssistantTurn[]) {
  return turns.some((turn) => turn.render_status === "permission_changed");
}

function isTransientHistoryError(error: unknown) {
  if (isNetworkError(error)) return true;
  if (!isApiErrorShape(error) || !TRANSIENT_HISTORY_STATUSES.has(error.status)) return false;
  const type = error.problemType;
  if (type != null && typeof type !== "string") return false;
  const problem = type?.split("/").pop()?.replaceAll("-", "_");
  return !problem || problem === String(error.status) || TRANSIENT_HISTORY_PROBLEMS.has(problem);
}

function mergeTurns(current: AssistantTurn[], incoming: AssistantTurn[]) {
  const byId = new Map(current.map((turn) => [turn.id, turn]));
  for (const turn of incoming) byId.set(turn.id, turn);
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}

function validateHistory(page: AssistantTurnPage, snapshot = false) {
  if (!page || !Array.isArray(page.items)
    || !Number.isInteger(page.limit) || page.limit < 1
    || (snapshot ? page.limit !== 200 || page.has_more : page.limit > 50)
    || page.offset !== 0
    || page.items.length > page.limit || typeof page.has_more !== "boolean"
    || (page.has_more && page.items.length === 0)) {
    throw new Error("Conversation history could not be read safely. Reopen the conversation.");
  }
  return page.has_more;
}

const SCOPE_LABELS: Record<AssistantScopeInput["scope_type"], string> = {
  tenant: "Workspace",
  client: "Client",
  matter: "Matter",
  ip_docket: "IP docket",
  ip_asset: "IP asset",
  trademark_application: "Application",
  ip_proceeding: "Proceeding",
  matter_document: "Matter document",
  ip_document: "IP document",
};

function scopeKey(scope: AssistantScopeInput) {
  return `${scope.scope_type}:${scope.scope_id}`;
}

function fallbackScopeOption(scope: AssistantScopeInput): AssistantScopeOption {
  return {
    ...scope,
    label: SCOPE_LABELS[scope.scope_type],
    secondary_text: scope.scope_id,
    href: "#",
    resource_version: "current",
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

export function WorkspaceAssistant() {
  const router = useRouter();
  const [sessions, setSessions] = useState<AssistantSessionSummary[]>([]);
  const [active, setActive] = useState<AssistantSessionRecord | null>(null);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [selected, setSelected] = useState<AssistantScopeOption[]>([]);
  const [scopeQuery, setScopeQuery] = useState("");
  const [scopeResults, setScopeResults] = useState<AssistantScopeOption[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<"scope" | "session" | "ask" | "export" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [policyDisabled, setPolicyDisabled] = useState(false);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [openingCitation, setOpeningCitation] = useState<string | null>(null);
  const readEpoch = useRef(0);
  const historyPending = useRef(false);
  const citationPending = useRef(false);
  const [actionReview, setActionReview] = useState<{
    turnId: string;
    action: AssistantProposedAction;
    epoch: number;
  } | null>(null);

  useEffect(() => {
    let live = true;
    const epoch = readEpoch.current;
    void listAssistantSessions()
      .then((response) => {
        if (live && readEpoch.current === epoch) setSessions(response.items);
      })
      .catch(() => {
        if (live && readEpoch.current === epoch) setSessions([]);
      });
    return () => {
      live = false;
      readEpoch.current += 1;
    };
  }, []);

  function resetConversationReads() {
    readEpoch.current += 1;
    historyPending.current = false;
    citationPending.current = false;
    setLoadingHistory(false);
    setOpeningCitation(null);
    setBusy(null);
    setHasMoreHistory(false);
    setTurns([]);
    setActionReview(null);
    setQuestion("");
    return readEpoch.current;
  }

  function hideConversation() {
    resetConversationReads();
    setActive(null);
    setSelected([]);
    setScopeResults([]);
  }

  function replaceCachedHistory(
    freshTurns: AssistantTurn[],
    hasMore: boolean,
    freshSession?: AssistantSessionRecord,
  ) {
    const epoch = resetConversationReads();
    setScopeResults([]);
    setSelected(freshSession ? freshSession.scopes.map(fallbackScopeOption) : []);
    if (freshSession) setActive(freshSession);
    setTurns(mergeTurns([], freshTurns));
    setHasMoreHistory(hasMore);
    setError(SOURCE_ACCESS_CHANGED);
    return epoch;
  }

  const selectionChanged = useMemo(() => {
    if (!active) return false;
    const current = active.scopes.map(scopeKey).sort();
    const next = selected.map(scopeKey).sort();
    return current.join("|") !== next.join("|");
  }, [active, selected]);

  async function runScopeSearch() {
    const normalized = scopeQuery.trim();
    if (normalized.length < 2) {
      setError("Enter at least two characters.");
      return;
    }
    const epoch = readEpoch.current;
    setBusy("scope");
    setError(null);
    setPolicyDisabled(false);
    try {
      const response = await searchAssistantScopes(normalized);
      if (readEpoch.current !== epoch) return;
      setScopeResults(response.items);
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      if (!isTransientHistoryError(caught)) hideConversation();
      if (isApiErrorShape(caught) && caught.problemType === "workspace_assistant_disabled") {
        setPolicyDisabled(true);
        setSessions([]);
        setScopeResults([]);
      } else {
        setError(apiErrorMessage(caught, "Could not search the permitted workspace records."));
      }
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  function addScope(option: AssistantScopeOption) {
    if (selected.some((scope) => scopeKey(scope) === scopeKey(option))) return;
    setSelected((current) => [...current, option].slice(0, 24));
  }

  function removeScope(option: AssistantScopeInput) {
    setSelected((current) => current.filter((scope) => scopeKey(scope) !== scopeKey(option)));
  }

  async function startSession() {
    if (selected.length === 0) {
      setError("Select at least one workspace scope.");
      return;
    }
    const epoch = resetConversationReads();
    setBusy("session");
    setError(null);
    try {
      const created = await createAssistantSession(
        `Ask · ${selected[0]?.label ?? "Workspace"}`,
        selected,
      );
      if (readEpoch.current !== epoch) return;
      setActive(created);
      setTurns([]);
      setSessions((current) => [created, ...current.filter((row) => row.id !== created.id)]);
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      hideConversation();
      setError(apiErrorMessage(caught, "Could not start the workspace conversation."));
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function saveScopes() {
    if (!active || selected.length === 0) {
      setError("Select at least one workspace scope.");
      return;
    }
    const epoch = resetConversationReads();
    setBusy("session");
    setError(null);
    try {
      const updated = await replaceAssistantScopes(active.id, active.version, selected);
      const history = await listAssistantTurns(updated.id, { latest: true });
      const hasMore = validateHistory(history);
      if (readEpoch.current !== epoch) return;
      setActive(updated);
      setTurns(mergeTurns([], history.items));
      setHasMoreHistory(hasMore);
      setSessions((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      hideConversation();
      setError(apiErrorMessage(caught, "Could not update the active scope."));
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function openSession(summary: AssistantSessionSummary): Promise<number | null> {
    const epoch = resetConversationReads();
    setActive(null);
    setSelected([]);
    setScopeResults([]);
    setBusy("session");
    setError(null);
    try {
      const [sessionRecord, history] = await Promise.all([
        getAssistantSession(summary.id),
        listAssistantTurns(summary.id, { latest: true }),
      ]);
      const hasMore = validateHistory(history);
      if (readEpoch.current !== epoch) return null;
      setActive(sessionRecord);
      setTurns(mergeTurns([], history.items));
      setHasMoreHistory(hasMore);
      setSelected(sessionRecord.scopes.map(fallbackScopeOption));
      return epoch;
    } catch (caught) {
      if (readEpoch.current !== epoch) return null;
      setError(apiErrorMessage(caught, "Could not open that conversation."));
      return null;
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function loadMoreHistory() {
    if (!active || !hasMoreHistory || historyPending.current) return;
    const epoch = readEpoch.current;
    historyPending.current = true;
    setLoadingHistory(true);
    setError(null);
    try {
      // A later clean page cannot authorize an earlier cached answer.
      const page = await listAssistantTurns(active.id, { snapshot: true });
      validateHistory(page, true);
      if (readEpoch.current !== epoch) return;
      if (hasChangedSourceAccess(page.items)) {
        replaceCachedHistory(page.items, false);
        return;
      }
      setTurns(mergeTurns([], page.items));
      setHasMoreHistory(false);
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      // The prefix was not reauthorized. Keep a retry for transient failures,
      // but never leave the old private messages or scope labels on screen.
      if (isTransientHistoryError(caught)) replaceCachedHistory([], true);
      else hideConversation();
      setError(apiErrorMessage(caught, "Could not load more conversation messages."));
    } finally {
      if (readEpoch.current === epoch) {
        historyPending.current = false;
        setLoadingHistory(false);
      }
    }
  }

  async function openCitation(citationId: string) {
    if (!active || citationPending.current) return;
    const epoch = readEpoch.current;
    citationPending.current = true;
    setOpeningCitation(citationId);
    setError(null);
    try {
      const opened = await openAssistantCitation(active.id, citationId);
      if (readEpoch.current !== epoch) return;
      router.push(safeAssistantCitationHref(opened.source_url));
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      // No response means no new access decision: keep the conversation for a
      // retry. Any answer from the server may mean access changed.
      if (!isTransientHistoryError(caught)) hideConversation();
      setError(apiErrorMessage(caught, "Could not open this citation. Reopen the conversation and try again."));
    } finally {
      if (readEpoch.current === epoch) {
        citationPending.current = false;
        setOpeningCitation(null);
      }
    }
  }

  async function submitQuestion() {
    const normalized = question.trim();
    if (!active || normalized.length < 2 || historyPending.current) return;
    const epoch = readEpoch.current;
    setBusy("ask");
    setError(null);
    try {
      const response = await askWorkspaceAssistant(active.id, active.version, normalized);
      if (readEpoch.current !== epoch) return;
      const incoming = [response.user_turn, response.assistant_turn];
      if (response.session.scope_state === "permission_changed" || hasChangedSourceAccess(incoming)) {
        replaceCachedHistory(incoming, hasMoreHistory, response.session);
      } else {
        setActive(response.session);
        setTurns((current) => mergeTurns(current, incoming));
        setQuestion("");
      }
      setSessions((current) =>
        current.map((row) => (row.id === response.session.id ? response.session : row)),
      );
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      const message = apiErrorMessage(caught, "The workspace assistant could not answer.");
      if (isApiErrorShape(caught) && caught.problemType === "workspace_assistant_unavailable") {
        // The server recorded the failed exchange and advanced the session:
        // reload that state, then offer the same question again.
        const reopened = await openSession(active);
        if (reopened !== null && readEpoch.current === reopened) {
          setQuestion(normalized);
          setError(message);
        }
        return;
      }
      // Keep the conversation and the typed question when the request never
      // reached a decision, so the user can simply ask again.
      if (!isTransientHistoryError(caught)) hideConversation();
      setError(message);
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function archiveAndClear() {
    if (!active) return;
    const epoch = readEpoch.current;
    setBusy("session");
    setError(null);
    try {
      const archived =
        active.status === "archived"
          ? active
          : await archiveAssistantSession(active.id, active.version);
      if (readEpoch.current !== epoch) return;
      setSessions((current) => current.map((row) => (row.id === archived.id ? archived : row)));
      hideConversation();
      setScopeQuery("");
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      setError(apiErrorMessage(caught, "Could not archive the conversation."));
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function downloadExport() {
    if (!active) return;
    let epoch = readEpoch.current;
    setBusy("export");
    setError(null);
    try {
      const exported = await exportAssistantSession(active.id);
      if (readEpoch.current !== epoch) return;
      if (exported.session.scope_state === "permission_changed" || hasChangedSourceAccess(exported.turns)) {
        epoch = replaceCachedHistory(exported.turns, false, exported.session);
      }
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `caseops-assistant-${active.id}.json`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      if (!isTransientHistoryError(caught)) hideConversation();
      setError(apiErrorMessage(caught, "Could not export the conversation."));
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  async function requestDeletion() {
    if (!active) return;
    const epoch = readEpoch.current;
    setBusy("session");
    setError(null);
    try {
      await deleteAssistantSession(active.id);
    } catch (caught) {
      if (readEpoch.current !== epoch) return;
      setError(apiErrorMessage(caught, "Deletion is not available for this retained conversation."));
    } finally {
      if (readEpoch.current === epoch) setBusy(null);
    }
  }

  function actionConfirmed(preview: AssistantActionPreview) {
    if (!active || !actionReview || actionReview.epoch !== readEpoch.current
      || preview.resulting_session_version === null) return;
    const version = preview.resulting_session_version;
    setActive((current) => (current ? { ...current, version } : current));
    setSessions((current) =>
      current.map((row) => (row.id === active.id ? { ...row, version } : row)),
    );
  }

  return (
    <div className="min-w-0">
      <header className="flex min-w-0 flex-col gap-4 border-b border-[var(--color-line)] pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-[var(--color-brand-700)]">
            <MessageSquareText className="h-4 w-4" aria-hidden />
            Permission-scoped assistant
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-[var(--color-ink)]">Ask this Workspace</h1>
          {active ? (
            <p className="mt-1 truncate text-sm text-[var(--color-mute)]">
              {active.title} · retained until {formatDate(active.retention_expires_at)}
            </p>
          ) : null}
        </div>
        {active ? (
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <button
              type="button"
              onClick={() => void downloadExport()}
              disabled={busy !== null}
              title="Export conversation"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] disabled:opacity-50"
              aria-label="Export conversation"
            >
              {busy === "export" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={() => void requestDeletion()}
              disabled={busy !== null}
              title="Delete conversation"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] disabled:opacity-50"
              aria-label="Delete conversation"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => void archiveAndClear()}
              disabled={busy !== null}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-[var(--color-line)] px-3 text-sm font-semibold text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] disabled:opacity-50"
            >
              <Archive className="h-4 w-4" aria-hidden /> Clear scope
            </button>
          </div>
        ) : null}
      </header>

      <div className="grid min-w-0 gap-8 py-6 xl:grid-cols-[minmax(240px,320px)_minmax(0,1fr)]">
        <aside className="min-w-0 xl:border-r xl:border-[var(--color-line)] xl:pr-6">
          <h2 className="text-sm font-semibold text-[var(--color-ink)]">Active scope</h2>
          <div className="mt-3 flex min-w-0 flex-wrap gap-2" data-testid="assistant-active-scope">
            {selected.length === 0 ? (
              <span className="text-sm text-[var(--color-mute)]">No scope selected</span>
            ) : (
              selected.map((scope) => (
                <span
                  key={scopeKey(scope)}
                  className="inline-flex max-w-full min-w-0 items-center gap-1 rounded-md border border-[var(--color-line)] bg-white py-1 pl-2.5 pr-1 text-xs text-[var(--color-ink-2)]"
                >
                  <span className="truncate">{scope.label}</span>
                  <button
                    type="button"
                    onClick={() => removeScope(scope)}
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-[var(--color-mute)] hover:bg-[var(--color-bg-2)] hover:text-[var(--color-ink)]"
                    aria-label={`Remove ${scope.label}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </span>
              ))
            )}
          </div>

          <form
            className="mt-4 flex min-w-0 gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void runScopeSearch();
            }}
          >
            <label className="relative min-w-0 flex-1">
              <span className="sr-only">Find workspace records</span>
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[var(--color-mute)]" aria-hidden />
              <input
                value={scopeQuery}
                onChange={(event) => setScopeQuery(event.target.value.slice(0, 160))}
                placeholder="Client, matter, mark, number…"
                className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white pl-9 pr-3 text-sm outline-none focus:border-[var(--color-brand-600)] focus:ring-2 focus:ring-[var(--color-brand-600)]/15"
              />
            </label>
            <button
              type="submit"
              disabled={busy !== null}
              title="Find permitted records"
              aria-label="Find permitted records"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[var(--color-ink)] text-white disabled:opacity-50"
            >
              {busy === "scope" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            </button>
          </form>

          {policyDisabled ? (
            <div className="mt-4 flex gap-2 border-l-2 border-[var(--color-warning-500)] pl-3 text-sm text-[var(--color-ink-2)]" role="status">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>
                Workspace AI policy has not enabled this assistant. A workspace owner can enable
                it under{" "}
                <Link
                  href="/app/admin"
                  className="font-semibold text-[var(--color-brand-700)] underline underline-offset-2"
                >
                  Admin → AI controls
                </Link>
                .
              </span>
            </div>
          ) : null}

          {scopeResults.length > 0 ? (
            <ul className="mt-3 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
              {scopeResults.map((option) => {
                const isSelected = selected.some((scope) => scopeKey(scope) === scopeKey(option));
                return (
                  <li key={scopeKey(option)} className="flex min-w-0 items-center gap-2 py-3">
                    <FileSearch className="h-4 w-4 shrink-0 text-[var(--color-brand-600)]" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-[var(--color-ink)]">{option.label}</span>
                      <span className="block truncate text-xs text-[var(--color-mute)]">{option.secondary_text}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => addScope(option)}
                      disabled={isSelected}
                      title={isSelected ? "Selected" : `Add ${option.label}`}
                      aria-label={isSelected ? `${option.label} selected` : `Add ${option.label}`}
                      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-ink-2)] disabled:bg-[var(--color-bg-2)] disabled:text-[var(--color-mute)]"
                    >
                      {isSelected ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}

          <div className="mt-4">
            {!active ? (
              <button
                type="button"
                onClick={() => void startSession()}
                disabled={busy !== null || selected.length === 0}
                className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-[var(--color-brand-600)] px-4 text-sm font-semibold text-white hover:bg-[var(--color-brand-700)] disabled:opacity-50"
              >
                <MessageSquareText className="h-4 w-4" aria-hidden /> Start conversation
              </button>
            ) : selectionChanged ? (
              <button
                type="button"
                onClick={() => void saveScopes()}
                disabled={busy !== null || selected.length === 0}
                className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-[var(--color-brand-600)] px-4 text-sm font-semibold text-white disabled:opacity-50"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden /> Apply scope
              </button>
            ) : null}
          </div>

          {sessions.length > 0 ? (
            <div className="mt-8 border-t border-[var(--color-line)] pt-5">
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">Recent conversations</h2>
              <ul className="mt-2 space-y-1">
                {sessions.slice(0, 8).map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      onClick={() => void openSession(row)}
                      disabled={busy !== null}
                      className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-[var(--color-bg-2)] disabled:opacity-50"
                    >
                      <span className="min-w-0 flex-1 truncate text-[var(--color-ink-2)]">{row.title}</span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-mute)]" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>

        <section className="flex min-h-[520px] min-w-0 flex-col" aria-label="Workspace conversation">
          {!active ? (
            <div className="flex flex-1 flex-col items-center justify-center border-y border-[var(--color-line)] py-16 text-center">
              <Bot className="h-8 w-8 text-[var(--color-brand-600)]" aria-hidden />
              <p className="mt-3 text-sm font-semibold text-[var(--color-ink)]">Select the records for this conversation</p>
              <p className="mt-1 max-w-md text-sm text-[var(--color-mute)]">Search “workspace” to use all currently permitted records.</p>
            </div>
          ) : (
            <>
              {active.scope_state === "permission_changed" ? (
                <div className="mb-4 flex gap-2 border-l-2 border-[var(--color-warning-500)] pl-3 text-sm text-[var(--color-ink-2)]" role="status">
                  <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  Scope permissions changed. Apply a current scope before relying on earlier answers.
                </div>
              ) : null}
              <div className="min-h-0 flex-1 space-y-5 overflow-y-auto border-y border-[var(--color-line)] py-5" data-testid="assistant-turns">
                {turns.length === 0 ? (
                  <div className="flex min-h-72 items-center justify-center text-sm text-[var(--color-mute)]">No questions yet</div>
                ) : (
                  turns.map((turn) => (
                    <TurnView
                      key={turn.id}
                      turn={turn}
                      sessionId={active.id}
                      openingCitation={openingCitation}
                      onOpenCitation={openCitation}
                      onSuggestion={setQuestion}
                      onAction={(action) => setActionReview({ turnId: turn.id, action, epoch: readEpoch.current })}
                    />
                  ))
                )}
              </div>
              {hasMoreHistory ? (
                <button
                  type="button"
                  onClick={() => void loadMoreHistory()}
                  disabled={busy !== null || loadingHistory}
                  className="mt-3 inline-flex h-9 items-center justify-center gap-2 self-start rounded-md border border-[var(--color-line)] px-3 text-sm font-semibold disabled:opacity-50"
                >
                  {loadingHistory ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
                  Load more messages
                </button>
              ) : null}
              <form
                className="mt-4 flex min-w-0 flex-col gap-2 sm:flex-row"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitQuestion();
                }}
              >
                <label className="min-w-0 flex-1">
                  <span className="sr-only">Ask this workspace</span>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value.slice(0, 2000))}
                    rows={2}
                    placeholder="Ask about the selected workspace records"
                    className="min-h-12 w-full min-w-0 resize-y rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--color-brand-600)] focus:ring-2 focus:ring-[var(--color-brand-600)]/15"
                  />
                </label>
                <button
                  type="submit"
                  disabled={busy !== null || loadingHistory || question.trim().length < 2 || selectionChanged}
                  className="inline-flex h-12 w-full shrink-0 items-center justify-center gap-2 rounded-md bg-[var(--color-ink)] px-4 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto"
                >
                  {busy === "ask" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {busy === "ask" ? "Working" : "Ask"}
                </button>
              </form>
            </>
          )}

          {error ? (
            <div className="mt-4 flex items-start gap-2 border-l-2 border-[var(--color-danger-500)] pl-3 text-sm text-[var(--color-danger-700)]" role="alert">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{error}</span>
            </div>
          ) : null}
        </section>
      </div>
      {active && actionReview ? (
        <AssistantActionDialog
          key={`${actionReview.turnId}:${actionReview.action.proposal_id}`}
          sessionId={active.id}
          sessionVersion={active.version}
          turnId={actionReview.turnId}
          action={actionReview.action}
          onClose={() => {
            if (readEpoch.current === actionReview.epoch) setActionReview(null);
          }}
          onConfirmed={actionConfirmed}
        />
      ) : null}
    </div>
  );
}

function isRenderableAction(action: AssistantProposedAction) {
  if (action.action_type === "search") {
    return !action.requires_confirmation && action.href?.startsWith("/app/research?query=") === true;
  }
  return action.action_type !== "navigation" && action.requires_confirmation;
}

function TurnView({
  turn,
  sessionId,
  openingCitation,
  onOpenCitation,
  onSuggestion,
  onAction,
}: {
  turn: AssistantTurn;
  sessionId: string;
  openingCitation: string | null;
  onOpenCitation: (citationId: string) => void;
  onSuggestion: (value: string) => void;
  onAction: (action: AssistantProposedAction) => void;
}) {
  const assistant = turn.role === "assistant";
  return (
    <article className={assistant ? "pr-4" : "pl-4 sm:pl-16"} data-turn-role={turn.role} data-turn-id={turn.id}>
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${assistant ? "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]" : "bg-[var(--color-ink)] text-white"}`}>
          {assistant ? <Bot className="h-4 w-4" aria-hidden /> : <MessageSquareText className="h-4 w-4" aria-hidden />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="whitespace-pre-wrap text-sm leading-6 text-[var(--color-ink-2)]">{turn.content}</div>
          {turn.citations.length > 0 ? (
            <ol className="mt-3 flex flex-wrap gap-2" aria-label="Answer sources">
              {turn.citations.map((citation) => (
                <li key={citation.id}>
                  <button
                    type="button"
                    onClick={() => onOpenCitation(citation.id)}
                    disabled={openingCitation !== null}
                    aria-label={`Open source: ${citation.label}`}
                    className="inline-flex max-w-full items-center gap-1 rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs font-semibold text-[var(--color-brand-700)] hover:border-[var(--color-brand-600)] disabled:opacity-50"
                  >
                    <span className="max-w-56 truncate">{citation.label}</span>
                    {openingCitation === citation.id ? <LoaderCircle className="h-3 w-3 shrink-0 animate-spin" aria-hidden /> : <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />}
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
          {turn.proposed_actions.some(isRenderableAction) ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {turn.proposed_actions.filter(isRenderableAction).map((action) =>
                action.action_type === "search" && action.href ? (
                  <a
                    key={action.proposal_id}
                    href={action.href}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 text-xs font-semibold text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
                  >
                    Search verified legal sources <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </a>
                ) : (
                  <button
                    key={action.proposal_id}
                    type="button"
                    disabled={!action.execution_available}
                    onClick={() => action.execution_available && onAction(action)}
                    title={
                      action.execution_available
                        ? "Review proposed action"
                        : (action.unavailable_reason ?? "Action unavailable")
                    }
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 text-xs font-semibold text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] disabled:cursor-not-allowed disabled:text-[var(--color-mute)]"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {action.label}
                  </button>
                ),
              )}
            </div>
          ) : null}
          {turn.suggested_searches.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {turn.suggested_searches.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => onSuggestion(suggestion)}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 text-xs font-semibold text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
                >
                  <Search className="h-3.5 w-3.5" aria-hidden /> {suggestion}
                </button>
              ))}
            </div>
          ) : null}
          {assistant && turn.model ? (
            <p className="mt-3 text-[11px] text-[var(--color-mute)]">
              {turn.model.provider} · {turn.model.model} · {turn.model.prompt_tokens + turn.model.completion_tokens} tokens
            </p>
          ) : null}
          {assistant ? (
            <AIFeedbackControls
              target={{
                surface: "workspace_assistant",
                sessionId,
                turnId: turn.id,
              }}
              testId={`workspace-assistant-feedback-${turn.id}`}
            />
          ) : null}
        </div>
      </div>
    </article>
  );
}
