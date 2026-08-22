"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  Clock3,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
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
  acknowledgeIpRenewalInstruction,
  createIpRenewalInstruction,
  fetchIpRenewalPortfolio,
  scheduleIpRenewalReminders,
  transitionIpRenewalTerm,
  type IpRenewalInstruction,
  type IpRenewalState,
  type IpRenewalWorkflow,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});
const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const STATE_LABEL: Record<IpRenewalState, string> = {
  due: "Due",
  instructed: "Instructed",
  filing_in_progress: "Filing in progress",
  filed: "Filed",
  accepted: "Registry accepted",
  grace: "Grace period",
  overdue: "Overdue",
  completed: "Completed",
  cancelled: "Cancelled",
};

const ACTION_LABEL: Record<IpRenewalWorkflow["action_required"], string> = {
  request_instruction: "Request client instruction",
  review_instruction: "Review client instruction",
  record_filing_initiation: "Record filing initiation",
  record_filing: "Record filing evidence",
  await_registry_acceptance: "Await registry acceptance",
  record_registry_acceptance: "Record registry acceptance",
  record_certificate_and_next_term: "Record certificate and next term",
  resolve_grace_period: "Resolve grace-period status",
  resolve_overdue_term: "Resolve overdue term",
  none: "No action",
};

const TRANSITIONS: Record<IpRenewalState, IpRenewalState[]> = {
  due: ["filing_in_progress", "filed", "grace", "overdue", "cancelled"],
  instructed: ["filing_in_progress", "filed", "grace", "overdue", "cancelled"],
  filing_in_progress: ["filed", "grace", "overdue", "cancelled"],
  filed: ["accepted", "grace", "overdue", "cancelled"],
  accepted: ["completed", "cancelled"],
  grace: ["filing_in_progress", "filed", "overdue", "cancelled"],
  overdue: ["filing_in_progress", "filed", "grace", "cancelled"],
  completed: [],
  cancelled: [],
};

function displayDate(value: string | null) {
  if (!value) return "Not recorded";
  return DATE.format(new Date(`${value}T00:00:00`));
}

function stateTone(state: IpRenewalState) {
  if (state === "completed" || state === "accepted") return "success" as const;
  if (state === "grace" || state === "overdue") return "warning" as const;
  if (state === "instructed" || state === "filed") return "brand" as const;
  return "neutral" as const;
}

