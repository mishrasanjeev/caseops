"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  bulkAcknowledgeIpCoverage,
  checkIpCalendarDrift,
  createIpControlReview,
  decideIpControlReviewException,
  decideIpCalendarReconciliationCandidate,
  deleteIpDocketQueue,
  fetchIpAssignedCoverage,
  fetchIpCalendarReconciliationCandidates,
  fetchIpControlReviews,
  fetchIpDailyDocket,
  fetchIpDocketQueues,
  recordIpControlReviewExport,
  recordIpControlReviewSample,
  saveIpDocketQueue,
  signOffIpControlReview,
  type IpAssignedCoverage,
  type IpCalendarDriftFinding,
  type IpCalendarReconciliationCandidate,
  type IpControlReview,
  type IpDailyDocketQueue,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { downloadControlReviewManifest } from "@/lib/ip/control-review-manifest";

const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const DUE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

const ESCALATION_REASON: Record<string, string> = {
  owner_inactive: "Responsible member is inactive",
  unacknowledged_critical: "Critical deadline not acknowledged",
  unowned: "No active member holds this deadline",
};

const EXCEPTION_KIND: Record<string, string> = {
  uncovered: "Deadline has no coverage",
  inactive_owner: "Coverage owner is inactive",
  unprojected_calendar: "Not projected to a calendar",
  open_incident: "Open incident",
};

const ACK_REASON: Record<string, string> = {
  already_acknowledged: "Already acknowledged",
  not_found: "No longer available to you",
  not_responsible: "You are not the responsible member",
  version_conflict: "Changed since you loaded this page",
  transfer_pending: "A transfer decision is outstanding",
};

/**
 * A count the backend could not establish.
 *
 * When a source is stale the API returns `null` rather than `0`, because
 * unknown work is not no work (UJ-50-EXC-03). Rendering it as a dash or a zero
 * would quietly undo that, so it is spelled out.
 */
function Count({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-[var(--color-mute)]">Unknown</span>;
  }
  return <span className="tabular-nums">{value}</span>;
}
function dueLabel(row: IpAssignedCoverage) {
  if (!row.due_on) return "No due date recorded";
  const on = DUE.format(new Date(`${row.due_on}T00:00:00`));
  if (row.days_until_due === null) return `Due ${on}`;
  if (row.days_until_due < 0) return `Due ${on} · ${Math.abs(row.days_until_due)} days overdue`;
  if (row.days_until_due === 0) return `Due ${on} · today`;
  return `Due ${on} · in ${row.days_until_due} ${row.days_until_due === 1 ? "day" : "days"}`;
}
function acknowledgementLabel(row: IpAssignedCoverage) {
  const docket = row.docket_identifier
    ? `${row.docket_title} (${row.docket_identifier})`
    : row.docket_title;
  const deadline = row.deadline_title?.trim() || "Untitled deadline";
  const due = row.due_on
    ? `due ${DUE.format(new Date(`${row.due_on}T00:00:00`))}`
    : "no due date recorded";
  return `${docket} · ${deadline} · ${due}`;
}

type AcknowledgementSelection = {
  expectedVersion: number;
  label: string;
};

type AcknowledgementSubmission = {
  coverageIds: readonly string[];
  expectedVersions: Readonly<Record<string, number>>;
  labels: Readonly<Record<string, string>>;
};

function acknowledgementSubmission(
  selected: ReadonlyMap<string, AcknowledgementSelection>,
): AcknowledgementSubmission {
  const entries = [...selected.entries()];
  return Object.freeze({
    coverageIds: Object.freeze(entries.map(([coverageId]) => coverageId)),
    expectedVersions: Object.freeze(
      Object.fromEntries(
        entries.map(([coverageId, snapshot]) => [coverageId, snapshot.expectedVersion]),
      ),
    ),
    labels: Object.freeze(
      Object.fromEntries(entries.map(([coverageId, snapshot]) => [coverageId, snapshot.label])),
    ),
  });
}

export default function IpDailyDocketPage() {
  // These mirror the API exactly: the daily docket needs ip:read, acting on
  // coverage or queues needs ip:write, and signing off needs ip:approve.
  // Showing a control the API will refuse is worse than hiding it.
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canApprove = useCapability("ip:approve");
  const [team, setTeam] = useState("");
  const [appliedTeam, setAppliedTeam] = useState<string | null>(null);

  const docket = useQuery({
    queryKey: ["ip-daily-docket", appliedTeam],
    queryFn: () => fetchIpDailyDocket({ team: appliedTeam }),
    enabled: canRead,
  });

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Daily docket" description="Deadline control for the IP portfolio." />
        <EmptyState
          title="You do not have access to the IP docket"
          description="Ask an owner or admin for the IP read capability."
        />
      </div>
    );
  }

  const filters = appliedTeam ? { team: appliedTeam } : {};

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title="Daily docket"
        description="Who holds which deadline, what is unacknowledged, and what must not be lost."
      />

      <ProvenanceCard
        docket={docket.data}
        isLoading={docket.isLoading}
        isError={docket.isError}
        error={docket.error}
        team={team}
        onTeamChange={setTeam}
        onApply={() => setAppliedTeam(team.trim() || null)}
        onRetry={() => docket.refetch()}
      />

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        <CapacityCard
          queues={docket.data?.queues ?? []}
          isLoading={docket.isPending}
          isError={docket.isError}
          error={docket.error}
          isSuccess={docket.isSuccess}
          onRetry={() => docket.refetch()}
        />
        <EscalationsCard
          escalations={docket.data?.escalations ?? []}
          isLoading={docket.isPending}
          isError={docket.isError}
          error={docket.error}
          isSuccess={docket.isSuccess}
          onRetry={() => docket.refetch()}
        />
      </div>

      {canWrite ? <AcknowledgementCard onChanged={() => docket.refetch()} /> : null}

      {canWrite ? <CalendarDriftCard canApprove={canApprove} /> : null}

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        {canWrite ? (
        <SavedQueuesCard
          filters={filters}
          onApply={(saved) => {
            const savedTeam = typeof saved.team === "string" ? saved.team : "";
            setTeam(savedTeam);
            setAppliedTeam(savedTeam || null);
          }}
        />
        ) : null}
        <ControlReviewCard filters={filters} canWrite={canWrite} canApprove={canApprove} />
      </div>
    </div>
  );
}

