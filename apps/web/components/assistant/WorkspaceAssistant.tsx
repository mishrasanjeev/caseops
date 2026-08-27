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
import { useEffect, useMemo, useState } from "react";

import {
  archiveAssistantSession,
  askWorkspaceAssistant,
  createAssistantSession,
  deleteAssistantSession,
  exportAssistantSession,
  getAssistantSession,
  listAssistantSessions,
  listAssistantTurns,
  replaceAssistantScopes,
  searchAssistantScopes,
  type AssistantScopeInput,
  type AssistantScopeOption,
  type AssistantSessionRecord,
  type AssistantSessionSummary,
  type AssistantTurn,
} from "@/lib/api/workspace-assistant";
import { apiErrorMessage, isApiErrorShape } from "@/lib/api/config";

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

  useEffect(() => {
    let live = true;
    void listAssistantSessions()
      .then((response) => {
        if (live) setSessions(response.items);
      })
      .catch(() => {
        if (live) setSessions([]);
      });
    return () => {
      live = false;
    };
  }, []);

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
    setBusy("scope");
    setError(null);
    setPolicyDisabled(false);
    try {
      const response = await searchAssistantScopes(normalized);
      setScopeResults(response.items);
    } catch (caught) {
      if (isApiErrorShape(caught) && caught.problemType === "workspace_assistant_disabled") {
        setPolicyDisabled(true);
        setScopeResults([]);
      } else {
        setError(apiErrorMessage(caught, "Could not search the permitted workspace records."));
      }
    } finally {
      setBusy(null);
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
    setBusy("session");
    setError(null);
    try {
      const created = await createAssistantSession(
        `Ask · ${selected[0]?.label ?? "Workspace"}`,
        selected,
      );
      setActive(created);
      setTurns([]);
      setSessions((current) => [created, ...current.filter((row) => row.id !== created.id)]);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Could not start the workspace conversation."));
    } finally {
      setBusy(null);
    }
  }

  async function saveScopes() {
    if (!active || selected.length === 0) {
      setError("Select at least one workspace scope.");
      return;
    }
    setBusy("session");
    setError(null);
    try {
      const updated = await replaceAssistantScopes(active.id, active.version, selected);
      setActive(updated);
      setSessions((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (caught) {
      setError(apiErrorMessage(caught, "Could not update the active scope."));
    } finally {
      setBusy(null);
    }
  }

  async function openSession(summary: AssistantSessionSummary) {
    setBusy("session");
    setError(null);
    try {
      const [sessionRecord, history] = await Promise.all([
        getAssistantSession(summary.id),
        listAssistantTurns(summary.id),
      ]);
      setActive(sessionRecord);
      setTurns(history.items);
      setSelected(sessionRecord.scopes.map(fallbackScopeOption));
    } catch (caught) {
      setError(apiErrorMessage(caught, "Could not open that conversation."));
    } finally {
      setBusy(null);
    }
  }

  async function submitQuestion() {
    const normalized = question.trim();
    if (!active || normalized.length < 2) return;
    setBusy("ask");
    setError(null);
    try {
      const response = await askWorkspaceAssistant(active.id, active.version, normalized);
      setActive(response.session);
      setTurns((current) => [...current, response.user_turn, response.assistant_turn]);
      setQuestion("");
      setSessions((current) =>
        current.map((row) => (row.id === response.session.id ? response.session : row)),
      );
    } catch (caught) {
      setError(apiErrorMessage(caught, "The workspace assistant could not answer."));
    } finally {
      setBusy(null);
    }
  }

  async function archiveAndClear() {
    if (!active) return;
    setBusy("session");
    setError(null);
    try {
      const archived =
        active.status === "archived"
          ? active
          : await archiveAssistantSession(active.id, active.version);
      setSessions((current) => current.map((row) => (row.id === archived.id ? archived : row)));
      setActive(null);
      setTurns([]);
      setSelected([]);
      setScopeResults([]);
      setScopeQuery("");
    } catch (caught) {
      setError(apiErrorMessage(caught, "Could not archive the conversation."));
    } finally {
      setBusy(null);
    }
  }

  async function downloadExport() {
    if (!active) return;
    setBusy("export");
    setError(null);
    try {
      const exported = await exportAssistantSession(active.id);
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `caseops-assistant-${active.id}.json`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Could not export the conversation."));
    } finally {
      setBusy(null);
    }
  }

  async function requestDeletion() {
    if (!active) return;
    setBusy("session");
    setError(null);
    try {
      await deleteAssistantSession(active.id);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Deletion is not available for this retained conversation."));
    } finally {
      setBusy(null);
    }
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
              Workspace AI policy has not enabled this assistant.
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
                  turns.map((turn) => <TurnView key={turn.id} turn={turn} onSuggestion={setQuestion} />)
                )}
              </div>
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
                  disabled={busy !== null || question.trim().length < 2 || selectionChanged}
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
    </div>
  );
}

function TurnView({ turn, onSuggestion }: { turn: AssistantTurn; onSuggestion: (value: string) => void }) {
  const assistant = turn.role === "assistant";
  return (
    <article className={assistant ? "pr-4" : "pl-4 sm:pl-16"} data-turn-role={turn.role}>
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
                  <a
                    href={citation.source_url ?? "#"}
                    className="inline-flex max-w-full items-center gap-1 rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs font-semibold text-[var(--color-brand-700)] hover:border-[var(--color-brand-600)]"
                  >
                    <span className="max-w-56 truncate">{citation.label}</span>
                    <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                  </a>
                </li>
              ))}
            </ol>
          ) : null}
          {turn.proposed_actions.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {turn.proposed_actions.map((action) =>
                action.href && !action.requires_confirmation ? (
                  <a
                    key={action.proposal_id}
                    href={action.href}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 text-xs font-semibold text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
                  >
                    {action.label} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </a>
                ) : (
                  <button
                    key={action.proposal_id}
                    type="button"
                    disabled
                    title="Review and confirmation required"
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 text-xs font-semibold text-[var(--color-mute)] disabled:cursor-not-allowed"
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
        </div>
      </div>
    </article>
  );
}
