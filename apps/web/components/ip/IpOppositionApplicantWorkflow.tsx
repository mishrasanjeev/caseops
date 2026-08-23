"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, FileSignature, Hash, Send } from "lucide-react";
import { useMemo, useState } from "react";
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
  fetchIpOppositionApplicantWorkflow,
  proposeIpOppositionApplicantDeadline,
  recordIpOppositionApplicantAction,
  type IpDocket,
  type IpLegalDeadline,
  type IpOppositionWorkspace,
} from "@/lib/api/endpoints";

const TODAY = new Date().toISOString().slice(0, 10);
const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <Label className="block min-w-0 space-y-1.5"><span className="block">{label}</span>{children}</Label>;
}

function refs(value: string): string[] {
  return value.split(",").map((row) => row.trim()).filter(Boolean);
}

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

export function IpOppositionApplicantWorkflow({
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
    queryKey: ["ip", "opposition-applicant-workflow", docket.id, proceeding.id],
    queryFn: () => fetchIpOppositionApplicantWorkflow({ docketId: docket.id, proceedingId: proceeding.id }),
  });
  const deadlineWorkspace = useQuery({
    queryKey: ["ip", "deadline-workspace", docket.id],
    queryFn: () => fetchIpDeadlineWorkspace(docket.id),
  });

  const [oppositionNumber, setOppositionNumber] = useState("");
  const [numberSource, setNumberSource] = useState("Trade Marks Registry record");
  const [baseDate, setBaseDate] = useState(TODAY);
  const [certainty, setCertainty] = useState<"certain" | "uncertain" | "conflicting" | "unknown">("certain");
  const [ruleVersionId, setRuleVersionId] = useState("");
  const [calendarVersionId, setCalendarVersionId] = useState("");
  const [primaryId, setPrimaryId] = useState(currentMembershipId ?? "");
  const [backupId, setBackupId] = useState("");
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
  const [sourceReference, setSourceReference] = useState("");
  const [documentRefs, setDocumentRefs] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [reason, setReason] = useState("");

  const next = workflow.data?.next_required_action;
  const workflowStage = next?.includes("applicant_evidence")
    ? "applicant_evidence_due" as const
    : "counterstatement_due" as const;
  const exactRules = useMemo(
    () => (deadlineWorkspace.data?.rules ?? []).filter((row) =>
      row.status === "active" && row.proceeding_kind === "opposition" &&
      row.role === "applicant" && row.stage === workflowStage),
    [deadlineWorkspace.data?.rules, workflowStage],
  );
  const activeCalendars = (deadlineWorkspace.data?.calendars ?? []).filter((row) => row.status === "active");
  const selectedRule = ruleVersionId || exactRules[0]?.id || "";
  const selectedCalendar = calendarVersionId || activeCalendars[0]?.id || "";
  const triggerEvent = workflowStage === "counterstatement_due"
    ? workspace.profile_event
    : [...workspace.stage_events].reverse().find((row) => row.after_phase === "opponent_evidence_filed" || row.resulting_stage === "opponent_evidence_filed");

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-applicant-workflow", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "deadline-workspace", docket.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-workspace", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] }),
    ]);
  };
  const mutationOptions = {
    onSuccess: async () => { toast.success("Applicant opposition workflow updated."); await refresh(); },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, "The applicant workflow change was rejected.")),
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
    mutationFn: () => proposeIpOppositionApplicantDeadline({
      docketId: docket.id,
      proceedingId: proceeding.id,
      workflowStage,
      triggerEventId: triggerEvent?.id ?? "",
      ruleVersionId: selectedRule,
      calendarVersionId: selectedCalendar,
      baseDate: baseDate || null,
      certainty,
    }),
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
  const recordAction = useMutation({
    mutationFn: () => {
      if (!next || !currentMembershipId) throw new Error("Applicant action is unavailable.");
      const actionKind = next === "file_counterstatement"
        ? "counterstatement_filed" as const
        : next === "record_counterstatement_service"
          ? "counterstatement_served" as const
          : "applicant_evidence_decision" as const;
      return recordIpOppositionApplicantAction({
        docketId: docket.id,
        proceedingId: proceeding.id,
        lifecycleVersion: docket.lifecycle_version,
        proceedingVersion: proceeding.version,
        responsibleMembershipId: currentMembershipId,
        actionKind,
        sourceReference,
        effectiveAt: new Date().toISOString(),
        reason,
        filingReference: actionKind === "counterstatement_filed" ? filingReference : null,
        filedOn: actionKind === "counterstatement_filed" ? filedOn : null,
        verification: actionKind === "counterstatement_filed" ? {
          signatory,
          authority,
          place,
          verified_on: filedOn,
          verified_paragraph_ranges: refs(paragraphs),
          knowledge_basis: knowledgeBasis,
          signed_document_ref: refs(documentRefs)[0],
        } : null,
        service: actionKind === "counterstatement_served" ? {
          method: serviceMethod,
          destination: serviceDestination,
          served_on: servedOn,
          acknowledgement: null,
          starts_response_period: true,
          evidence_refs: refs(evidenceRefs),
        } : null,
        evidenceElection: actionKind === "applicant_evidence_decision" ? election : null,
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

  const actionReady = Boolean(sourceReference.trim() && reason.trim().length >= 5 && (
    next === "file_counterstatement"
      ? filingReference.trim() && filedOn && signatory.trim() && authority.trim() && place.trim() && refs(paragraphs).length && knowledgeBasis.trim() && refs(documentRefs).length && refs(evidenceRefs).length
      : next === "record_counterstatement_service"
        ? serviceMethod.trim() && serviceDestination.trim() && servedOn && refs(evidenceRefs).length
        : next === "record_applicant_evidence_decision"
          ? refs(evidenceRefs).length && (election === "rely_on_pleaded_facts" || refs(documentRefs).length)
          : false
  ));

  return (
    <section data-testid="ip-opposition-applicant-workflow" className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h4 className="font-semibold">Applicant docketing</h4><p className="text-sm text-[var(--color-mute)]">Next: {readable(workflow.data.next_required_action)}</p></div>
        <Badge tone={workflow.data.opposition_number_status === "confirmed" ? "success" : "warning"}>{readable(workflow.data.opposition_number_status)}</Badge>
      </div>

      {next === "record_opposition_number" ? <form className="grid gap-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); addNumber.mutate(); }}>
        <Field label="Opposition number"><Input value={oppositionNumber} onChange={(event) => setOppositionNumber(event.target.value)} /></Field>
        <Field label="Registry source"><Input value={numberSource} onChange={(event) => setNumberSource(event.target.value)} /></Field>
        <div className="flex items-end"><Button type="submit" disabled={!canReview || !oppositionNumber.trim() || !numberSource.trim() || addNumber.isPending}><Hash className="h-4 w-4" /> Record number</Button></div>
      </form> : null}

      {next?.startsWith("propose_") ? <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-5" onSubmit={(event) => { event.preventDefault(); propose.mutate(); }}>
        <Field label="Governed rule"><select className={SELECT_CLASS} value={selectedRule} onChange={(event) => setRuleVersionId(event.target.value)}>{exactRules.map((row) => <option key={row.id} value={row.id}>{row.key} v{row.version}</option>)}</select></Field>
        <Field label="Working calendar"><select className={SELECT_CLASS} value={selectedCalendar} onChange={(event) => setCalendarVersionId(event.target.value)}>{activeCalendars.map((row) => <option key={row.id} value={row.id}>{row.name} v{row.version}</option>)}</select></Field>
        <Field label="Trigger date"><Input type="date" value={baseDate} onChange={(event) => setBaseDate(event.target.value)} /></Field>
        <Field label="Date certainty"><select className={SELECT_CLASS} value={certainty} onChange={(event) => setCertainty(event.target.value as typeof certainty)}><option value="certain">Certain</option><option value="uncertain">Uncertain</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option></select></Field>
        <div className="flex items-end"><Button type="submit" disabled={!canReview || !triggerEvent || !selectedRule || !selectedCalendar || propose.isPending}><CalendarClock className="h-4 w-4" /> Propose deadline</Button></div>
        {!triggerEvent ? <p className="text-sm text-[var(--color-danger)] md:col-span-2 xl:col-span-5">The confirmed trigger event is not yet recorded.</p> : null}
        {!exactRules.length ? <p className="text-sm text-[var(--color-danger)] md:col-span-2 xl:col-span-5">No active governed opposition/applicant/{workflowStage} rule is available.</p> : null}
      </form> : null}

      {workflow.data.deadlines.length ? <div className="space-y-2">{workflow.data.deadlines.map(({ workflow_stage, deadline }) => <div key={deadline.id} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[1fr_180px_180px_auto]">
        <div><strong>{readable(workflow_stage)}</strong><p className="text-sm text-[var(--color-mute)]">{deadline.result_on ?? "Date unresolved"} · {deadline.state} · {deadline.rule_citation}</p></div>
        {deadline.state === "provisional" || deadline.state === "candidate" ? <><Input aria-label="Primary membership ID" value={primaryId} onChange={(event) => setPrimaryId(event.target.value)} placeholder="Primary membership ID" /><Input aria-label="Backup membership ID" value={backupId} onChange={(event) => setBackupId(event.target.value)} placeholder="Backup membership ID" /><Button type="button" onClick={() => confirm.mutate(deadline)} disabled={!canReview || !primaryId.trim() || !backupId.trim() || primaryId.trim() === backupId.trim() || confirm.isPending}><Check className="h-4 w-4" /> Confirm</Button></> : <Badge tone="success">Confirmed</Badge>}
      </div>)}</div> : null}

      {next && ["file_counterstatement", "record_counterstatement_service", "record_applicant_evidence_decision"].includes(next) ? <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); recordAction.mutate(); }}>
        {next === "file_counterstatement" ? <><Field label="TM-O filing reference"><Input value={filingReference} onChange={(event) => setFilingReference(event.target.value)} /></Field><Field label="Filed and verified on"><Input type="date" value={filedOn} onChange={(event) => setFiledOn(event.target.value)} /></Field><Field label="Signatory"><Input value={signatory} onChange={(event) => setSignatory(event.target.value)} /></Field><Field label="Authority"><Input value={authority} onChange={(event) => setAuthority(event.target.value)} /></Field><Field label="Place"><Input value={place} onChange={(event) => setPlace(event.target.value)} /></Field><Field label="Verified paragraph ranges"><Input value={paragraphs} onChange={(event) => setParagraphs(event.target.value)} placeholder="1-12, verification" /></Field><Field label="Knowledge basis"><Textarea value={knowledgeBasis} onChange={(event) => setKnowledgeBasis(event.target.value)} /></Field></> : null}
        {next === "record_counterstatement_service" ? <><Field label="Service method"><Input value={serviceMethod} onChange={(event) => setServiceMethod(event.target.value)} /></Field><Field label="Destination"><Input value={serviceDestination} onChange={(event) => setServiceDestination(event.target.value)} /></Field><Field label="Served on"><Input type="date" value={servedOn} onChange={(event) => setServedOn(event.target.value)} /></Field></> : null}
        {next === "record_applicant_evidence_decision" ? <Field label="Rule 46 election"><select className={SELECT_CLASS} value={election} onChange={(event) => setElection(event.target.value as typeof election)}><option value="rely_on_pleaded_facts">Rely on pleaded facts</option><option value="file_evidence">File applicant evidence</option></select></Field> : null}
        <Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field>
        <Field label="Document references"><Input value={documentRefs} onChange={(event) => setDocumentRefs(event.target.value)} placeholder="Comma separated" /></Field>
        <Field label="Evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field>
        <Field label="Lawyer reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
        <div className="flex items-end"><Button type="submit" disabled={!canReview || !currentMembershipId || !actionReady || recordAction.isPending}>{next === "record_counterstatement_service" ? <Send className="h-4 w-4" /> : <FileSignature className="h-4 w-4" />} Record work product</Button></div>
      </form> : null}
    </section>
  );
}
