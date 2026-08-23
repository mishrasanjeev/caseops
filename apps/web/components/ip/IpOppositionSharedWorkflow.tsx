"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, FileArchive, Gavel, Link2, TimerReset } from "lucide-react";
import { cloneElement, useEffect, useId, useMemo, useState, type ReactElement } from "react";
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
  createIpSharedHearing,
  fetchIpOppositionSharedWorkflow,
  recordIpOppositionSharedAction,
  type IpDocket,
  type IpOppositionSharedWorkflow as SharedWorkflow,
  type IpOppositionWorkspace,
} from "@/lib/api/endpoints";

type ActionKind = Parameters<typeof recordIpOppositionSharedAction>[0]["actionKind"];

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm";
const ACTIONS: Array<{ value: ActionKind; label: string }> = [
  { value: "deadline_extended", label: "Deadline extension" },
  { value: "further_evidence_leave_recorded", label: "Further-evidence leave" },
  { value: "evidence_package_recorded", label: "Evidence package" },
  { value: "hearing_preparation_recorded", label: "Hearing preparation" },
  { value: "post_hearing_note_recorded", label: "Post-hearing note" },
  { value: "order_recorded", label: "Opposition order" },
  { value: "appeal_linked", label: "Appeal link" },
];

function Field({ label, children }: { label: string; children: ReactElement<{ id?: string }> }) {
  const id = useId();
  return <div className="min-w-0 space-y-1.5"><Label htmlFor={id}>{label}</Label>{cloneElement(children, { id: children.props.id ?? id })}</div>;
}

function refs(value: string) {
  return value.split(",").map((row) => row.trim()).filter(Boolean);
}