/**
 * CAL-OPS-09 requires the generation time, the filters, and the freshness of
 * the report to be visible. They are stated in one line rather than hidden
 * behind a tooltip, because a number whose provenance is unknown is not
 * evidence.
 */
function ProvenanceCard({
  docket,
  isLoading,
  isError,
  error,
  team,
  onTeamChange,
  onApply,
  onRetry,
}: {
  docket:
    | {
        generated_at: string;
        filters: Record<string, unknown>;
        stale_sources: string[];
        counts_are_complete: boolean;
      }
    | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  team: string;
  onTeamChange: (value: string) => void;
  onApply: () => void;
  onRetry: () => void;
}) {
  if (isError) {
    return (
      <EmptyState
        title="Could not load the daily docket"
        description={apiErrorMessage(error, "The IP API did not respond.")}
        action={<Button onClick={onRetry}>Retry</Button>}
      />
    );
  }

  const filterEntries = Object.entries(docket?.filters ?? {}).filter(
    ([, value]) => value !== null && value !== "",
  );

  return (
    <Card className="min-w-0" data-testid="ip-docket-provenance">
      <CardContent className="flex min-w-0 flex-col gap-3 py-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <span className="text-[var(--color-ink-2)] tabular-nums">
            {isLoading || !docket
              ? "Generating…"
              : `Generated ${STAMP.format(new Date(docket.generated_at))}`}
          </span>
          <span className="text-[var(--color-mute)]">
            {filterEntries.length
              ? `Filters: ${filterEntries.map(([key, value]) => `${key}=${String(value)}`).join(", ")}`
              : "No filters applied"}
          </span>
          {docket && !docket.counts_are_complete ? (
            <Badge tone="warning">
              {docket.stale_sources.length} stale source
              {docket.stale_sources.length === 1 ? "" : "s"} — counts unavailable
            </Badge>
          ) : docket ? (
            <Badge tone="success">All sources current</Badge>
          ) : null}
        </div>

        {docket && !docket.counts_are_complete ? (
          <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
            Counts below are shown as unknown rather than zero while{" "}
            {docket.stale_sources.join(", ")} {docket.stale_sources.length === 1 ? "is" : "are"}{" "}
            stale. Unknown work is not the same as no work.
          </p>
        ) : null}

        <form
          className="flex min-w-0 flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onApply();
          }}
        >
          <div className="flex min-w-0 flex-col gap-1">
            <Label htmlFor="docket-team">Team filter</Label>
            <Input
              id="docket-team"
              value={team}
              onChange={(event) => onTeamChange(event.target.value)}
              placeholder="All teams"
            />
          </div>
          <Button size="sm" type="submit" variant="secondary">
            Apply filter
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function CapacityCard({
  queues,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
}: {
  queues: IpDailyDocketQueue[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => Promise<unknown> | unknown;
}) {
  return (
    <Card className="min-w-0" data-testid="ip-docket-capacity">
      <CardHeader>
        <CardTitle as="h2">Workload and capacity</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0 overflow-x-auto">
        {isLoading ? (
          <div
            className="flex flex-col gap-2"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="ip-docket-capacity-loading"
          >
            <span className="sr-only">Loading workload and capacity.</span>
            <Skeleton className="h-16 w-full" aria-hidden="true" />
            <Skeleton className="h-16 w-full" aria-hidden="true" />
          </div>
        ) : isError ? (
          <QueryErrorState
            error={error}
            title="Could not load workload and capacity"
            onRetry={onRetry}
          />
        ) : isSuccess && queues.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">
            No deadline coverage is assigned in this view. Coverage appears here once a deadline
            has a responsible member.
          </p>
        ) : isSuccess ? (
          <table className="w-full min-w-[32rem] text-sm">
            <thead>
              <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase tracking-wide text-[var(--color-mute)]">
                <th scope="col" className="py-2 pr-3 font-medium">Member</th>
                <th scope="col" className="py-2 pr-3 font-medium">Availability</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Assigned</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Critical</th>
                <th scope="col" className="py-2 text-right font-medium">Unacknowledged</th>
              </tr>
            </thead>
            <tbody>
              {queues.map((queue) => (
                <tr
                  key={queue.membership_id}
                  className="border-b border-[var(--color-line)] last:border-b-0"
                  data-testid={`ip-docket-queue-${queue.membership_id}`}
                >
                  <td className="py-2 pr-3 font-medium">{queue.label}</td>
                  <td className="py-2 pr-3">
                    {queue.capacity_state === "available" ? (
                      <span className="text-[var(--color-ink-2)]">Available</span>
                    ) : (
                      <Badge tone="warning">Unavailable</Badge>
                    )}
                  </td>
                  <td
                    className="py-2 pr-3 text-right"
                    data-testid={`ip-docket-assigned-${queue.membership_id}`}
                  >
                    <Count value={queue.assigned_count} />
                  </td>
                  <td
                    className="py-2 pr-3 text-right"
                    data-testid={`ip-docket-critical-${queue.membership_id}`}
                  >
                    <Count value={queue.critical_count} />
                  </td>
                  <td
                    className="py-2 text-right"
                    data-testid={`ip-docket-unacknowledged-${queue.membership_id}`}
                  >
                    <Count value={queue.unacknowledged_count} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </CardContent>
    </Card>
  );
}

function EscalationsCard({
  escalations,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
}: {
  escalations: {
    coverage_id: string;
    docket_id: string;
    reason: string;
    critical: boolean;
    escalate_to_membership_id: string | null;
  }[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => Promise<unknown> | unknown;
}) {
  return (
    <Card className="min-w-0" data-testid="ip-docket-escalations">
      <CardHeader>
        <CardTitle as="h2">Escalations</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-2">
        {isLoading ? (
          <div
            className="flex flex-col gap-2"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="ip-docket-escalations-loading"
          >
            <span className="sr-only">Loading deadline escalations.</span>
            <Skeleton className="h-16 w-full" aria-hidden="true" />
            <Skeleton className="h-16 w-full" aria-hidden="true" />
          </div>
        ) : isError ? (
          <QueryErrorState
            error={error}
            title="Could not load deadline escalations"
            onRetry={onRetry}
          />
        ) : isSuccess && escalations.length === 0 ? (
          <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
            Nothing is escalating. Items appear here when a deadline has no active owner, or when a
            critical deadline has not been acknowledged — they cannot be filtered away.
          </p>
        ) : isSuccess ? (
          escalations.map((row) => (
            <div
              key={row.coverage_id}
              className="min-w-0 rounded-lg border border-[var(--color-line)] p-3"
              data-testid={`ip-docket-escalation-${row.coverage_id}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {ESCALATION_REASON[row.reason] ?? row.reason}
                </span>
                {row.critical ? <Badge tone="warning">Critical</Badge> : null}
              </div>
              <p className="mt-1 text-sm text-[var(--color-mute)]">
                {row.escalate_to_membership_id
                  ? "A named backup can pick this up."
                  : "There is no backup to fall back to; assign one."}
              </p>
            </div>
          ))
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * Bulk acknowledgement (CAL-OPS-09).
 *
 * The API validates per record and applies partially, so the outcome of every
 * requested row is reported back rather than summarised — a row that did not
 * acknowledge must never look like one that did.
 */
function AcknowledgementCard({ onChanged }: { onChanged: () => void }) {
  const [selected, setSelected] = useState<Map<string, AcknowledgementSelection>>(new Map());
  // Each selection retains the label and concurrency version the user saw. The
  // submit handler freezes an id-to-label map before the mutation starts, so a
  // pending refetch, rename or removal cannot turn the outcome back into an id.
  const [rejected, setRejected] = useState<
    { coverage_id: string; reason: string | null; label: string }[]
  >([]);

  const mine = useQuery({
    queryKey: ["ip-assigned-coverage"],
    queryFn: () => fetchIpAssignedCoverage({ unacknowledgedOnly: true }),
  });

  const rows = useMemo(() => {
    const list = mine.data?.coverages ?? [];
    return [...list].sort((a, b) => {
      if (a.due_on === b.due_on) return a.docket_title.localeCompare(b.docket_title);
      if (!a.due_on) return 1;
      if (!b.due_on) return -1;
      return a.due_on < b.due_on ? -1 : 1;
    });
  }, [mine.data]);

  const acknowledge = useMutation({
    mutationFn: (submission: AcknowledgementSubmission) =>
      bulkAcknowledgeIpCoverage({
        coverageIds: [...submission.coverageIds],
        expectedVersions: { ...submission.expectedVersions },
      }),
    onSuccess: async (result, submission) => {
      setRejected(
        result.outcomes
          .filter((outcome) => !outcome.acknowledged)
          .map((outcome, index) => ({
            coverage_id: outcome.coverage_id,
            reason: outcome.reason,
            label:
              submission.labels[outcome.coverage_id] ??
              `Deadline ${index + 1} from this acknowledgement request`,
          })),
      );
      setSelected(new Map());
      if (result.acknowledged_count) {
        toast.success(
          `${result.acknowledged_count} deadline${result.acknowledged_count === 1 ? "" : "s"} acknowledged.`,
        );
      }
      if (result.rejected_count) {
        toast.error(
          `${result.rejected_count} could not be acknowledged. Each one is listed with its reason.`,
        );
      }
      await mine.refetch();
      onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not acknowledge these deadlines.")),
  });

  function submitSelected() {
    const submission = acknowledgementSubmission(selected);
    acknowledge.mutate(submission);
  }

  const selectable = rows.filter((row) => !row.transfer_pending);

  useEffect(() => {
    if (window.location.hash === "#coverage-acknowledgements") {
      document.getElementById("coverage-acknowledgements")?.scrollIntoView({
        block: "start",
      });
    }
  }, []);

  return (
    <Card
      id="coverage-acknowledgements"
      className="min-w-0 scroll-mt-6"
      data-testid="ip-docket-acknowledge"
    >
      <CardHeader>
        <CardTitle as="h2">Your unacknowledged deadlines</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {mine.isPending ? (
          <div
            className="flex flex-col gap-2"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="ip-docket-acknowledgements-loading"
          >
            <span className="sr-only">Loading your unacknowledged deadlines.</span>
            <Skeleton className="h-16 w-full" aria-hidden="true" />
            <Skeleton className="h-16 w-full" aria-hidden="true" />
          </div>
        ) : mine.isError ? (
          <QueryErrorState
            error={mine.error}
            title="Could not load your unacknowledged deadlines"
            onRetry={() => mine.refetch()}
          />
        ) : mine.isSuccess && rows.length === 0 ? (
          <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
            You have acknowledged every deadline you hold. Acknowledging is what stops a critical
            deadline escalating, so this list is meant to reach empty.
          </p>
        ) : mine.isSuccess ? (
          <>
            {rows.map((row) => {
              const checkboxId = `ack-${row.coverage_id}`;
              return (
                <div
                  key={row.coverage_id}
                  className="flex min-w-0 items-start gap-3 rounded-lg border border-[var(--color-line)] p-3"
                  data-testid={`ip-docket-ack-${row.coverage_id}`}
                >
                  <input
                    id={checkboxId}
                    type="checkbox"
                    className="mt-1 h-4 w-4"
                    disabled={row.transfer_pending}
                    checked={selected.has(row.coverage_id)}
                    onChange={(event) => {
                      const next = new Map(selected);
                      if (event.target.checked) {
                        next.set(row.coverage_id, {
                          expectedVersion: row.reassignment_version,
                          label: acknowledgementLabel(row),
                        });
                      } else {
                        next.delete(row.coverage_id);
                      }
                      setSelected(next);
                    }}
                  />
                  <label htmlFor={checkboxId} className="min-w-0 flex-1 cursor-pointer">
                    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="break-words font-semibold">{row.docket_title}</span>
                      {row.docket_identifier ? (
                        <span className="font-mono text-xs tabular-nums text-[var(--color-mute)]">
                          {row.docket_identifier}
                        </span>
                      ) : null}
                      {row.critical ? <Badge tone="warning">Critical</Badge> : null}
                    </span>
                    <span className="mt-1 block text-sm tabular-nums text-[var(--color-ink-2)]">
                      {row.deadline_title ? `${row.deadline_title} · ` : ""}
                      {dueLabel(row)}
                    </span>
                    {row.transfer_pending ? (
                      <span className="mt-1 block text-sm text-[var(--color-mute)]">
                        A transfer decision is outstanding on this deadline, so it cannot be
                        acknowledged yet.
                      </span>
                    ) : null}
                  </label>
                </div>
              );
            })}

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={selected.size === 0 || acknowledge.isPending}
                onClick={submitSelected}
              >
                Acknowledge selected
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={selectable.length === 0 || acknowledge.isPending}
                onClick={() =>
                  setSelected(
                    new Map(
                      selectable.map((row) => [
                        row.coverage_id,
                        {
                          expectedVersion: row.reassignment_version,
                          label: acknowledgementLabel(row),
                        },
                      ]),
                    ),
                  )
                }
              >
                Select all {selectable.length}
              </Button>
            </div>
          </>
        ) : null}

        {rejected.length ? (
          <div
            className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3"
            data-testid="ip-docket-ack-rejected"
          >
            <p className="text-sm font-medium">Not acknowledged</p>
            <ul className="mt-1 flex flex-col gap-1 text-sm text-[var(--color-mute)]">
              {rejected.map((row) => (
                <li key={row.coverage_id}>
                  <span className="font-medium text-[var(--color-ink-2)]">{row.label}</span> —{" "}
                  {ACK_REASON[row.reason ?? ""] ?? "Could not be acknowledged"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

const DRIFT_LABEL: Record<string, string> = {
  moved: "Moved away from the CaseOps date",
  missing: "No longer on the calendar",
  unknown: "Could not be checked",
};

/**
 * External calendar drift (UJ-62-EXC-03).
 *
 * The projection is a copy; CaseOps holds the obligation. A copy edited or
 * deleted in the provider is reported rather than silently rewritten — it is
 * someone's own calendar — so the repair is a deliberate act.
 *
 * `unknown` is shown as its own outcome, never folded in with "fine": a
 * projection that could not be read is unverified, not verified.
 */
function CalendarDriftCard({ canApprove }: { canApprove: boolean }) {
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [findings, setFindings] = useState<IpCalendarDriftFinding[] | null>(null);
  const candidates = useQuery({
    queryKey: ["ip-calendar-reconciliation-candidates"],
    queryFn: () => fetchIpCalendarReconciliationCandidates({ limit: 100 }),
  });

  const check = useMutation({
    mutationFn: checkIpCalendarDrift,
    onSuccess: async (result) => {
      setCheckedAt(result.checked_at);
      setFindings(result.findings);
      await candidates.refetch();
      toast.success(
        result.findings.length
          ? `${result.findings.length} projected event${result.findings.length === 1 ? "" : "s"} no longer match CaseOps.`
          : "Every projected event still matches CaseOps.",
      );
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not check the calendars.")),
  });

  const unknown = (findings ?? []).filter((row) => row.drift_status === "unknown").length;
  const pendingCandidates = candidates.data?.candidates ?? [];

  async function candidateDecided(candidateId: string) {
    setFindings((current) =>
      current?.filter((row) => row.reconciliation_candidate_id !== candidateId) ?? null,
    );
    await candidates.refetch();
  }

  return (
    <Card className="min-w-0" data-testid="ip-docket-drift">
      <CardHeader>
        <CardTitle as="h2">External calendar copies</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
          Deadlines are copied to connected calendars. If a copy is moved or deleted there, the
          calendar stops agreeing with the deadline CaseOps holds. Copies are reported here rather
          than silently rewritten, because they sit in someone&rsquo;s own calendar.
        </p>

        <div>
          <Button size="sm" disabled={check.isPending} onClick={() => check.mutate()}>
            Check calendar copies
          </Button>
        </div>

        {findings !== null ? (
          findings.length === 0 ? (
            <p className="text-sm tabular-nums text-[var(--color-ink-2)]" data-testid="ip-docket-drift-clean">
              Every projected event matched when checked
              {checkedAt ? ` at ${STAMP.format(new Date(checkedAt))}` : ""}.
            </p>
          ) : (
            <>
              {unknown ? (
                <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
                  {unknown} could not be read, so {unknown === 1 ? "it is" : "they are"} unverified
                  rather than confirmed correct.
                </p>
              ) : null}
              <ul className="flex min-w-0 flex-col gap-2" data-testid="ip-docket-drift-findings">
                {findings.map((row) => (
                  <li
                    key={row.sync_id}
                    className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm"
                    data-testid={`ip-docket-drift-${row.sync_id}`}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">
                        {DRIFT_LABEL[row.drift_status] ?? row.drift_status}
                      </span>
                      {row.drift_status === "unknown" ? (
                        <Badge tone="neutral">Unverified</Badge>
                      ) : (
                        <Badge tone="warning">Out of step</Badge>
                      )}
                    </span>
                    <span className="mt-1 block text-[var(--color-mute)]">{row.detail}</span>
                  </li>
                ))}
              </ul>
            </>
          )
        ) : null}

        <div className="border-t border-[var(--color-line)] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-[var(--color-ink-2)]">Waiting for review</p>
            {pendingCandidates.length ? (
              <Badge tone="warning">{pendingCandidates.length}</Badge>
            ) : null}
          </div>

          {candidates.isPending ? (
            <div className="mt-3 flex flex-col gap-2" role="status" aria-label="Loading calendar reviews">
              <Skeleton className="h-24 w-full" />
            </div>
          ) : candidates.isError ? (
            <div className="mt-3">
              <QueryErrorState
                error={candidates.error}
                title="Could not load calendar reviews"
                onRetry={() => candidates.refetch()}
              />
            </div>
          ) : pendingCandidates.length ? (
            <ul className="mt-3 flex min-w-0 flex-col gap-3" data-testid="ip-calendar-candidates">
              {pendingCandidates.map((candidate) => (
                <CalendarReconciliationCandidateRow
                  key={candidate.id}
                  candidate={candidate}
                  canApprove={canApprove}
                  onDecided={() => candidateDecided(candidate.id)}
                />
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-[var(--color-mute)]" data-testid="ip-calendar-candidates-empty">
              No calendar-copy reviews are waiting.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function snapshotString(snapshot: Record<string, unknown>, key: string) {
  const value = snapshot[key];
  return typeof value === "string" && value ? value : null;
}

function CalendarReconciliationCandidateRow({
  candidate,
  canApprove,
  onDecided,
}: {
  candidate: IpCalendarReconciliationCandidate;
  canApprove: boolean;
  onDecided: () => Promise<void>;
}) {
  const [evidenceReference, setEvidenceReference] = useState("");
  const decision = useMutation({
    mutationFn: (action: "accept" | "reject") =>
      decideIpCalendarReconciliationCandidate(candidate.id, {
        action,
        evidenceReference: evidenceReference.trim(),
        expectedSnapshotSha256: candidate.snapshot_sha256,
      }),
    onSuccess: async (_result, action) => {
      toast.success(
        action === "reject"
          ? "The CaseOps calendar copy is queued for restoration."
          : "The calendar review is recorded.",
      );
      await onDecided();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not record the calendar review.")),
  });
  const expectedDate = snapshotString(candidate.expected_snapshot, "occurs_on");
  const observedDate = snapshotString(candidate.observed_snapshot, "start_date");
  const validEvidence = evidenceReference.trim().length >= 8;

  return (
    <li
      className="min-w-0 rounded-lg border border-[var(--color-line)] p-3"
      data-testid={`ip-calendar-candidate-${candidate.id}`}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {DRIFT_LABEL[candidate.drift_status] ?? candidate.drift_status}
          </p>
          <p className="mt-1 break-words text-sm text-[var(--color-mute)]">
            CaseOps {expectedDate ?? "date unavailable"}
            {observedDate ? ` · Calendar ${observedDate}` : " · Calendar date unavailable"}
          </p>
        </div>
        <Badge tone={candidate.drift_status === "unknown" ? "neutral" : "warning"}>
          {candidate.drift_status === "unknown" ? "Unverified" : "Review"}
        </Badge>
      </div>

      {canApprove ? (
        <div className="mt-3 flex min-w-0 flex-col gap-2">
          <Label htmlFor={`calendar-evidence-${candidate.id}`}>Review evidence reference</Label>
          <Input
            id={`calendar-evidence-${candidate.id}`}
            value={evidenceReference}
            maxLength={500}
            placeholder="Matter note or review reference"
            onChange={(event) => setEvidenceReference(event.target.value)}
          />
          <div className="flex min-w-0 flex-wrap gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={!validEvidence || decision.isPending}
              onClick={() => decision.mutate("accept")}
            >
              Record review
            </Button>
            {candidate.drift_status === "moved" &&
            snapshotString(candidate.observed_snapshot, "provider_precondition_revision") ? (
              <Button
                size="sm"
                disabled={!validEvidence || decision.isPending}
                onClick={() => decision.mutate("reject")}
              >
                Restore from CaseOps
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-[var(--color-mute)]">
          IP approval is required to close this review.
        </p>
      )}
    </li>
  );
}

function SavedQueuesCard({
  filters,
  onApply,
}: {
  filters: Record<string, unknown>;
  onApply: (filters: Record<string, unknown>) => void;
}) {
  const [name, setName] = useState("");
  const queues = useQuery({ queryKey: ["ip-docket-queues"], queryFn: fetchIpDocketQueues });

  const save = useMutation({
    mutationFn: () => saveIpDocketQueue({ name: name.trim(), filters }),
    onSuccess: async () => {
      toast.success("Queue saved.");
      setName("");
      await queues.refetch();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save this queue.")),
  });

  const remove = useMutation({
    mutationFn: (queueId: string) => deleteIpDocketQueue(queueId),
    onSuccess: async () => {
      toast.success("Queue deleted.");
      await queues.refetch();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not delete this queue.")),
  });

  const rows = queues.data?.queues ?? [];

  return (
    <Card className="min-w-0" data-testid="ip-docket-queues">
      <CardHeader>
        <CardTitle as="h2">Saved queues</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {queues.isPending ? (
          <div
            className="flex flex-col gap-2"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="ip-docket-saved-queues-loading"
          >
            <span className="sr-only">Loading saved queues.</span>
            <Skeleton className="h-16 w-full" aria-hidden="true" />
            <Skeleton className="h-16 w-full" aria-hidden="true" />
          </div>
        ) : queues.isError ? (
          <QueryErrorState
            error={queues.error}
            title="Could not load saved queues"
            onRetry={() => queues.refetch()}
          />
        ) : queues.isSuccess && rows.length === 0 ? (
          <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
            No saved queues yet. Save the filters you triage with each morning so the same view is
            one click away, and share it with a team so everyone triages the same list.
          </p>
        ) : queues.isSuccess ? (
          rows.map((queue) => (
            <div
              key={queue.id}
              className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-line)] p-3"
              data-testid={`ip-docket-queue-saved-${queue.id}`}
            >
              <div className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-2">
                  <span className="break-words font-medium">{queue.name}</span>
                  <Badge tone={queue.scope === "team" ? "brand" : "neutral"}>
                    {queue.scope === "team" ? "Team" : "Personal"}
                  </Badge>
                </span>
                {queue.description ? (
                  <span className="mt-1 block text-sm text-[var(--color-mute)]">
                    {queue.description}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={() => onApply(queue.filters)}>
                  Apply
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(queue.id)}
                >
                  Delete
                </Button>
              </div>
            </div>
          ))
        ) : null}

        {queues.isSuccess ? <form
          className="flex min-w-0 flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="flex min-w-0 flex-col gap-1">
            <Label htmlFor="queue-name">Save current filters as</Label>
            <Input
              id="queue-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Critical this week"
            />
          </div>
          <Button size="sm" type="submit" variant="secondary" disabled={name.trim().length < 2 || save.isPending}>
            Save queue
          </Button>
        </form> : null}
      </CardContent>
    </Card>
  );
}

/**
 * The control review and its sign-off (CAL-OPS-09, CAL-OPS-13).
 *
 * The review is generated, then signed. Sign-off is refused by the API while
 * the review is incomplete or an export failed, so the button states which of
 * those is blocking rather than simply being inert.
 */
function ControlReviewCard({
  filters,
  canWrite,
  canApprove,
}: {
  filters: Record<string, unknown>;
  // Recording an export is a write, so a read-only member must not be offered
  // a control the API will refuse.
  canWrite: boolean;
  canApprove: boolean;
}) {
  const [review, setReview] = useState<IpControlReview | null>(null);
  const [attestation, setAttestation] = useState("");
  const [decisionKey, setDecisionKey] = useState("");
  const [decisionDisposition, setDecisionDisposition] = useState<
    "resolved" | "annotated"
  >("resolved");
  const [decisionAnnotation, setDecisionAnnotation] = useState("");
  const [decisionEvidence, setDecisionEvidence] = useState("");
  const [sampleDocketId, setSampleDocketId] = useState("");
  const [sampleSource, setSampleSource] = useState("");
  const [sampleCalculation, setSampleCalculation] = useState("");
  const [sampleCoverage, setSampleCoverage] = useState("");
  const [sampleNotes, setSampleNotes] = useState("");

  const history = useQuery({
    queryKey: ["ip-control-reviews"],
    queryFn: fetchIpControlReviews,
  });

  useEffect(() => {
    if (!review && history.data?.reviews[0]) {
      const latest = history.data.reviews[0];
      setReview(latest);
      setSampleDocketId(latest.snapshot.included_records[0]?.docket_id ?? "");
    }
  }, [history.data, review]);

  const generate = useMutation({
    mutationFn: () => createIpControlReview({ filters }),
    onSuccess: (result) => {
      setReview(result);
      setDecisionKey("");
      setSampleDocketId(result.snapshot.included_records[0]?.docket_id ?? "");
      void history.refetch();
      toast.success("Control review generated.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not generate the review.")),
  });

  const decideException = useMutation({
    mutationFn: () => {
      const [docketId, kind] = decisionKey.split(":");
      return decideIpControlReviewException(review!.id, docketId, kind, {
        expectedVersion: review!.version,
        disposition: decisionDisposition,
        annotation: decisionAnnotation.trim(),
        evidenceReference: decisionEvidence.trim(),
      });
    },
    onSuccess: (result) => {
      setReview(result);
      setDecisionKey("");
      setDecisionDisposition("resolved");
      setDecisionAnnotation("");
      setDecisionEvidence("");
      toast.success("Exception decision recorded.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not record the decision.")),
  });

  const recordSample = useMutation({
    mutationFn: () =>
      recordIpControlReviewSample(review!.id, {
        expectedVersion: review!.version,
        docketId: sampleDocketId,
        sourceEvidenceReference: sampleSource.trim(),
        calculationEvidenceReference: sampleCalculation.trim(),
        coverageEvidenceReference: sampleCoverage.trim(),
        notes: sampleNotes.trim() || null,
      }),
    onSuccess: (result) => {
      setReview(result);
      setSampleSource("");
      setSampleCalculation("");
      setSampleCoverage("");
      setSampleNotes("");
      toast.success("Independent sample recorded.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not record the sample.")),
  });

  /**
   * Produce the manifest, then report what actually happened.
   *
   * The API only records the outcome, so reporting "generated" without having
   * produced a document would claim an export that never occurred. The
   * document is built first; only if that succeeds is success reported, and a
   * failure is recorded with a redacted reason that names no record.
   */
  const exportManifest = useMutation({
    mutationFn: async () => {
      const target = review!;
      try {
        downloadControlReviewManifest(target);
      } catch {
        // The recorded failure is what blocks sign-off, so it is kept and
        // shown rather than discarded in favour of a toast.
        const failed = await recordIpControlReviewExport(target.id, {
          outcome: "failed",
          errorRedacted: "The manifest could not be produced in this browser.",
        });
        return { produced: false as const, review: failed };
      }
      const recorded = await recordIpControlReviewExport(target.id, {
        outcome: "generated",
      });
      return { produced: true as const, review: recorded };
    },
    onSuccess: (result) => {
      setReview(result.review);
      if (result.produced) {
        toast.success("Manifest exported. It is ready to print or file.");
      } else {
        toast.error(
          "The manifest could not be produced, so the export is recorded as failed.",
        );
      }
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not record the export.")),
  });

  const sign = useMutation({
    mutationFn: () =>
      signOffIpControlReview(review!.id, {
        expectedVersion: review!.version,
        attestation: attestation.trim(),
      }),
    onSuccess: (result) => {
      setReview(result);
      setAttestation("");
      toast.success(
        result.signoff_status === "signed"
          ? "Control review signed off."
          : "Preparer signature recorded. Independent review is still required.",
      );
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not sign off this review.")),
  });

  // Every review write uses an optimistic-lock version. Keep actions serial so
  // a fast follow-up cannot submit the stale version while another audit write
  // (notably the export record) is still completing.
  const reviewWritePending =
    generate.isPending ||
    decideException.isPending ||
    recordSample.isPending ||
    exportManifest.isPending ||
    sign.isPending;

  const blockedBy = !review
    ? null
    : review.completeness_status !== "complete"
      ? "This review is incomplete, so it cannot be signed."
      : review.pending_exception_count > 0
        ? `Record a decision for all ${review.pending_exception_count} pending exception${review.pending_exception_count === 1 ? "" : "s"} before signing.`
        : review.export_status === "failed"
          ? "The last export failed, so this review cannot be signed. Export it again."
          : null;

  const selectedException = review?.mandatory_exceptions.find(
    (exception) => `${exception.docket_id}:${exception.kind}` === decisionKey,
  );
  const sampleComplete =
    sampleDocketId.length > 0 &&
    sampleSource.trim().length >= 3 &&
    sampleCalculation.trim().length >= 3 &&
    sampleCoverage.trim().length >= 3;
  const reviewerSampleRequirementMet =
    !review ||
    review.signoff_status !== "awaiting_second_signature" ||
    review.reviewer_samples.length >= review.review_policy.required_sample_size;

  return (
    <Card className="min-w-0" data-testid="ip-docket-control-review">
      <CardHeader>
        <CardTitle as="h2">Control review</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {!review ? (
          <>
            <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
              A control review is the signed record that the docket was checked
              on a given day. It captures the generation time, the filters used,
              and which sources were stale, so what is signed is exactly what
              was produced.
            </p>
            {canWrite ? (
              <div>
                <Button
                  size="sm"
                  disabled={generate.isPending}
                  onClick={() => generate.mutate()}
                >
                  Generate control review
                </Button>
              </div>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                Your role can view the docket but cannot create a control-review
                record.
              </p>
            )}
          </>
        ) : (
          <>
            {history.data && history.data.reviews.length > 1 ? (
              <div className="max-w-md">
                <Label htmlFor="control-review-history">Recent control review</Label>
                <select
                  id="control-review-history"
                  className="mt-1 h-9 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-sm"
                  value={review.id}
                  onChange={(event) => {
                    const selected = history.data.reviews.find(
                      (item) => item.id === event.target.value,
                    );
                    if (selected) {
                      setReview(selected);
                      setSampleDocketId(
                        selected.snapshot.included_records[0]?.docket_id ?? "",
                      );
                    }
                  }}
                >
                  {history.data.reviews.map((item) => (
                    <option key={item.id} value={item.id}>
                      {STAMP.format(new Date(item.generated_at))} · {item.signoff_status}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <dl className="grid min-w-0 gap-x-4 gap-y-2 sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-[var(--color-mute)]">
                  Generated
                </dt>
                <dd className="text-sm tabular-nums">
                  {STAMP.format(new Date(review.generated_at))}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-[var(--color-mute)]">
                  Records reviewed
                </dt>
                <dd className="text-sm tabular-nums">
                  {review.report.docket_count}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase tracking-wide text-[var(--color-mute)]">
                  Manifest SHA-256
                </dt>
                <dd className="break-all font-mono text-xs text-[var(--color-ink-2)]">
                  {review.manifest_sha256}
                </dd>
              </div>
            </dl>

            {review.incompleteness_reasons.length ? (
              <div data-testid="ip-docket-review-incomplete">
                <p className="text-sm font-medium">Incomplete</p>
                <ul className="mt-1 flex flex-col gap-1 text-sm text-[var(--color-mute)]">
                  {review.incompleteness_reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {review.mandatory_exceptions.length ? (
              <div data-testid="ip-docket-review-exceptions">
                <p className="text-sm font-medium">
                  Exceptions ({review.pending_exception_count} pending of{" "}
                  {review.mandatory_exceptions.length})
                </p>
                <ul className="mt-2 flex flex-col gap-2 text-sm text-[var(--color-mute)]">
                  {review.mandatory_exceptions.map((exception, index) => (
                    <li
                      className="flex min-w-0 items-center justify-between gap-2 border-b border-[var(--color-border)] pb-2"
                      key={`${exception.docket_id}-${exception.kind}-${index}`}
                    >
                      <span>
                        {EXCEPTION_KIND[exception.kind] ?? exception.kind}
                      </span>
                      {review.exception_decisions.some(
                        (decision) =>
                          decision.docket_id === exception.docket_id &&
                          decision.exception_kind === exception.kind,
                      ) ? (
                        <Badge tone="success">Recorded</Badge>
                      ) : canWrite && review.signatures.length === 0 ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={reviewWritePending}
                          onClick={() =>
                            setDecisionKey(
                              `${exception.docket_id}:${exception.kind}`,
                            )
                          }
                        >
                          Record decision
                        </Button>
                      ) : (
                        <Badge tone="warning">Pending</Badge>
                      )}
                    </li>
                  ))}
                </ul>
                {selectedException ? (
                  <div className="mt-3 grid gap-3 border-l-2 border-[var(--color-line)] pl-3">
                    <div>
                      <Label htmlFor="control-review-disposition">
                        Decision
                      </Label>
                      <select
                        id="control-review-disposition"
                        className="mt-1 h-9 w-full max-w-xs rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-sm"
                        value={decisionDisposition}
                        onChange={(event) =>
                          setDecisionDisposition(
                            event.target.value as "resolved" | "annotated",
                          )
                        }
                      >
                        <option value="resolved">Resolved</option>
                        <option value="annotated">
                          Annotated for follow-up
                        </option>
                      </select>
                    </div>
                    <div>
                      <Label htmlFor="control-review-decision-note">
                        Decision note
                      </Label>
                      <Textarea
                        id="control-review-decision-note"
                        value={decisionAnnotation}
                        onChange={(event) =>
                          setDecisionAnnotation(event.target.value)
                        }
                      />
                    </div>
                    <div>
                      <Label htmlFor="control-review-decision-evidence">
                        Evidence reference
                      </Label>
                      <Input
                        id="control-review-decision-evidence"
                        value={decisionEvidence}
                        onChange={(event) =>
                          setDecisionEvidence(event.target.value)
                        }
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={
                          decisionAnnotation.trim().length < 5 ||
                          decisionEvidence.trim().length < 3 ||
                          reviewWritePending
                        }
                        onClick={() => decideException.mutate()}
                      >
                        Save immutable decision
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={reviewWritePending}
                        onClick={() => setDecisionKey("")}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            {review.predecessor_review_id ? (
              <div className="text-sm" data-testid="ip-docket-review-delta">
                <p className="font-medium">
                  Changes since the last signed review
                </p>
                <p className="text-[var(--color-mute)]">
                  {review.delta.added_docket_ids.length} added,{" "}
                  {review.delta.removed_docket_ids.length} removed,{" "}
                  {review.delta.changed_docket_ids.length} changed;{" "}
                  {review.delta.added_exception_keys.length} new exceptions and{" "}
                  {review.delta.removed_exception_keys.length} cleared.
                </p>
              </div>
            ) : null}

            {review.signatures.length ? (
              <ol
                className="flex flex-col gap-1 text-sm"
                data-testid="ip-docket-review-signatures"
              >
                {review.signatures.map((signature) => (
                  <li
                    key={`${signature.sequence}-${signature.signer_membership_id}`}
                  >
                    {signature.sequence}. {signature.signer_label_snapshot} (
                    {signature.signer_role})
                  </li>
                ))}
              </ol>
            ) : null}

            {review.signed_off_at ? (
              <p className="text-sm" data-testid="ip-docket-review-signed">
                Signed off by {review.signer_label_snapshot ?? "a reviewer"} on{" "}
                <span className="tabular-nums">
                  {STAMP.format(new Date(review.signed_off_at))}
                </span>
                .
              </p>
            ) : !canApprove ? (
              <p className="text-sm text-[var(--color-mute)]">
                Your role cannot sign off a control review.
              </p>
            ) : blockedBy ? (
              <p
                className="text-sm text-[var(--color-mute)]"
                data-testid="ip-docket-review-blocked"
              >
                {blockedBy}
              </p>
            ) : (
              <div className="flex min-w-0 flex-col gap-4">
                {review.signoff_status === "awaiting_second_signature" &&
                !reviewerSampleRequirementMet ? (
                  <div
                    className="grid gap-3"
                    data-testid="ip-docket-review-sample"
                  >
                    <p className="text-sm font-medium">
                      Independent reviewer sample
                    </p>
                    <div>
                      <Label htmlFor="control-review-sample-record">
                        Included record
                      </Label>
                      <select
                        id="control-review-sample-record"
                        className="mt-1 h-9 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-sm"
                        value={sampleDocketId}
                        onChange={(event) =>
                          setSampleDocketId(event.target.value)
                        }
                      >
                        {review.snapshot.included_records.map((record) => (
                          <option
                            key={record.docket_id}
                            value={record.docket_id}
                          >
                            {record.docket_id}
                          </option>
                        ))}
                      </select>
                    </div>
                    <Input
                      aria-label="Source evidence reference"
                      placeholder="Source evidence reference"
                      value={sampleSource}
                      onChange={(event) => setSampleSource(event.target.value)}
                    />
                    <Input
                      aria-label="Calculation evidence reference"
                      placeholder="Calculation evidence reference"
                      value={sampleCalculation}
                      onChange={(event) =>
                        setSampleCalculation(event.target.value)
                      }
                    />
                    <Input
                      aria-label="Coverage evidence reference"
                      placeholder="Coverage evidence reference"
                      value={sampleCoverage}
                      onChange={(event) =>
                        setSampleCoverage(event.target.value)
                      }
                    />
                    <Textarea
                      aria-label="Reviewer sample notes"
                      placeholder="Optional reviewer notes"
                      value={sampleNotes}
                      onChange={(event) => setSampleNotes(event.target.value)}
                    />
                    <div>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!sampleComplete || reviewWritePending}
                        onClick={() => recordSample.mutate()}
                      >
                        Record sample
                      </Button>
                    </div>
                  </div>
                ) : null}
                {reviewerSampleRequirementMet ? (
                  <>
                    <Label htmlFor="attestation">
                      What are you attesting to?
                    </Label>
                    <Textarea
                      id="attestation"
                      value={attestation}
                      onChange={(event) => setAttestation(event.target.value)}
                      placeholder="Recorded against your name on this review."
                    />
                    <div>
                      <Button
                        size="sm"
                        disabled={
                          attestation.trim().length < 5 || reviewWritePending
                        }
                        onClick={() => sign.mutate()}
                      >
                        {review.signoff_status === "draft"
                          ? "Add preparer signature"
                          : "Add reviewer signature"}
                      </Button>
                    </div>
                  </>
                ) : null}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {canWrite &&
              !review.signed_off_at &&
              review.signatures.length === 0 ? (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={reviewWritePending}
                  onClick={() => exportManifest.mutate()}
                  data-testid="ip-docket-review-export"
                >
                  Export manifest
                </Button>
              ) : null}
              {review.signed_off_at ? (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => downloadControlReviewManifest(review)}
                  data-testid="ip-docket-review-download-signed"
                >
                  Download signed manifest
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                disabled={reviewWritePending}
                onClick={() => generate.mutate()}
              >
                Regenerate
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
