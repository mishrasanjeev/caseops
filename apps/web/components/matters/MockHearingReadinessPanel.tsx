"use client";

import { CheckCircle2, Circle, Clock3, FileUp, Loader2, RefreshCw, ScanText, XCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import type { MockHearingReadinessResponse } from "@/lib/api/schemas";
import { cn } from "@/lib/cn";

type Check = MockHearingReadinessResponse["checks"][number];

const STATUS_ICON: Record<Check["status"], typeof Circle> = {
  met: CheckCircle2,
  missing: Circle,
  pending: Clock3,
  blocked: XCircle,
};
const STATUS_TEXT: Record<Check["status"], string> = {
  met: "Done",
  missing: "Not done",
  pending: "In progress",
  blocked: "Blocked",
};

/** Where the documents page should land for an affidavit prerequisite. */
export function affidavitDocumentsHref(
  matterId: string,
  step: "upload" | "mark",
): string {
  return `/app/matters/${encodeURIComponent(matterId)}/documents?affidavit=${step}`;
}

/**
 * Start-session prerequisites for a mock hearing, with the one action that
 * moves the matter forward. Every check and the next action come from the
 * server's readiness read, which uses the start path's own predicates.
 */
export function MockHearingReadinessPanel({
  matterId,
  readiness,
  canRun,
  isRunning,
  isRefreshing,
  onRunAffidavitIntelligence,
  onRefresh,
}: {
  matterId: string;
  readiness: MockHearingReadinessResponse;
  canRun: boolean;
  isRunning: boolean;
  isRefreshing: boolean;
  onRunAffidavitIntelligence: (attachmentId: string) => void;
  onRefresh: () => void;
}) {
  const runTarget = readiness.affidavit_sources.find(
    (source) => source.attachment_id === readiness.next_action_attachment_id,
  );
  // The server offers an analysed affidavit again only when its readable text
  // changed since that run (for example OCR finished afterwards).
  const runLabel = runTarget?.latest_run_status
    ? "Re-run affidavit intelligence"
    : "Run affidavit intelligence";
  return (
    <section
      aria-labelledby="mock-hearing-readiness-title"
      className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4"
      data-testid="mock-hearing-readiness"
      data-ready={readiness.ready ? "true" : "false"}
    >
      <h3
        id="mock-hearing-readiness-title"
        className="text-sm font-semibold text-[var(--color-ink)]"
      >
        {readiness.ready ? "Ready to start" : "Before you can start a session"}
      </h3>
      <p
        id="mock-hearing-readiness-detail"
        className="mt-1 max-w-3xl text-sm text-[var(--color-mute)]"
        data-testid="mock-hearing-readiness-detail"
      >
        {readiness.next_action_detail}
      </p>
      <ol className="mt-3 grid gap-1.5" data-testid="mock-hearing-readiness-checks">
        {readiness.checks.map((check) => {
          const Icon = STATUS_ICON[check.status];
          return (
            <li
              key={check.key}
              className="flex items-start gap-2 text-sm"
              data-testid={`mock-hearing-check-${check.key}`}
              data-status={check.status}
            >
              <Icon
                aria-hidden
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  check.status === "met"
                    ? "text-[var(--color-success-600)]"
                    : check.status === "blocked"
                      ? "text-[var(--color-danger-600)]"
                      : "text-[var(--color-mute)]",
                )}
              />
              <span className="min-w-0">
                <span className="font-medium text-[var(--color-ink)]">{check.label}</span>
                <span className="sr-only">: {STATUS_TEXT[check.status]}.</span>
                <span className="block text-xs text-[var(--color-mute)]">{check.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {readiness.next_action === "run_affidavit_intelligence" &&
        readiness.next_action_attachment_id ? (
          canRun ? (
            <Button
              type="button"
              size="sm"
              disabled={isRunning}
              onClick={() =>
                onRunAffidavitIntelligence(readiness.next_action_attachment_id as string)
              }
              data-testid="mock-hearing-run-affidavit"
            >
              {isRunning ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ScanText className="h-4 w-4" aria-hidden />
              )}
              {isRunning ? "Running affidavit intelligence" : runLabel}
            </Button>
          ) : (
            <p className="text-sm text-[var(--color-mute)]">
              Ask a colleague who can generate hearing packs to run affidavit intelligence.
            </p>
          )
        ) : null}
        {readiness.next_action === "upload_affidavit" ? (
          <Button
            href={affidavitDocumentsHref(matterId, "upload")}
            size="sm"
            data-testid="mock-hearing-upload-affidavit"
          >
            <FileUp className="h-4 w-4" aria-hidden />
            Upload affidavit
          </Button>
        ) : null}
        {readiness.next_action === "mark_affidavit" ? (
          <Button
            href={affidavitDocumentsHref(matterId, "mark")}
            size="sm"
            data-testid="mock-hearing-mark-affidavit"
          >
            <FileUp className="h-4 w-4" aria-hidden />
            Mark the affidavit
          </Button>
        ) : null}
        {readiness.next_action === "wait_for_processing" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isRefreshing}
            onClick={onRefresh}
            data-testid="mock-hearing-readiness-refresh"
          >
            <RefreshCw className={cn("h-4 w-4", isRefreshing && "animate-spin")} aria-hidden />
            Check again
          </Button>
        ) : null}
      </div>
      {isRunning ? (
        <p role="status" className="mt-2 text-xs text-[var(--color-mute)]">
          Analysing {runTarget?.filename ?? "the affidavit"}. Start session unlocks when the
          question bank is ready.
        </p>
      ) : null}
    </section>
  );
}
