"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Check, FileSignature, Hash, Send, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  confirmIpLegalDeadline,
  createIpOppositionIdentifier,
  fetchIpDeadlineWorkspace,
  fetchIpOppositionOpponentWorkflow,
  proposeIpOppositionOpponentDeadline,
  recordIpOppositionOpponentAction,
  type IpDocket,
  type IpLegalDeadline,
  type IpOppositionWorkspace,
} from "@/lib/api/endpoints";

const TODAY = new Date().toISOString().slice(0, 10);
const SELECT_CLASS = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <Label className="block min-w-0 space-y-1.5"><span className="block">{label}</span>{children}</Label>;
}

function refs(value: string): string[] {
  return value.split(",").map((row) => row.trim()).filter(Boolean);
}

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

export function IpOppositionOpponentWorkflow({
  docket,
  workspace,
  canReview,
  currentMembershipId,
}: {
  docket: IpDocket;
  workspace: IpOppositionWorkspace;
  canReview: boolean;
  currentMembershipId: string | null;
}) {
  const queryClient = useQueryClient();
  const proceeding = workspace.proceeding;
  const workflow = useQuery({
    queryKey: ["ip", "opposition-opponent-workflow", docket.id, proceeding.id],
    queryFn: () => fetchIpOppositionOpponentWorkflow({ docketId: docket.id, proceedingId: proceeding.id }),
  });
  const deadlineWorkspace = useQuery({
    queryKey: ["ip", "deadline-workspace", docket.id],
    queryFn: () => fetchIpDeadlineWorkspace(docket.id),
  });

  const [oppositionNumber, setOppositionNumber] = useState("");
  const [numberSource, setNumberSource] = useState("Trade Marks Registry allocation");
  const [baseDate, setBaseDate] = useState(workspace.profile?.limitation_date ?? TODAY);
  const [certainty, setCertainty] = useState<"certain" | "uncertain" | "conflicting" | "unknown">("certain");
  const [ruleVersionId, setRuleVersionId] = useState("");
  const [calendarVersionId, setCalendarVersionId] = useState("");
  const [primaryId, setPrimaryId] = useState(currentMembershipId ?? "");
  const [backupId, setBackupId] = useState("");
  const [filingOutcome, setFilingOutcome] = useState<"accepted" | "rejected">("accepted");
  const [filingReference, setFilingReference] = useState("");
  const [filedOn, setFiledOn] = useState(TODAY);
  const [signatory, setSignatory] = useState("");
  const [authority, setAuthority] = useState("");
  const [place, setPlace] = useState("New Delhi");
  const [paragraphs, setParagraphs] = useState("");
  const [knowledgeBasis, setKnowledgeBasis] = useState("");
  const [serviceMethod, setServiceMethod] = useState("");
  const [serviceDestination, setServiceDestination] = useState("");
  const [servedOn, setServedOn] = useState(TODAY);
  const [election, setElection] = useState<"file_evidence" | "rely_on_pleaded_facts">("rely_on_pleaded_facts");
  const [replyElection, setReplyElection] = useState<"file_reply_evidence" | "no_reply_evidence">("no_reply_evidence");
  const [rejectionReference, setRejectionReference] = useState("");
  const [correctiveDueOn, setCorrectiveDueOn] = useState(TODAY);
  const [escalationReference, setEscalationReference] = useState("");
  const [escalationDueOn, setEscalationDueOn] = useState(workspace.profile?.limitation_date ?? TODAY);
  const [sourceReference, setSourceReference] = useState("");
  const [documentRefs, setDocumentRefs] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [reason, setReason] = useState("");

  const next = workflow.data?.next_required_action;
  const workflowStage = next?.includes("reply_evidence")
    ? "reply_evidence_due" as const
    : next?.includes("opponent_evidence")
      ? "opponent_evidence_due" as const
      : "notice_filing_due" as const;
  const exactRules = useMemo(
    () => (deadlineWorkspace.data?.rules ?? []).filter((row) =>
      row.status === "active" && row.proceeding_kind === "opposition" &&
      row.role === "opponent" && row.stage === workflowStage),
    [deadlineWorkspace.data?.rules, workflowStage],
  );
  const activeCalendars = (deadlineWorkspace.data?.calendars ?? []).filter((row) => row.status === "active");
  const selectedRule = ruleVersionId || exactRules[0]?.id || "";
  const selectedCalendar = calendarVersionId || activeCalendars[0]?.id || "";
  const triggerEvent = workflowStage === "notice_filing_due"
    ? workspace.profile_event
    : [...workspace.stage_events].reverse().find((row) =>
      workflowStage === "opponent_evidence_due"
        ? row.after_phase === "counterstatement_filed" || row.resulting_stage === "counterstatement_filed"
        : row.after_phase === "applicant_evidence_filed" || row.resulting_stage === "applicant_evidence_filed");
  const triggerDate = triggerEvent?.effective_at?.slice(0, 10)
    ?? (workflowStage === "notice_filing_due" ? workspace.profile?.limitation_date : null)
    ?? TODAY;

  useEffect(() => {
    setBaseDate(triggerDate);
  }, [triggerDate, triggerEvent?.id, workflowStage]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-opponent-workflow", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "deadline-workspace", docket.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-workspace", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "tasks", docket.id] }),
    ]);
  };
  const mutationOptions = {
    onSuccess: async () => { toast.success("Opponent opposition workflow updated."); await refresh(); },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, "The opponent workflow change was rejected.")),
  };
  const addNumber = useMutation({
    mutationFn: () => createIpOppositionIdentifier({
      docketId: docket.id,
      proceedingId: proceeding.id,
      rawValue: oppositionNumber,
      office: proceeding.office,
      jurisdiction: proceeding.jurisdiction,
      source: numberSource,
      effectiveFrom: TODAY,
    }),
    ...mutationOptions,
  });
  const propose = useMutation({
    mutationFn: (input: Parameters<typeof proposeIpOppositionOpponentDeadline>[0]) =>
      proposeIpOppositionOpponentDeadline(input),
    ...mutationOptions,
  });
  const confirm = useMutation({
    mutationFn: (deadline: IpLegalDeadline) => confirmIpLegalDeadline({
      deadlineId: deadline.id,
      expectedVersion: deadline.version,
      responsibilities: [
        { membership_id: primaryId.trim(), role: "primary", accepted: true, replacement_source: "direct_assignment", escalation_policy: { escalate_after_hours: 24 } },
        { membership_id: backupId.trim(), role: "backup", accepted: true, replacement_source: "direct_assignment", escalation_policy: { escalate_after_hours: 24 } },
      ],
      internalTargetOn: null,
      reminderOffsetsDays: [7, 1, 0],
    }),
    ...mutationOptions,
  });

  const actionKind = next === "record_client_instruction_escalation"
    ? "client_instruction_escalated" as const
    : next === "file_notice"
      ? filingOutcome === "accepted" ? "notice_filed" as const : "notice_filing_rejected" as const
      : next === "correct_rejected_notice"
        ? "notice_refiled" as const
        : next === "record_notice_service"
          ? "notice_served" as const
          : next === "record_opponent_evidence_decision"
            ? "opponent_evidence_decision" as const
            : "reply_evidence_decision" as const;
  const recordAction = useMutation({
    mutationFn: (forcedKind?: "watch_hit_closed") => {
      if (!currentMembershipId) throw new Error("Opponent action is unavailable.");
      const kind = forcedKind ?? actionKind;
      return recordIpOppositionOpponentAction({
        docketId: docket.id,
        proceedingId: proceeding.id,
        lifecycleVersion: docket.lifecycle_version,
        proceedingVersion: proceeding.version,
        responsibleMembershipId: currentMembershipId,
        actionKind: kind,
        sourceReference,
        effectiveAt: new Date().toISOString(),
        reason,
        filingReference: ["notice_filed", "notice_refiled"].includes(kind) ? filingReference : null,
        filedOn: ["notice_filed", "notice_refiled"].includes(kind) ? filedOn : null,
        verification: ["notice_filed", "notice_refiled"].includes(kind) ? {
          signatory,
          authority,
          place,
          verified_on: filedOn,
          verified_paragraph_ranges: refs(paragraphs),
          knowledge_basis: knowledgeBasis,
          signed_document_ref: refs(documentRefs)[0],
        } : null,
        service: kind === "notice_served" ? {
          method: serviceMethod,
          destination: serviceDestination,
          served_on: servedOn,
          acknowledgement: null,
          starts_response_period: true,
          evidence_refs: refs(evidenceRefs),
        } : null,
        evidenceElection: kind === "opponent_evidence_decision"
          ? election
          : kind === "reply_evidence_decision" ? replyElection : null,
        rejectionReference: kind === "notice_filing_rejected" ? rejectionReference : null,
        correctiveDueOn: kind === "notice_filing_rejected" ? correctiveDueOn : null,
        escalationReference: kind === "client_instruction_escalated" ? escalationReference : null,
        escalationDueOn: kind === "client_instruction_escalated" ? escalationDueOn : null,
        evidenceRefs: refs(evidenceRefs),
        documentRefs: refs(documentRefs),
      });
    },
    ...mutationOptions,
  });

  if (workflow.isLoading || deadlineWorkspace.isLoading) return <Skeleton className="h-32 w-full" />;
  if (workflow.isError) return <QueryErrorState error={workflow.error} onRetry={() => workflow.refetch()} />;
  if (deadlineWorkspace.isError) return <QueryErrorState error={deadlineWorkspace.error} onRetry={() => deadlineWorkspace.refetch()} />;
  if (!workflow.data) return null;

  const filingReady = filingReference.trim() && filedOn && signatory.trim() && authority.trim() && place.trim() && refs(paragraphs).length && knowledgeBasis.trim() && refs(documentRefs).length && refs(evidenceRefs).length;
  const actionReady = Boolean(sourceReference.trim() && reason.trim().length >= 5 && (
    actionKind === "client_instruction_escalated"
      ? escalationReference.trim() && escalationDueOn && refs(evidenceRefs).length
      : actionKind === "notice_filing_rejected"
        ? rejectionReference.trim() && correctiveDueOn && refs(evidenceRefs).length
        : ["notice_filed", "notice_refiled"].includes(actionKind)
          ? filingReady
          : actionKind === "notice_served"
            ? serviceMethod.trim() && serviceDestination.trim() && servedOn && refs(evidenceRefs).length
            : actionKind === "opponent_evidence_decision"
              ? refs(evidenceRefs).length && (election === "rely_on_pleaded_facts" || refs(documentRefs).length)
              : actionKind === "reply_evidence_decision"
                ? refs(evidenceRefs).length && (replyElection === "no_reply_evidence" || refs(documentRefs).length)
                : false
  ));

  const canCloseWatch = proceeding.origin_kind === "watch_hit" && proceeding.stage === "draft" && workflow.data.opponent_actions.length === 0;
  const actionable = [
    "record_client_instruction_escalation", "file_notice", "correct_rejected_notice",
    "record_notice_service", "record_opponent_evidence_decision", "record_reply_evidence_decision",
  ].includes(next ?? "");

  return (
    <section data-testid="ip-opposition-opponent-workflow" className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h4 className="font-semibold">Opponent docketing</h4><p className="text-sm text-[var(--color-mute)]">Next: {readable(workflow.data.next_required_action)}</p></div>
        <div className="flex flex-wrap gap-2"><Badge tone={workflow.data.client_instruction_status === "confirmed" ? "success" : "warning"}>{readable(workflow.data.client_instruction_status)} instruction</Badge><Badge tone={workflow.data.opposition_number_status === "confirmed" ? "success" : "warning"}>{readable(workflow.data.opposition_number_status)}</Badge></div>
      </div>

      {canCloseWatch ? <div className="grid gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-2 xl:grid-cols-4"><div className="md:col-span-2 xl:col-span-4"><strong>Watch-hit disposition</strong><p className="text-sm text-[var(--color-mute)]">Keep the draft intake for audit without creating a filed opposition.</p></div><Field label="Watch source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field><Field label="Watch evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field><Field label="Watch disposition reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field><div className="flex items-end"><Button type="button" variant="secondary" disabled={!canReview || !currentMembershipId || !sourceReference.trim() || reason.trim().length < 5 || !refs(evidenceRefs).length || recordAction.isPending} onClick={() => recordAction.mutate("watch_hit_closed")}><XCircle className="h-4 w-4" /> Close without proceeding</Button></div></div> : null}

      {next === "record_opposition_number" ? <form className="grid gap-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); addNumber.mutate(); }}><Field label="Opposition number"><Input value={oppositionNumber} onChange={(event) => setOppositionNumber(event.target.value)} /></Field><Field label="Registry source"><Input value={numberSource} onChange={(event) => setNumberSource(event.target.value)} /></Field><div className="flex items-end"><Button type="submit" disabled={!canReview || !oppositionNumber.trim() || !numberSource.trim() || addNumber.isPending}><Hash className="h-4 w-4" /> Record number</Button></div></form> : null}

      {next?.startsWith("propose_") ? <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-5" onSubmit={(event) => { event.preventDefault(); propose.mutate({ docketId: docket.id, proceedingId: proceeding.id, workflowStage, triggerEventId: triggerEvent?.id ?? "", ruleVersionId: selectedRule, calendarVersionId: selectedCalendar, baseDate: baseDate || null, certainty }); }}><Field label="Governed rule"><select className={SELECT_CLASS} value={selectedRule} onChange={(event) => setRuleVersionId(event.target.value)}>{exactRules.map((row) => <option key={row.id} value={row.id}>{row.key} v{row.version}</option>)}</select></Field><Field label="Working calendar"><select className={SELECT_CLASS} value={selectedCalendar} onChange={(event) => setCalendarVersionId(event.target.value)}>{activeCalendars.map((row) => <option key={row.id} value={row.id}>{row.name} v{row.version}</option>)}</select></Field><Field label="Trigger date"><Input type="date" value={baseDate} onChange={(event) => setBaseDate(event.target.value)} /></Field><Field label="Date certainty"><select className={SELECT_CLASS} value={certainty} onChange={(event) => setCertainty(event.target.value as typeof certainty)}><option value="certain">Certain</option><option value="uncertain">Uncertain</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option></select></Field><div className="flex items-end"><Button type="submit" disabled={!canReview || !triggerEvent || !selectedRule || !selectedCalendar || propose.isPending}><CalendarClock className="h-4 w-4" /> Propose deadline</Button></div>{!triggerEvent ? <p className="text-sm text-[var(--color-danger)] md:col-span-2 xl:col-span-5">The confirmed trigger event is not yet recorded.</p> : null}{!exactRules.length ? <p className="text-sm text-[var(--color-danger)] md:col-span-2 xl:col-span-5">No exact active opponent rule is available for {workflowStage}.</p> : null}</form> : null}

      {workflow.data.deadlines.length ? <div className="space-y-2">{workflow.data.deadlines.map(({ workflow_stage, deadline }) => <div key={deadline.id} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[1fr_180px_180px_auto]"><div><strong>{readable(workflow_stage)}</strong><p className="text-sm text-[var(--color-mute)]">{deadline.result_on ?? "Date unresolved"} · {deadline.state} · {deadline.rule_citation}</p></div>{deadline.state === "provisional" || deadline.state === "candidate" ? <><Input aria-label="Opponent primary membership ID" value={primaryId} onChange={(event) => setPrimaryId(event.target.value)} placeholder="Primary membership ID" /><Input aria-label="Opponent backup membership ID" value={backupId} onChange={(event) => setBackupId(event.target.value)} placeholder="Backup membership ID" /><Button type="button" onClick={() => confirm.mutate(deadline)} disabled={!canReview || !primaryId.trim() || !backupId.trim() || primaryId.trim() === backupId.trim() || confirm.isPending}><Check className="h-4 w-4" /> Confirm</Button></> : <Badge tone="success">Confirmed</Badge>}</div>)}</div> : null}

      {actionable ? <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); recordAction.mutate(undefined); }}>
        {next === "file_notice" ? <Field label="Filing outcome"><select className={SELECT_CLASS} value={filingOutcome} onChange={(event) => setFilingOutcome(event.target.value as typeof filingOutcome)}><option value="accepted">Filed and accepted</option><option value="rejected">Rejected by registry</option></select></Field> : null}
        {["file_notice", "correct_rejected_notice"].includes(next ?? "") && actionKind !== "notice_filing_rejected" ? <><Field label="TM-O notice filing reference"><Input value={filingReference} onChange={(event) => setFilingReference(event.target.value)} /></Field><Field label="Filed and verified on"><Input type="date" value={filedOn} onChange={(event) => setFiledOn(event.target.value)} /></Field><Field label="Signatory"><Input value={signatory} onChange={(event) => setSignatory(event.target.value)} /></Field><Field label="Authority"><Input value={authority} onChange={(event) => setAuthority(event.target.value)} /></Field><Field label="Place"><Input value={place} onChange={(event) => setPlace(event.target.value)} /></Field><Field label="Verified paragraph ranges"><Input value={paragraphs} onChange={(event) => setParagraphs(event.target.value)} placeholder="1-14, verification" /></Field><Field label="Knowledge basis"><Textarea value={knowledgeBasis} onChange={(event) => setKnowledgeBasis(event.target.value)} /></Field></> : null}
        {actionKind === "notice_filing_rejected" ? <><Field label="Registry rejection reference"><Input value={rejectionReference} onChange={(event) => setRejectionReference(event.target.value)} /></Field><Field label="Corrective task due"><Input type="date" value={correctiveDueOn} onChange={(event) => setCorrectiveDueOn(event.target.value)} /></Field></> : null}
        {next === "record_client_instruction_escalation" ? <><Field label="Instruction escalation reference"><Input value={escalationReference} onChange={(event) => setEscalationReference(event.target.value)} /></Field><Field label="Escalation due"><Input type="date" value={escalationDueOn} onChange={(event) => setEscalationDueOn(event.target.value)} /></Field></> : null}
        {next === "record_notice_service" ? <><Field label="Notice service method"><Input value={serviceMethod} onChange={(event) => setServiceMethod(event.target.value)} /></Field><Field label="Notice service destination"><Input value={serviceDestination} onChange={(event) => setServiceDestination(event.target.value)} /></Field><Field label="Notice served on"><Input type="date" value={servedOn} onChange={(event) => setServedOn(event.target.value)} /></Field></> : null}
        {next === "record_opponent_evidence_decision" ? <Field label="Rule 45 election"><select className={SELECT_CLASS} value={election} onChange={(event) => setElection(event.target.value as typeof election)}><option value="rely_on_pleaded_facts">Rely on pleaded facts</option><option value="file_evidence">File opponent evidence</option></select></Field> : null}
        {next === "record_reply_evidence_decision" ? <Field label="Rule 47 election"><select className={SELECT_CLASS} value={replyElection} onChange={(event) => setReplyElection(event.target.value as typeof replyElection)}><option value="no_reply_evidence">No reply evidence</option><option value="file_reply_evidence">File reply evidence</option></select></Field> : null}
        <Field label="Opponent source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field><Field label="Opponent document references"><Input value={documentRefs} onChange={(event) => setDocumentRefs(event.target.value)} placeholder="Comma separated" /></Field><Field label="Opponent evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field><Field label="Opponent lawyer reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field><div className="flex items-end"><Button type="submit" disabled={!canReview || !currentMembershipId || !actionReady || recordAction.isPending}>{actionKind === "notice_filing_rejected" ? <AlertTriangle className="h-4 w-4" /> : actionKind === "notice_served" ? <Send className="h-4 w-4" /> : <FileSignature className="h-4 w-4" />} Record opponent work product</Button></div>
      </form> : null}

      {workflow.data.corrective_task_id ? <p className="text-sm text-[var(--color-warning)]">Corrective shared task: {workflow.data.corrective_task_id}</p> : null}
    </section>
  );
}
