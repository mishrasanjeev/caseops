"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ResearchAnswerActions, ResearchAnswerStatus, useResearchAnswer } from "@/components/research/ResearchAnswerPanel";
import { ResearchAnswerView } from "@/components/research/ResearchAnswerView";
import { PageHeader } from "@/components/ui/PageHeader";
import { ReadingColumn } from "@/components/ui/ReadingColumn";
import { apiErrorMessage } from "@/lib/api/config";

export default function ResearchAnswerPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params?.id === "string" ? params.id : null;
  const answer = useResearchAnswer(id);
  const record = answer.data;
  return (
    <ReadingColumn className="flex flex-col gap-8" data-testid="research-answer-column">
      <PageHeader
        eyebrow="Research"
        title="Research answer"
        description={record?.query ?? "Short answer, detailed research, then the authorities and sources relied on."}
        actions={
          <Link href="/app/research" className="inline-flex items-center gap-1 text-sm underline">
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Research
          </Link>
        }
      />
      {answer.isPending ? <p role="status" className="text-sm">Loading research answer...</p> : null}
      {answer.isError ? (
        <p role="alert" className="text-sm text-[var(--color-danger-500)]">
          {apiErrorMessage(answer.error, "This research answer could not be loaded.")}
        </p>
      ) : null}
      {record ? <ResearchAnswerStatus record={record} onPermalinkPage /> : null}
      {record?.status === "answered" ? (
        <>
          <ResearchAnswerView record={record} />
          <ResearchAnswerActions record={record} />
        </>
      ) : null}
    </ReadingColumn>
  );
}