function readable(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function localDateTime() {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}

function suggestedAction(next: SharedWorkflow["next_required_action"]): ActionKind {
  if (next === "record_evidence_package") return "evidence_package_recorded";
  if (next === "record_hearing_preparation") return "hearing_preparation_recorded";
  if (next === "record_post_hearing_note") return "post_hearing_note_recorded";
  if (next === "record_order") return "order_recorded";
  if (next === "link_appeal") return "appeal_linked";
  return "deadline_extended";
}

export function IpOppositionSharedWorkflow({
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
  const queryKey = ["ip", "opposition-shared-workflow", docket.id, proceeding.id];
  const workflow = useQuery({
    queryKey,
    queryFn: () => fetchIpOppositionSharedWorkflow({ docketId: docket.id, proceedingId: proceeding.id }),
  });

  const [actionKind, setActionKind] = useState<ActionKind>("deadline_extended");
  const [sourceReference, setSourceReference] = useState("");
  const [effectiveAt, setEffectiveAt] = useState(localDateTime);
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [documentRefs, setDocumentRefs] = useState("");
  const [acknowledgeBackdated, setAcknowledgeBackdated] = useState(false);

  const [deadlineId, setDeadlineId] = useState("");
  const [newDeadlineOn, setNewDeadlineOn] = useState("");
  const [primaryId, setPrimaryId] = useState(currentMembershipId ?? "");
  const [backupId, setBackupId] = useState("");

  const [packageKind, setPackageKind] = useState<"rule_45" | "rule_46" | "rule_47" | "further_evidence">(
    proceeding.side === "applicant" ? "rule_46" : "rule_45",
  );
  const [packageVersion, setPackageVersion] = useState(1);
  const [deponent, setDeponent] = useState("");
  const [affidavitRef, setAffidavitRef] = useState("");
  const [exhibitRefs, setExhibitRefs] = useState("");
  const [indexRef, setIndexRef] = useState("");
  const [reliedRefs, setReliedRefs] = useState("");
  const [filingReference, setFilingReference] = useState("");
  const [filedOn, setFiledOn] = useState("");
  const [signatory, setSignatory] = useState("");
  const [authority, setAuthority] = useState("");
  const [place, setPlace] = useState("");
  const [paragraphs, setParagraphs] = useState("");
  const [knowledgeBasis, setKnowledgeBasis] = useState("");
  const [signedRef, setSignedRef] = useState("");
  const [serviceMethod, setServiceMethod] = useState("");
  const [serviceDestination, setServiceDestination] = useState("");
  const [serviceRefs, setServiceRefs] = useState("");
  const [leaveReference, setLeaveReference] = useState("");
  const [leaveScope, setLeaveScope] = useState("");
  const [leaveGrantedOn, setLeaveGrantedOn] = useState("");

  const [hearingId, setHearingId] = useState("");
  const [checklist, setChecklist] = useState("");
  const [issues, setIssues] = useState("");
  const [hearingEvidenceRefs, setHearingEvidenceRefs] = useState("");
  const [authorityRefs, setAuthorityRefs] = useState("");
  const [submissionRefs, setSubmissionRefs] = useState("");
  const [attendanceIds, setAttendanceIds] = useState(currentMembershipId ?? "");
  const [causeListSource, setCauseListSource] = useState("");
  const [postHearingNotes, setPostHearingNotes] = useState("");
  const [hearingOn, setHearingOn] = useState("");
  const [hearingForum, setHearingForum] = useState(workspace.profile?.forum ?? proceeding.office);
  const [hearingPurpose, setHearingPurpose] = useState("Opposition hearing");

  const [operativeResult, setOperativeResult] = useState("");
  const [costDirections, setCostDirections] = useState("");
  const [complianceDirection, setComplianceDirection] = useState("");
  const [complianceDueOn, setComplianceDueOn] = useState("");
  const [orderDocumentRef, setOrderDocumentRef] = useState("");
  const [appealReview, setAppealReview] = useState<"required" | "not_required" | "pending">("pending");
  const [appealTargetKind, setAppealTargetKind] = useState<"appeal_proceeding" | "matter">("appeal_proceeding");
  const [appealTargetId, setAppealTargetId] = useState("");
  const [appealIdentifier, setAppealIdentifier] = useState("");
  const [orderEventId, setOrderEventId] = useState("");

  useEffect(() => {
    if (!workflow.data) return;
    setActionKind(suggestedAction(workflow.data.next_required_action));
    setDeadlineId((value) => value || workflow.data.active_deadlines[0]?.id || "");
    setHearingId((value) => value || workflow.data.shared_hearings[0]?.id || "");
    const order = [...workflow.data.shared_actions].reverse().find(
      (event) => event.payload_json.action_kind === "order_recorded",
    );
    setOrderEventId((value) => value || order?.id || "");
  }, [workflow.data]);

  const selectedDeadline = workflow.data?.active_deadlines.find((row) => row.id === deadlineId);
  const selectedHearing = workflow.data?.shared_hearings.find((row) => row.id === hearingId);
  const eventDetails = useMemo(() => {
    const verification = {
      signatory,
      authority,
      place,
      verified_on: filedOn,
      verified_paragraph_ranges: refs(paragraphs),
      knowledge_basis: knowledgeBasis,
      signed_document_ref: signedRef,
    };
    const service = {
      method: serviceMethod,
      destination: serviceDestination,
      served_on: filedOn,
      starts_response_period: false,
      evidence_refs: refs(serviceRefs),
    };
    const preparation = {
      shared_hearing_id: hearingId,
      checklist_items: refs(checklist),
      issues: refs(issues),
      evidence_document_refs: refs(hearingEvidenceRefs),
      authority_refs: refs(authorityRefs),
      written_submission_document_refs: refs(submissionRefs),
      attendance_membership_ids: refs(attendanceIds),
      cause_list_source: causeListSource,
      post_hearing_notes: actionKind === "post_hearing_note_recorded" ? postHearingNotes : null,
    };
    return {
      deadlineExtension: selectedDeadline ? {
        deadline_id: selectedDeadline.id,
        expected_deadline_version: selectedDeadline.version,
        new_result_on: newDeadlineOn,
        responsibilities: [
          { membership_id: primaryId, role: "primary", accepted: true },
          { membership_id: backupId, role: "backup", accepted: true },
        ],
        reminder_offsets_days: [7, 1, 0],
      } : null,
      furtherEvidenceLeave: {
        leave_or_order_reference: leaveReference,
        permitted_scope: leaveScope,
        granted_on: leaveGrantedOn,
      },
      evidencePackage: {
        package_kind: packageKind,
        package_version: packageVersion,
        affidavit_deponent: deponent,
        affidavit_document_ref: affidavitRef,
        exhibit_document_refs: refs(exhibitRefs),
        index_document_ref: indexRef,
        verification,
        relied_on_document_refs: refs(reliedRefs),
        filing_reference: filingReference,
        filed_on: filedOn,
        service,
        leave_or_order_reference: packageKind === "further_evidence" ? leaveReference : null,
      },
      hearingPreparation: preparation,
      orderDetails: {
        operative_result: operativeResult,
        affected_application_id: proceeding.application_id,
        affected_proceeding_id: proceeding.id,
        costs_and_directions: refs(costDirections),
        compliance_directions: complianceDirection.trim() && complianceDueOn
          ? [{ direction: complianceDirection, due_on: complianceDueOn }]
          : [],
        appeal_review: appealReview,
        order_document_ref: orderDocumentRef,
      },
      appealLink: {
        target_kind: appealTargetKind,
        target_id: appealTargetId,
        appeal_identifier: appealIdentifier,
        order_event_id: orderEventId,
      },
    };
  }, [actionKind, affidavitRef, appealIdentifier, appealReview, appealTargetId, appealTargetKind, attendanceIds, authority, authorityRefs, backupId, causeListSource, checklist, complianceDirection, complianceDueOn, costDirections, deponent, exhibitRefs, filedOn, filingReference, hearingEvidenceRefs, hearingId, indexRef, issues, knowledgeBasis, leaveGrantedOn, leaveReference, leaveScope, newDeadlineOn, operativeResult, orderDocumentRef, orderEventId, packageKind, packageVersion, paragraphs, place, postHearingNotes, primaryId, proceeding.application_id, proceeding.id, reliedRefs, selectedDeadline, serviceDestination, serviceMethod, serviceRefs, signatory, signedRef, submissionRefs]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-workspace", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-applicant-workflow", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "opposition-opponent-workflow", docket.id, proceeding.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "shared-hearings", docket.id] }),
    ]);
  };
  const mutationOptions = {
    onSuccess: async () => { toast.success("Opposition record updated."); await refresh(); },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, "The opposition record was rejected.")),
  };
  const record = useMutation({
    mutationFn: () => {
      if (!currentMembershipId) throw new Error("A responsible member is required.");
      return recordIpOppositionSharedAction({
        docketId: docket.id,
        proceedingId: proceeding.id,
        lifecycleVersion: docket.lifecycle_version,
        proceedingVersion: proceeding.version,
        responsibleMembershipId: currentMembershipId,
        actionKind,
        sourceReference,
        effectiveAt: new Date(effectiveAt).toISOString(),
        reason,
        authorizedConfirmation: confirmation,
        evidenceRefs: refs(evidenceRefs),
        documentRefs: refs(documentRefs),
        acknowledgeBackdated,
        ...(actionKind === "deadline_extended" ? { deadlineExtension: eventDetails.deadlineExtension } : {}),
        ...(actionKind === "further_evidence_leave_recorded" ? { furtherEvidenceLeave: eventDetails.furtherEvidenceLeave } : {}),
        ...(actionKind === "evidence_package_recorded" ? { evidencePackage: eventDetails.evidencePackage } : {}),
        ...(["hearing_preparation_recorded", "post_hearing_note_recorded"].includes(actionKind) ? { hearingPreparation: eventDetails.hearingPreparation } : {}),
        ...(actionKind === "order_recorded" ? { orderDetails: eventDetails.orderDetails } : {}),
        ...(actionKind === "appeal_linked" ? { appealLink: eventDetails.appealLink } : {}),
      });
    },
    ...mutationOptions,
  });
  const scheduleHearing = useMutation({
    mutationFn: () => {
      if (!currentMembershipId) throw new Error("A responsible member is required.");
      return createIpSharedHearing({
        docketId: docket.id,
        hearingOn,
        timeStatus: "time_not_published",
        timezone: "Asia/Kolkata",
        forumName: hearingForum,
        purpose: hearingPurpose,
        hearingMode: "unknown",
        source: "manual",
        responsibleMembershipId: currentMembershipId,
        attendeeMembershipIds: [currentMembershipId],
        reminderOffsetsHours: [168, 24],
        reminderChannels: ["in_app", "email"],
        reminderRecipientMembershipIds: [currentMembershipId],
      });
    },
    ...mutationOptions,
  });

  if (workflow.isLoading) return <Skeleton className="h-36 w-full" />;
  if (workflow.isError) return <QueryErrorState error={workflow.error} onRetry={() => workflow.refetch()} />;
  if (!workflow.data) return null;

  const commonReady = Boolean(
    canReview && currentMembershipId && sourceReference.trim().length >= 2 && effectiveAt
    && reason.trim().length >= 5 && confirmation.trim().length >= 2 && refs(evidenceRefs).length,
  );
  const detailReady = actionKind === "deadline_extended"
    ? Boolean(selectedDeadline && newDeadlineOn && primaryId.trim() && backupId.trim() && primaryId.trim() !== backupId.trim())
    : actionKind === "further_evidence_leave_recorded"
      ? Boolean(leaveReference.trim() && leaveScope.trim().length >= 5 && leaveGrantedOn)
      : actionKind === "evidence_package_recorded"
        ? Boolean(deponent.trim() && affidavitRef.trim() && refs(exhibitRefs).length && indexRef.trim() && refs(reliedRefs).length && filingReference.trim() && filedOn && signatory.trim() && authority.trim() && place.trim() && refs(paragraphs).length && knowledgeBasis.trim() && signedRef.trim() && serviceMethod.trim() && serviceDestination.trim() && refs(serviceRefs).length && (packageKind !== "further_evidence" || leaveReference.trim()))
        : ["hearing_preparation_recorded", "post_hearing_note_recorded"].includes(actionKind)
          ? Boolean(selectedHearing && refs(checklist).length && refs(issues).length && refs(hearingEvidenceRefs).length && refs(authorityRefs).length && refs(attendanceIds).length && causeListSource.trim() && (actionKind !== "post_hearing_note_recorded" || postHearingNotes.trim()))
          : actionKind === "order_recorded"
            ? Boolean(operativeResult.trim().length >= 5 && proceeding.application_id && orderDocumentRef.trim())
            : Boolean(appealTargetId.trim() && appealIdentifier.trim() && orderEventId.trim());

  return (
    <section data-testid="ip-opposition-shared-workflow" className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h4 className="font-semibold">Evidence, hearing and decision</h4><p className="text-sm text-[var(--color-mute)]">Next: {readable(workflow.data.next_required_action)}</p></div>
        <Badge tone={workflow.data.current_stage === "closed" ? "neutral" : "brand"}>{readable(workflow.data.current_stage)}</Badge>
      </div>

      {workflow.data.next_required_action === "schedule_hearing" ? <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); scheduleHearing.mutate(); }}>
        <Field label="Hearing date"><Input type="date" value={hearingOn} onChange={(event) => setHearingOn(event.target.value)} /></Field>
        <Field label="Forum"><Input value={hearingForum} onChange={(event) => setHearingForum(event.target.value)} /></Field>
        <Field label="Purpose"><Input value={hearingPurpose} onChange={(event) => setHearingPurpose(event.target.value)} /></Field>
        <div className="flex items-end"><Button type="submit" disabled={!canReview || !currentMembershipId || !hearingOn || hearingForum.trim().length < 2 || hearingPurpose.trim().length < 2 || scheduleHearing.isPending}><CalendarPlus className="h-4 w-4" /> Schedule hearing</Button></div>
      </form> : null}

      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); record.mutate(); }}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Record type"><select className={SELECT_CLASS} value={actionKind} onChange={(event) => setActionKind(event.target.value as ActionKind)}>{ACTIONS.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}</select></Field>
          <Field label="Effective at"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></Field>
          <Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field>
          <Field label="Lawyer confirmation"><Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></Field>
        </div>

        {actionKind === "deadline_extended" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Active deadline"><select className={SELECT_CLASS} value={deadlineId} onChange={(event) => setDeadlineId(event.target.value)}><option value="">Select deadline</option>{workflow.data.active_deadlines.map((row) => <option key={row.id} value={row.id}>{row.title} - {row.result_on ?? "unresolved"}</option>)}</select></Field>
          <Field label="Extended result date"><Input type="date" value={newDeadlineOn} onChange={(event) => setNewDeadlineOn(event.target.value)} /></Field>
          <Field label="Primary membership ID"><Input value={primaryId} onChange={(event) => setPrimaryId(event.target.value)} /></Field>
          <Field label="Backup membership ID"><Input value={backupId} onChange={(event) => setBackupId(event.target.value)} /></Field>
        </div> : null}

        {actionKind === "further_evidence_leave_recorded" ? <div className="grid gap-3 md:grid-cols-3">
          <Field label="Leave or order reference"><Input value={leaveReference} onChange={(event) => setLeaveReference(event.target.value)} /></Field>
          <Field label="Granted on"><Input type="date" value={leaveGrantedOn} onChange={(event) => setLeaveGrantedOn(event.target.value)} /></Field>
          <Field label="Permitted scope"><Textarea value={leaveScope} onChange={(event) => setLeaveScope(event.target.value)} /></Field>
        </div> : null}

        {actionKind === "evidence_package_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Evidence rule"><select className={SELECT_CLASS} value={packageKind} onChange={(event) => setPackageKind(event.target.value as typeof packageKind)}><option value="rule_45">Rule 45</option><option value="rule_46">Rule 46</option><option value="rule_47">Rule 47</option><option value="further_evidence">Further evidence</option></select></Field>
          <Field label="Package version"><Input type="number" min={1} value={packageVersion} onChange={(event) => setPackageVersion(Number(event.target.value))} /></Field>
          <Field label="Affidavit deponent"><Input value={deponent} onChange={(event) => setDeponent(event.target.value)} /></Field>
          <Field label="Affidavit document"><Input value={affidavitRef} onChange={(event) => setAffidavitRef(event.target.value)} /></Field>
          <Field label="Exhibit documents"><Input value={exhibitRefs} onChange={(event) => setExhibitRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Evidence index"><Input value={indexRef} onChange={(event) => setIndexRef(event.target.value)} /></Field>
          <Field label="Relied-on documents"><Input value={reliedRefs} onChange={(event) => setReliedRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Filing reference"><Input value={filingReference} onChange={(event) => setFilingReference(event.target.value)} /></Field>
          <Field label="Filed and verified on"><Input type="date" value={filedOn} onChange={(event) => setFiledOn(event.target.value)} /></Field>
          <Field label="Signatory"><Input value={signatory} onChange={(event) => setSignatory(event.target.value)} /></Field>
          <Field label="Authority"><Input value={authority} onChange={(event) => setAuthority(event.target.value)} /></Field>
          <Field label="Place"><Input value={place} onChange={(event) => setPlace(event.target.value)} /></Field>
          <Field label="Verified paragraphs"><Input value={paragraphs} onChange={(event) => setParagraphs(event.target.value)} placeholder="1-12, verification" /></Field>
          <Field label="Knowledge basis"><Textarea value={knowledgeBasis} onChange={(event) => setKnowledgeBasis(event.target.value)} /></Field>
          <Field label="Signed affidavit reference"><Input value={signedRef} onChange={(event) => setSignedRef(event.target.value)} /></Field>
          <Field label="Service method"><Input value={serviceMethod} onChange={(event) => setServiceMethod(event.target.value)} /></Field>
          <Field label="Service destination"><Input value={serviceDestination} onChange={(event) => setServiceDestination(event.target.value)} /></Field>
          <Field label="Service evidence"><Input value={serviceRefs} onChange={(event) => setServiceRefs(event.target.value)} placeholder="Comma separated" /></Field>
          {packageKind === "further_evidence" ? <Field label="Leave or order reference"><Input value={leaveReference} onChange={(event) => setLeaveReference(event.target.value)} /></Field> : null}
        </div> : null}

        {["hearing_preparation_recorded", "post_hearing_note_recorded"].includes(actionKind) ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Shared hearing"><select className={SELECT_CLASS} value={hearingId} onChange={(event) => setHearingId(event.target.value)}><option value="">Select hearing</option>{workflow.data.shared_hearings.map((row) => <option key={row.id} value={row.id}>{row.hearing_on} - {row.forum_name} - {row.status}</option>)}</select></Field>
          <Field label="Checklist items"><Input value={checklist} onChange={(event) => setChecklist(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Issues"><Input value={issues} onChange={(event) => setIssues(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Evidence documents"><Input value={hearingEvidenceRefs} onChange={(event) => setHearingEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Authorities"><Input value={authorityRefs} onChange={(event) => setAuthorityRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Written submissions"><Input value={submissionRefs} onChange={(event) => setSubmissionRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Attendance membership IDs"><Input value={attendanceIds} onChange={(event) => setAttendanceIds(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Cause-list source"><Input value={causeListSource} onChange={(event) => setCauseListSource(event.target.value)} /></Field>
          {actionKind === "post_hearing_note_recorded" ? <Field label="Post-hearing note"><Textarea value={postHearingNotes} onChange={(event) => setPostHearingNotes(event.target.value)} /></Field> : null}
        </div> : null}

        {actionKind === "order_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Operative result"><Textarea value={operativeResult} onChange={(event) => setOperativeResult(event.target.value)} /></Field>
          <Field label="Costs and directions"><Input value={costDirections} onChange={(event) => setCostDirections(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Compliance direction"><Textarea value={complianceDirection} onChange={(event) => setComplianceDirection(event.target.value)} /></Field>
          <Field label="Compliance due date"><Input type="date" value={complianceDueOn} onChange={(event) => setComplianceDueOn(event.target.value)} /></Field>
          <Field label="Order document"><Input value={orderDocumentRef} onChange={(event) => setOrderDocumentRef(event.target.value)} /></Field>
          <Field label="Appeal review"><select className={SELECT_CLASS} value={appealReview} onChange={(event) => setAppealReview(event.target.value as typeof appealReview)}><option value="pending">Pending</option><option value="required">Required</option><option value="not_required">Not required</option></select></Field>
        </div> : null}

        {actionKind === "appeal_linked" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Appeal target"><select className={SELECT_CLASS} value={appealTargetKind} onChange={(event) => setAppealTargetKind(event.target.value as typeof appealTargetKind)}><option value="appeal_proceeding">Appeal proceeding</option><option value="matter">Matter</option></select></Field>
          <Field label="Target record ID"><Input value={appealTargetId} onChange={(event) => setAppealTargetId(event.target.value)} /></Field>
          <Field label="Appeal identifier"><Input value={appealIdentifier} onChange={(event) => setAppealIdentifier(event.target.value)} /></Field>
          <Field label="Opposition order event"><select className={SELECT_CLASS} value={orderEventId} onChange={(event) => setOrderEventId(event.target.value)}><option value="">Select order</option>{workflow.data.shared_actions.filter((event) => event.payload_json.action_kind === "order_recorded").map((event) => <option key={event.id} value={event.id}>{event.source_reference ?? event.id}</option>)}</select></Field>
        </div> : null}

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Document references"><Input value={documentRefs} onChange={(event) => setDocumentRefs(event.target.value)} placeholder="Comma separated" /></Field>
          <Field label="Reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={acknowledgeBackdated} onChange={(event) => setAcknowledgeBackdated(event.target.checked)} /> Recalculation preview reviewed</label>
        </div>
        <Button type="submit" disabled={!commonReady || !detailReady || record.isPending}>
          {actionKind === "deadline_extended" ? <TimerReset className="h-4 w-4" /> : actionKind === "order_recorded" ? <Gavel className="h-4 w-4" /> : actionKind === "appeal_linked" ? <Link2 className="h-4 w-4" /> : actionKind.includes("hearing") ? <Check className="h-4 w-4" /> : <FileArchive className="h-4 w-4" />}
          Record {ACTIONS.find((row) => row.value === actionKind)?.label.toLowerCase()}
        </Button>
      </form>

      {workflow.data.shared_actions.length ? <section className="border-t border-[var(--color-line)] pt-4"><h5 className="font-semibold">Shared event history</h5><ol className="mt-2 space-y-2">{[...workflow.data.shared_actions].reverse().map((event) => <li key={event.id} className="grid min-w-0 gap-1 rounded-md bg-[var(--color-bg-2)] p-3 text-sm md:grid-cols-[1fr_auto]"><div><strong>{readable(String(event.payload_json.action_kind ?? event.event_kind))}</strong><p className="break-words text-xs text-[var(--color-mute)]">{event.reason}</p></div><time className="text-xs text-[var(--color-mute)]">{new Date(event.effective_at).toLocaleDateString()}</time></li>)}</ol></section> : null}
    </section>
  );
}
