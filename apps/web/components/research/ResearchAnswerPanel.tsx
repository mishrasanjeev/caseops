"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, FileText, Save } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { MatterName, MatterPicker, OPERATIONAL_MATTER_STATUSES } from "@/components/app/MatterPicker";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Label } from "@/components/ui/Label";
import { ReadingColumn } from "@/components/ui/ReadingColumn";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createResearchAnswer,
  fetchResearchAnswer,
  listResearchAnswers,
  researchAnswerPending,
  saveResearchAnswerToMatter,
  type ResearchAnswerRecord,
} from "@/lib/api/research-answers";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

import { ResearchAnswerView, researchAnswerToHtml, researchAnswerToText } from "./ResearchAnswerView";

const POLL_MS = 2_000;

export function useResearchAnswer(answerId: string | null) {
  return useQuery({
    queryKey: ["research-answer", answerId],
    queryFn: ({ signal }) => fetchResearchAnswer(answerId as string, { signal }),
    enabled: Boolean(answerId),
    refetchInterval: (query) => (researchAnswerPending(query.state.data) ? POLL_MS : false),
  });
}

export function ResearchAnswerActions({ record }: { record: ResearchAnswerRecord }) {
  const canSave = useCapability("matters:edit");
  const queryClient = useQueryClient();
  const [matterId, setMatterId] = useState(record.saved_matter?.id ?? record.context_matter?.id ?? "");
  const [notice, setNotice] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => saveResearchAnswerToMatter(record.id, matterId),
    onSuccess: (saved) => {
      queryClient.setQueryData(["research-answer", saved.id], saved);
      setNotice(`Saved to ${saved.saved_matter?.title ?? "the matter"}.`);
    },
  });
  if (record.status !== "answered") return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(researchAnswerToText(record));
      setNotice("Copied in the same section order.");
    } catch {
      setNotice("Copy was blocked by the browser. Use Download instead.");
    }
  };
  const download = () => {
    const blob = new Blob([researchAnswerToHtml(record)], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `caseops-research-${record.answer?.law_checked_as_of ?? "answer"}.html`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="flex flex-col gap-3 rounded-md border border-[var(--color-line)] p-3" data-testid="research-answer-actions">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={copy}>
          <Copy className="mr-1 h-3.5 w-3.5" aria-hidden /> Copy
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={download}>
          <Download className="mr-1 h-3.5 w-3.5" aria-hidden /> Download
        </Button>
        <Link href={`/app/research/answers/${encodeURIComponent(record.id)}`} className="inline-flex items-center gap-1 text-sm underline">
          <FileText className="h-3.5 w-3.5" aria-hidden /> Permanent link
        </Link>
      </div>
      {record.saved_matter ? (
        <p className="text-sm" data-testid="research-saved-matter">
          Saved to matter{" "}
          <Link className="underline" href={`/app/matters/${encodeURIComponent(record.saved_matter.id)}`}>
            {record.saved_matter.title}
          </Link>
          {record.saved_at ? ` on ${formatLegalDate(record.saved_at.slice(0, 10))}` : ""}.
        </p>
      ) : canSave ? (
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(event) => { event.preventDefault(); if (matterId) save.mutate(); }}
          aria-label="Save research to a matter"
        >
          <div className="min-w-0 flex-1">
            <MatterPicker
              id="research-save-matter"
              label="Save to matter"
              searchLabel="Search matters"
              value={matterId}
              onChange={(value) => setMatterId(value)}
              disabledReason={(matter) => (OPERATIONAL_MATTER_STATUSES.has(matter.status) ? null : "Closed matter")}
            />
          </div>
          <Button type="submit" size="sm" disabled={!matterId || save.isPending}>
            <Save className="mr-1 h-3.5 w-3.5" aria-hidden /> {save.isPending ? "Saving..." : "Save to matter"}
          </Button>
        </form>
      ) : null}
      {save.isError ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">{apiErrorMessage(save.error, "The answer could not be saved to that matter.")}</p> : null}
      {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    </div>
  );
}

/** A timestamp the API wrote without a zone (SQLite) is UTC, never local time. */
function serverTime(value: string): number {
  return Date.parse(/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`);
}

/** Whole seconds since `since`, ticking once a second while `active`. */
function useElapsedSeconds(since: string, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const start = serverTime(since);
  return Number.isFinite(start) ? Math.max(0, Math.floor((now - start) / 1_000)) : 0;
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const USUAL_SECONDS = 120;

export function ResearchAnswerStatus({
  record,
  onPermalinkPage = false,
  onUseSuggestion,
}: {
  record: ResearchAnswerRecord;
  /** On the answer's own page a link to it would point at the current URL. */
  onPermalinkPage?: boolean;
  /** Puts a suggested question in the question box; without it, suggestions link to Research. */
  onUseSuggestion?: (question: string) => void;
}) {
  const pending = researchAnswerPending(record);
  // Counted from the record's own creation time, so leaving the page and
  // coming back shows the true elapsed time, not time since this mount.
  const elapsed = useElapsedSeconds(record.created_at, pending);
  if (pending) {
    return (
      <div role="status" className="flex flex-col gap-1 text-sm text-[var(--color-ink-2)]" data-testid="research-answer-pending">
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-semibold text-[var(--color-ink)]" data-testid="research-answer-step">
            {record.status === "queued"
              ? "Queued. Waiting to start the research run."
              : "Retrieving statutes and judgments, then drafting and verifying citations."}
          </span>
          {/* Hidden from assistive technology: inside role=status a per-second
              counter would be announced every second. */}
          <span className="font-mono tabular-nums" data-testid="research-answer-elapsed" aria-hidden="true">
            {formatElapsed(elapsed)}
          </span>
        </p>
        <p data-testid="research-answer-expectation">
          {elapsed > USUAL_SECONDS
            ? "Research answers usually take one to two minutes. This one is taking longer than usual; it will finish or report a failure here."
            : "Research answers usually take one to two minutes."}{" "}
          {onPermalinkPage ? (
            "You can leave this page and come back; the answer will appear here."
          ) : (
            <>
              You can leave this page; the answer is kept at{" "}
              <Link className="underline" href={`/app/research/answers/${encodeURIComponent(record.id)}`}>
                its permanent link
              </Link>
              .
            </>
          )}
        </p>
      </div>
    );
  }
  if (record.status === "abstained" || record.status === "failed") {
    return (
      <div className="flex flex-col gap-2 text-sm" data-testid="research-answer-unavailable">
        <p role="alert" className="text-[var(--color-warn-700)]">
          {record.message ?? "No answer was produced."}
        </p>
        {(record.suggestions ?? []).length ? (
          <div className="flex flex-col gap-1" data-testid="research-answer-suggestions">
            <p className="font-medium text-[var(--color-ink-2)]">Questions CaseOps can research instead</p>
            <ul className="flex flex-col gap-1">
              {(record.suggestions ?? []).map((suggestion) => (
                <li key={suggestion}>
                  {onUseSuggestion ? (
                    <button
                      type="button"
                      className="text-left underline underline-offset-2"
                      onClick={() => onUseSuggestion(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ) : (
                    <Link
                      className="underline underline-offset-2"
                      href={`/app/research?tab=answer&q=${encodeURIComponent(suggestion)}${
                        record.context_matter ? `&matter=${encodeURIComponent(record.context_matter.id)}` : ""
                      }`}
                    >
                      {suggestion}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    );
  }
  return null;
}

export function ResearchAnswerPanel({
  initialQuestion,
  contextMatterId,
}: {
  initialQuestion: string;
  contextMatterId: string | null;
}) {
  const canGenerate = useCapability("recommendations:generate");
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState(initialQuestion);
  const [answerId, setAnswerId] = useState<string | null>(null);
  const answer = useResearchAnswer(answerId);
  const recent = useQuery({
    queryKey: ["research-answers", contextMatterId ?? "mine"],
    queryFn: ({ signal }) => listResearchAnswers({ matterId: contextMatterId, signal }),
  });
  const create = useMutation({
    mutationFn: () => createResearchAnswer({ query: question.trim(), contextMatterId }),
    onSuccess: (record) => {
      queryClient.setQueryData(["research-answer", record.id], record);
      setAnswerId(record.id);
      void queryClient.invalidateQueries({ queryKey: ["research-answers"] });
    },
  });
  const pending = create.isPending || researchAnswerPending(answer.data);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pending && question.trim().length >= 10) create.mutate();
  };
  const record = answer.data;
  return (
    <div className="flex flex-col gap-8">
      <Card data-testid="research-answer-panel">
        <CardHeader>
          <CardTitle as="h2" className="text-base">Research answer</CardTitle>
          <CardDescription>
            Ask a legal question. CaseOps answers in three parts: a short answer, detailed research, then the
            authorities and sources it relied on. Every citation links to the source.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {contextMatterId ? (
            <p className="text-sm" data-testid="research-context-matter">
              Using the recorded facts of matter <MatterName matterId={contextMatterId} />. Matter documents are not read.
            </p>
          ) : null}
          {canGenerate ? (
            <form onSubmit={submit} className="flex flex-col gap-2" aria-label="Ask a research question">
              <Label htmlFor="research-question">Legal question</Label>
              <Textarea
                id="research-question"
                rows={3}
                maxLength={2000}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="For example: What are the notice period and procedure for a complaint under Section 138 of the Negotiable Instruments Act, 1881?"
                disabled={pending}
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={pending || question.trim().length < 10}>
                  {pending ? "Researching..." : "Get research answer"}
                </Button>
                <span className="text-xs text-[var(--color-mute-2)]">At least 10 characters. Uses AI credits.</span>
              </div>
            </form>
          ) : (
            <p className="text-sm text-[var(--color-mute-2)]">
              Your role can search authorities but cannot generate AI research answers.
            </p>
          )}
          {create.isError ? (
            <p role="alert" className="text-sm text-[var(--color-danger-500)]">{apiErrorMessage(create.error, "The research request was not accepted. Try again.")}</p>
          ) : null}
          {answer.isError ? (
            <p role="alert" className="text-sm text-[var(--color-danger-500)]">{apiErrorMessage(answer.error, "The research answer could not be loaded.")}</p>
          ) : null}
          {record ? (
            <ResearchAnswerStatus
              record={record}
              onUseSuggestion={canGenerate ? (suggestion) => {
                setQuestion(suggestion);
                document.getElementById("research-question")?.focus();
              } : undefined}
            />
          ) : null}
          {recent.data?.items.length ? (
            <details className="text-sm">
              <summary className="cursor-pointer text-[var(--color-ink-2)]">
                {contextMatterId ? "Research saved to this matter" : "Your recent research answers"} ({recent.data.items.length})
              </summary>
              <ul className="mt-2 flex flex-col gap-1">
                {recent.data.items.map((item) => (
                  <li key={item.id} className="flex flex-wrap gap-x-2">
                    <Link className="underline" href={`/app/research/answers/${encodeURIComponent(item.id)}`}>
                      {item.query.length > 110 ? `${item.query.slice(0, 110)}...` : item.query}
                    </Link>
                    <span className="text-[var(--color-mute-2)]">
                      {formatLegalDate(item.created_at.slice(0, 10))} · {item.status}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </CardContent>
      </Card>
      {/* The answer is a document, not card content: it sits below the card in
          the same reading column as its permanent page, so no card nests in a card. */}
      {record?.status === "answered" ? (
        <ReadingColumn className="flex flex-col gap-8" data-testid="research-answer-column">
          <ResearchAnswerView record={record} />
          <ResearchAnswerActions record={record} />
        </ReadingColumn>
      ) : null}
    </div>
  );
}
