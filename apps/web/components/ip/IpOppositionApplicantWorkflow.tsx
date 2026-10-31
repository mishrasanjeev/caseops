"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, FileSignature, Hash, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { IpDeadlineProposalBlockers } from "@/components/ip/IpDeadlineProposalBlockers";
import { IpGovernedDeadlinePickers, resolveGovernedSelection } from "@/components/ip/IpGovernedDeadlinePickers";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PersonPicker } from "@/components/ui/PersonPicker";
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
  const [baseDate, setBaseDate] = useState("");
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
  const governedScope = { proceedingKind: "opposition", role: "applicant", stage: workflowStage };
  const governed = resolveGovernedSelection(deadlineWorkspace.data, governedScope, ruleVersionId, calendarVersionId);
  const selectedRule = governed.rule?.id ?? "";
  const selectedCalendar = governed.calendar?.id ?? "";
  const triggerEvent = workflowStage === "counterstatement_due"
    ? workspace.profile_event
    : [...workspace.stage_events].reverse().find((row) => row.after_phase === "opponent_evidence_filed" || row.resulting_stage === "opponent_evidence_filed");
  // The counterstatement period runs from service of the notice, which the
  // profile records; the evidence period from the recorded service event.
  const triggerDate = workflowStage === "counterstatement_due"
    ? workspace.profile?.service?.served_on ?? ""
    : triggerEvent?.effective_at?.slice(0, 10) ?? "";
  const triggerNoun = workflowStage === "counterstatement_due" ? "notice of opposition service date" : "opponent evidence service date";
  const triggerLabel = `${triggerNoun.charAt(0).toUpperCase()}${triggerNoun.slice(1)}`;
  useEffect(() => {
    setBaseDate(triggerDate);
  }, [triggerDate, triggerEvent?.id, workflowStage]);
  const responsibleIds = deadlineWorkspace.data?.eligible_responsible_membership_ids;
  const responsibleEmpty = "No colleague has lasting access to this matter and IP record. An owner or admin can grant access on the matter.";
  const proposalGaps = workspace.readiness_gaps ?? [];
  const proposeBlockers = [
    !canReview ? "Your role cannot propose legal deadlines; an IP reviewer must propose it." : null,
    !triggerEvent ? "The confirmed trigger event is not yet recorded." : null,
    !selectedRule || !selectedCalendar ? "Choose a governed rule and a working calendar above." : null,
    !baseDate ? `Enter the ${triggerNoun}; the period runs from it.` : null,
  ].filter((row): row is string => Boolean(row));

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

  if (workflow.isLoading) return <Skeleton className="h-32 w-full" />;
  if (workflow.isError) return <QueryErrorState error={workflow.error} onRetry={() => workflow.refetch()} />;
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
        <IpGovernedDeadlinePickers docketId={docket.id} idPrefix="applicant-deadline" scope={governedScope} workspace={deadlineWorkspace} selection={governed} onRuleChange={setRuleVersionId} onCalendarChange={setCalendarVersionId} />
        <Field label={triggerLabel}><Input type="date" required value={baseDate} onChange={(event) => setBaseDate(event.target.value)} /></Field>
        <Field label="Date certainty"><select className={SELECT_CLASS} value={certainty} onChange={(event) => setCertainty(event.target.value as typeof certainty)}><option value="certain">Certain</option><option value="uncertain">Uncertain</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option></select></Field>
        <div className="flex items-end"><Button type="submit" disabled={proposeBlockers.length > 0 || proposalGaps.length > 0 || propose.isPending} aria-describedby={proposeBlockers.length || proposalGaps.length ? "applicant-deadline-blockers" : undefined}><CalendarClock className="h-4 w-4" /> Propose deadline</Button></div>
        <IpDeadlineProposalBlockers id="applicant-deadline-blockers" gaps={proposalGaps} missing={proposeBlockers} />
      </form> : null}

      {workflow.data.deadlines.length ? <div className="space-y-2">{workflow.data.deadlines.map(({ workflow_stage, deadline }) => <div key={deadline.id} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div><strong>{readable(workflow_stage)}</strong><p className="text-sm text-[var(--color-mute)]">{deadline.result_on ?? "Date unresolved"} · {deadline.state} · {deadline.rule_citation}</p></div>
        {deadline.state === "provisional" || deadline.state === "candidate" ? <><div className="flex min-w-0 flex-col gap-1"><Label htmlFor={`applicant-primary-${deadline.id}`}>Responsible lawyer</Label><PersonPicker id={`applicant-primary-${deadline.id}`} value={primaryId} onChange={setPrimaryId} onlyMembershipIds={responsibleIds ?? []} disabled={!responsibleIds} emptyText={responsibleEmpty} /></div><div className="flex min-w-0 flex-col gap-1"><Label htmlFor={`applicant-backup-${deadline.id}`}>Backup lawyer</Label><PersonPicker id={`applicant-backup-${deadline.id}`} value={backupId} onChange={setBackupId} excludeMembershipIds={[primaryId]} onlyMembershipIds={responsibleIds ?? []} disabled={!responsibleIds} emptyText={responsibleEmpty} placeholder="Select a backup…" /></div><Button type="button" onClick={() => confirm.mutate(deadline)} disabled={!canReview || !primaryId.trim() || !backupId.trim() || primaryId.trim() === backupId.trim() || confirm.isPending}><Check className="h-4 w-4" /> Confirm</Button>{!primaryId.trim() || !backupId.trim() || primaryId.trim() === backupId.trim() ? <p className="text-xs text-[var(--color-mute)] md:col-span-4">Choose a responsible lawyer and a different backup to confirm this deadline.</p> : null}{deadlineWorkspace.isError ? <p className="text-xs text-[var(--color-danger)] md:col-span-4" role="alert">Colleagues who can own this deadline could not be loaded. <button type="button" className="underline" onClick={() => deadlineWorkspace.refetch()}>Retry</button></p> : null}</> : <Badge tone="success">Confirmed</Badge>}
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
