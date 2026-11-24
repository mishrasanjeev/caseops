"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, FileText, Save } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import { MatterName, MatterPicker, OPERATIONAL_MATTER_STATUSES } from "@/components/app/MatterPicker";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Label } from "@/components/ui/Label";
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

export function ResearchAnswerStatus({ record }: { record: ResearchAnswerRecord }) {
  if (researchAnswerPending(record)) {
    return (
      <p role="status" className="text-sm text-[var(--color-ink-2)]" data-testid="research-answer-pending">
        {record.status === "queued" ? "Queued." : "Retrieving statutes and judgments, then drafting and verifying citations."}
        {" "}This usually takes under two minutes. You can keep working; the answer stays here.
      </p>
    );
  }
  if (record.status === "abstained" || record.status === "failed") {
    return (
      <p role="alert" className="text-sm text-[var(--color-warn-700)]" data-testid="research-answer-unavailable">
        {record.message ?? "No answer was produced."}
      </p>
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
        {record ? <ResearchAnswerStatus record={record} /> : null}
        {record?.status === "answered" ? (
          <>
            <ResearchAnswerActions record={record} />
            <ResearchAnswerView record={record} />
          </>
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
  );
}