export default function IpRenewalsPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const [selectedTermId, setSelectedTermId] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<"all" | IpRenewalState>("all");
  const portfolio = useQuery({
    queryKey: ["ip", "renewals", "portfolio"],
    queryFn: fetchIpRenewalPortfolio,
    enabled: canRead,
  });
  const filtered = useMemo(
    () =>
      (portfolio.data?.items ?? []).filter(
        (row) => stateFilter === "all" || row.reporting_state === stateFilter,
      ),
    [portfolio.data?.items, stateFilter],
  );

  useEffect(() => {
    if (!selectedTermId || !filtered.some((row) => row.term.id === selectedTermId)) {
      setSelectedTermId(filtered[0]?.term.id ?? null);
    }
  }, [filtered, selectedTermId]);

  const selected = filtered.find((row) => row.term.id === selectedTermId) ?? null;

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Trademark renewals" description="Renewal term control." />
        <EmptyState
          title="IP access required"
          description="Ask an owner or admin for the IP read capability."
        />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="Trademark renewals"
        description="Instruction, filing, registry acceptance, certificate and next-term control."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => portfolio.refetch()}
            disabled={portfolio.isFetching}
          >
            <RefreshCw className={portfolio.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      {portfolio.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Loading renewals">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton className="h-24" key={index} />
          ))}
        </div>
      ) : portfolio.isError ? (
        <QueryErrorState
          error={portfolio.error}
          title="Could not load trademark renewals"
          onRetry={() => portfolio.refetch()}
        />
      ) : portfolio.data ? (
        <>
          <RenewalMetrics data={portfolio.data} />
          <Card className="min-w-0" data-testid="renewal-portfolio">
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle as="h2">Renewal portfolio</CardTitle>
              <div className="min-w-40">
                <Label className="sr-only" htmlFor="renewal-state-filter">
                  Renewal state
                </Label>
                <select
                  id="renewal-state-filter"
                  className="h-9 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={stateFilter}
                  onChange={(event) =>
                    setStateFilter(event.target.value as "all" | IpRenewalState)
                  }
                >
                  <option value="all">All renewal states</option>
                  {Object.entries(STATE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </CardHeader>
            <CardContent className="min-w-0 overflow-x-auto p-0">
              {filtered.length === 0 ? (
                <div className="p-6">
                  <EmptyState
                    title="No renewal terms in this view"
                    description="Change the state filter or create a verified renewal term from the IP docket."
                  />
                </div>
              ) : (
                <table className="w-full min-w-[780px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                      <th className="px-4 py-3 font-semibold">Trademark</th>
                      <th className="px-4 py-3 font-semibold">Renewal due</th>
                      <th className="px-4 py-3 font-semibold">State</th>
                      <th className="px-4 py-3 font-semibold">Action</th>
                      <th className="px-4 py-3 font-semibold">Notifications</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <tr
                        className={
                          row.term.id === selectedTermId
                            ? "border-b border-[var(--color-line)] bg-[var(--color-brand-50)]"
                            : "border-b border-[var(--color-line)]"
                        }
                        key={row.term.id}
                      >
                        <td className="px-4 py-3">
                          <button
                            className="text-left font-semibold text-[var(--color-brand-700)] hover:underline"
                            onClick={() => setSelectedTermId(row.term.id)}
                          >
                            {row.docket_title}
                          </button>
                          <div className="mt-1 text-xs text-[var(--color-mute)]">
                            {row.primary_identifier ?? "Identifier not recorded"} · Term {row.term.term_sequence}
                          </div>
                        </td>
                        <td className="px-4 py-3 tabular-nums">
                          {displayDate(row.renewal_deadline.result_on)}
                          {row.grace_deadline ? (
                            <div className="mt-1 text-xs text-[var(--color-mute)]">
                              Grace ends {displayDate(row.grace_deadline.result_on)}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-4 py-3">
                          <Badge tone={stateTone(row.reporting_state)}>
                            {STATE_LABEL[row.reporting_state]}
                          </Badge>
                          {row.state_reconciliation_required ? (
                            <div className="mt-2 text-xs font-medium text-amber-800">
                              Recorded state: {STATE_LABEL[row.term.state]}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-4 py-3">{ACTION_LABEL[row.action_required]}</td>
                        <td className="px-4 py-3 tabular-nums">
                          {row.reminders.sent_or_delivered} delivered · {row.reminders.queued} queued
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>

          {selected ? <RenewalWorkspace row={selected} canWrite={canWrite} /> : null}
        </>
      ) : null}
    </div>
  );
}

function RenewalMetrics({ data }: { data: Awaited<ReturnType<typeof fetchIpRenewalPortfolio>> }) {
  const metrics = [
    ["Action required", data.counts.action_required, AlertTriangle],
    ["Due", data.counts.due, Clock3],
    ["Instructed", data.counts.instructed, CheckCircle2],
    ["Filed", data.counts.filed + data.counts.filing_in_progress, FileCheck2],
    ["Grace / overdue", data.counts.grace + data.counts.overdue, BellRing],
  ] as const;
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Renewal totals">
      {metrics.map(([label, value, Icon]) => (
        <div className="border-l-2 border-[var(--color-brand-500)] bg-white px-4 py-3" key={label}>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-[var(--color-mute)]">
            <Icon className="h-4 w-4" /> {label}
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
        </div>
      ))}
      <p className="text-xs text-[var(--color-mute)] sm:col-span-2 xl:col-span-5">
        Generated {STAMP.format(new Date(data.generated_at))}
      </p>
    </section>
  );
}

function RenewalWorkspace({ row, canWrite }: { row: IpRenewalWorkflow; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ip", "renewals", "portfolio"] });
  const currentInstruction = [...row.term.instructions]
    .reverse()
    .find((item) => item.status !== "superseded") ?? null;
  const reminders = useMutation({
    mutationFn: () => scheduleIpRenewalReminders({ docketId: row.docket_id, term: row.term }),
    onSuccess: async (result) => {
      toast.success(
        result.created_count
          ? `${result.created_count} renewal notification${result.created_count === 1 ? "" : "s"} scheduled.`
          : "Renewal notifications were already scheduled.",
      );
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not schedule renewal notifications.")),
  });

  return (
    <section className="border-t border-[var(--color-line)] pt-6" data-testid="renewal-workspace">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-[var(--color-mute)]">Selected renewal</p>
          <h2 className="mt-1 text-xl font-semibold">{row.docket_title}</h2>
          <p className="mt-1 text-sm text-[var(--color-mute)]">
            {row.primary_identifier ?? "Identifier not recorded"} · Term {row.term.term_sequence}
          </p>
        </div>
        <Button variant="outline" href={`/app/ip?docket=${encodeURIComponent(row.docket_id)}`}>
          Open IP docket
        </Button>
      </div>

      <div className="mt-5 grid min-w-0 gap-5 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader><CardTitle as="h3">Term and legal source</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Datum label="Recorded state" value={STATE_LABEL[row.term.state]} />
            <Datum label="Reporting state" value={STATE_LABEL[row.reporting_state]} />
            <Datum label="Renewal due" value={displayDate(row.renewal_deadline.result_on)} />
            <Datum label="Grace ends" value={displayDate(row.grace_deadline?.result_on ?? null)} />
            <Datum label="Rule citation" value={row.renewal_deadline.rule_citation} wide />
            <Datum label="Source version" value={row.renewal_deadline.source_version} wide />
            <Datum label="Calculation" value={row.renewal_deadline.explanation} wide />
            <Datum
              label="Fee / quote evidence"
              value={row.fee ? `${row.fee.description} · ${row.fee.evidence_reference}` : "Not linked"}
              wide
            />
            <Datum
              label="Payment / billing link"
              value={
                row.fee?.billing_link_type && row.fee.billing_link_id
                  ? `${row.fee.billing_link_type}: ${row.fee.billing_link_id}`
                  : row.fee
                    ? `Reconciliation: ${row.fee.reconciliation_status}`
                    : "Not linked"
              }
              wide
            />
            {row.state_reconciliation_required ? (
              <div className="sm:col-span-2 flex gap-2 border-l-2 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                The calendar is in {row.calendar_phase}; record the corresponding workflow transition.
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader><CardTitle as="h3">Instruction notifications</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <dl className="grid gap-3 sm:grid-cols-2">
              <Datum label="Delivered" value={String(row.reminders.sent_or_delivered)} />
              <Datum label="Queued" value={String(row.reminders.queued)} />
              <Datum
                label="Next scheduled"
                value={row.reminders.next_scheduled_for ? STAMP.format(new Date(row.reminders.next_scheduled_for)) : "None"}
              />
              <Datum label="Cancelled" value={String(row.reminders.cancelled)} />
            </dl>
            {canWrite && !currentInstruction && !["filing_in_progress", "filed", "accepted", "completed", "cancelled"].includes(row.term.state) ? (
              <div>
                <Button size="sm" onClick={() => reminders.mutate()} disabled={reminders.isPending}>
                  {reminders.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <BellRing className="h-4 w-4" />}
                  Schedule instruction notifications
                </Button>
              </div>
            ) : null}
            {row.reminders.blocked_or_failed ? (
              <p className="text-sm font-medium text-amber-800">
                {row.reminders.blocked_or_failed} notification delivery exception{row.reminders.blocked_or_failed === 1 ? "" : "s"}
              </p>
            ) : null}
          </CardContent>
        </Card>

        <InstructionPanel row={row} current={currentInstruction} canWrite={canWrite} onChanged={refresh} />
        <TransitionPanel row={row} canWrite={canWrite} onChanged={refresh} />
      </div>
    </section>
  );
}

function InstructionPanel({
  row,
  current,
  canWrite,
  onChanged,
}: {
  row: IpRenewalWorkflow;
  current: IpRenewalInstruction | null;
  canWrite: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [decision, setDecision] = useState<IpRenewalInstruction["decision"]>("renew");
  const [authorityName, setAuthorityName] = useState("");
  const [authorityReference, setAuthorityReference] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [scope, setScope] = useState("All registered classes");
  const [ackReason, setAckReason] = useState("");
  const [revising, setRevising] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      createIpRenewalInstruction({
        docketId: row.docket_id,
        termId: row.term.id,
        decision,
        scope: { description: scope.trim() },
        sourceChannel: "client_communication",
        authorityName: authorityName.trim(),
        authorityReference: authorityReference.trim() || null,
        evidenceRefs: [evidenceReference.trim()],
        receivedAt: new Date().toISOString(),
        currentInstruction: current,
      }),
    onSuccess: async () => {
      toast.success("Client instruction recorded; pending reminders were cancelled.");
      setRevising(false);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record client instruction.")),
  });
  const acknowledge = useMutation({
    mutationFn: (status: "accepted" | "rejected" | "clarification_required") =>
      acknowledgeIpRenewalInstruction({
        docketId: row.docket_id,
        termId: row.term.id,
        instruction: current!,
        status,
        reason: ackReason.trim(),
      }),
    onSuccess: async (term) => {
      toast.success(term.state === "instructed" ? "Renew instruction accepted." : "Instruction decision recorded.");
      setAckReason("");
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not decide the instruction.")),
  });
  const createReady =
    authorityName.trim().length >= 2 &&
    evidenceReference.trim().length > 0 &&
    scope.trim().length > 0;

  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Client instruction</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {current ? (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              <Datum label="Decision" value={current.decision.replaceAll("_", " ")} />
              <Datum label="Review status" value={current.status.replaceAll("_", " ")} />
              <Datum label="Authority" value={current.authority_name} />
              <Datum label="Reference" value={current.authority_reference ?? "Not recorded"} />
              <Datum label="Evidence" value={current.evidence_refs_json.join(", ")} wide />
            </dl>
            {canWrite && current.status === "pending" ? (
              <div className="flex flex-col gap-3 border-t border-[var(--color-line)] pt-4">
                <Label htmlFor="renewal-ack-reason">Review reason</Label>
                <Textarea id="renewal-ack-reason" value={ackReason} onChange={(event) => setAckReason(event.target.value)} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={ackReason.trim().length < 5 || acknowledge.isPending} onClick={() => acknowledge.mutate("accepted")}>Accept</Button>
                  <Button size="sm" variant="outline" disabled={ackReason.trim().length < 5 || acknowledge.isPending} onClick={() => acknowledge.mutate("clarification_required")}>Need clarification</Button>
                  <Button size="sm" variant="ghost" disabled={ackReason.trim().length < 5 || acknowledge.isPending} onClick={() => acknowledge.mutate("rejected")}>Reject</Button>
                </div>
              </div>
            ) : null}
            {canWrite && current.status !== "pending" && !revising ? (
              <div>
                <Button size="sm" variant="outline" onClick={() => setRevising(true)}>
                  Record revised instruction
                </Button>
              </div>
            ) : null}
            {canWrite && revising ? (
              <form
                className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-4 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  create.mutate();
                }}
              >
                <Field label="Revised decision">
                  <select className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={decision} onChange={(event) => setDecision(event.target.value as IpRenewalInstruction["decision"])}>
                    <option value="renew">Renew</option>
                    <option value="do_not_renew">Do not renew</option>
                    <option value="defer">Defer</option>
                    <option value="clarification_required">Clarification required</option>
                  </select>
                </Field>
                <Field label="Revised authority name"><Input value={authorityName} onChange={(event) => setAuthorityName(event.target.value)} /></Field>
                <Field label="Revised authority reference"><Input value={authorityReference} onChange={(event) => setAuthorityReference(event.target.value)} /></Field>
                <Field label="Revised evidence reference"><Input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} /></Field>
                <div className="sm:col-span-2"><Field label="Revised instruction scope"><Textarea value={scope} onChange={(event) => setScope(event.target.value)} /></Field></div>
                <div className="flex flex-wrap gap-2 sm:col-span-2">
                  <Button size="sm" type="submit" disabled={!createReady || create.isPending}>Record revision</Button>
                  <Button size="sm" type="button" variant="ghost" onClick={() => setRevising(false)}>Cancel</Button>
                </div>
              </form>
            ) : null}
          </>
        ) : canWrite ? (
          <form
            className="grid min-w-0 gap-3 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Decision">
              <select className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={decision} onChange={(event) => setDecision(event.target.value as IpRenewalInstruction["decision"])}>
                <option value="renew">Renew</option>
                <option value="do_not_renew">Do not renew</option>
                <option value="defer">Defer</option>
                <option value="clarification_required">Clarification required</option>
              </select>
            </Field>
            <Field label="Authority name"><Input value={authorityName} onChange={(event) => setAuthorityName(event.target.value)} /></Field>
            <Field label="Authority reference"><Input value={authorityReference} onChange={(event) => setAuthorityReference(event.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} /></Field>
            <div className="sm:col-span-2"><Field label="Instruction scope"><Textarea value={scope} onChange={(event) => setScope(event.target.value)} /></Field></div>
            <div className="sm:col-span-2"><Button size="sm" type="submit" disabled={!createReady || create.isPending}>{create.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}Record instruction</Button></div>
          </form>
        ) : (
          <p className="text-sm text-[var(--color-mute)]">No client instruction recorded.</p>
        )}
      </CardContent>
    </Card>
  );
}

function TransitionPanel({ row, canWrite, onChanged }: { row: IpRenewalWorkflow; canWrite: boolean; onChanged: () => Promise<unknown> }) {
  const options = TRANSITIONS[row.term.state];
  const [target, setTarget] = useState<IpRenewalState>(options[0] ?? row.term.state);
  const [reason, setReason] = useState("");
  const [filingReference, setFilingReference] = useState(row.term.filing_initiated_reference ?? "");
  const [filingEventId, setFilingEventId] = useState(row.term.filing_event_id ?? "");
  const [acceptanceEventId, setAcceptanceEventId] = useState(row.term.acceptance_event_id ?? "");
  const [certificateDocumentId, setCertificateDocumentId] = useState(row.term.certificate_document_id ?? "");
  const [nextDeadlineId, setNextDeadlineId] = useState(row.term.next_term_deadline_id ?? "");
  useEffect(() => {
    setTarget(TRANSITIONS[row.term.state][0] ?? row.term.state);
  }, [row.term.id, row.term.state]);
  const transition = useMutation({
    mutationFn: () => transitionIpRenewalTerm({
      docketId: row.docket_id,
      term: row.term,
      targetState: target,
      reason: reason.trim(),
      filingInitiatedReference: filingReference.trim() || null,
      filingEventId: filingEventId.trim() || null,
      acceptanceEventId: acceptanceEventId.trim() || null,
      certificateDocumentId: certificateDocumentId.trim() || null,
      nextTermDeadlineId: nextDeadlineId.trim() || null,
    }),
    onSuccess: async (term) => {
      toast.success(`Renewal moved to ${STATE_LABEL[term.state].toLowerCase()}.`);
      setReason("");
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not transition the renewal.")),
  });
  const requiresFilingReference = target === "filing_in_progress";
  const requiresFilingEvent = ["filed", "accepted", "completed"].includes(target);
  const requiresAcceptance = ["accepted", "completed"].includes(target);
  const requiresCompletion = target === "completed";
  const ready =
    reason.trim().length >= 5 &&
    (!requiresFilingReference || filingReference.trim().length >= 3) &&
    (!requiresFilingEvent || filingEventId.trim().length > 0) &&
    (!requiresAcceptance || acceptanceEventId.trim().length > 0) &&
    (!requiresCompletion || (certificateDocumentId.trim().length > 0 && nextDeadlineId.trim().length > 0));

  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Renewal progression</CardTitle></CardHeader>
      <CardContent>
        {!canWrite ? (
          <p className="text-sm text-[var(--color-mute)]">Current state: {STATE_LABEL[row.term.state]}</p>
        ) : options.length === 0 ? (
          <div className="flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4 text-green-700" />This renewal term is closed.</div>
        ) : (
          <form className="grid min-w-0 gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); transition.mutate(); }}>
            <Field label="Next state">
              <select className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={target} onChange={(event) => setTarget(event.target.value as IpRenewalState)}>
                {options.map((state) => <option key={state} value={state}>{STATE_LABEL[state]}</option>)}
              </select>
            </Field>
            <Field label="Reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            {requiresFilingReference ? <Field label="Filing initiation reference"><Input value={filingReference} onChange={(event) => setFilingReference(event.target.value)} /></Field> : null}
            {requiresFilingEvent ? <Field label="Confirmed filing event ID"><Input value={filingEventId} onChange={(event) => setFilingEventId(event.target.value)} /></Field> : null}
            {requiresAcceptance ? <Field label="Registry acceptance event ID"><Input value={acceptanceEventId} onChange={(event) => setAcceptanceEventId(event.target.value)} /></Field> : null}
            {requiresCompletion ? <Field label="Accepted certificate document ID"><Input value={certificateDocumentId} onChange={(event) => setCertificateDocumentId(event.target.value)} /></Field> : null}
            {requiresCompletion ? <Field label="Confirmed next-term deadline ID"><Input value={nextDeadlineId} onChange={(event) => setNextDeadlineId(event.target.value)} /></Field> : null}
            <div className="sm:col-span-2"><Button size="sm" type="submit" disabled={!ready || transition.isPending}>{transition.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}Record transition</Button></div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function Datum({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "min-w-0 sm:col-span-2" : "min-w-0"}>
      <dt className="text-xs font-semibold uppercase text-[var(--color-mute)]">{label}</dt>
      <dd className="mt-1 break-words text-sm">{value}</dd>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm font-medium">
      <span>{label}</span>
      {children}
    </label>
  );
}
