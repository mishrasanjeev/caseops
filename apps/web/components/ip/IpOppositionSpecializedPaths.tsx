"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Languages, Scale } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchIpOppositionSharedWorkflow,
  recordIpOppositionSharedAction,
  type IpDocket,
  type IpOppositionWorkspace,
} from "@/lib/api/endpoints";

type SpecializedAction =
  | "scope_review_recorded"
  | "translation_recorded"
  | "hearing_notice_recorded"
  | "adjournment_recorded"
  | "written_arguments_recorded"
  | "attendance_recorded"
  | "security_for_costs_recorded"
  | "disposition_review_recorded"
  | "madrid_designation_link_recorded";

type ScopeStatus = "unreviewed" | "challenged" | "continuing" | "withdrawn" | "decided";
type Fields = Record<string, string>;

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm";
const ACTIONS: Array<{ value: SpecializedAction; label: string }> = [
  { value: "scope_review_recorded", label: "Class and goods scope" },
  { value: "translation_recorded", label: "Attested translation" },
  { value: "hearing_notice_recorded", label: "Hearing notice" },
  { value: "adjournment_recorded", label: "Adjournment" },
  { value: "written_arguments_recorded", label: "Written arguments" },
  { value: "attendance_recorded", label: "Attendance or nonappearance" },
  { value: "security_for_costs_recorded", label: "Security for costs" },
  { value: "disposition_review_recorded", label: "Application disposition review" },
  { value: "madrid_designation_link_recorded", label: "Madrid designation" },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <Label className="block min-w-0 space-y-1.5"><span className="block">{label}</span>{children}</Label>;
}

function refs(value: string): string[] {
  return value.split(",").map((row) => row.trim()).filter(Boolean);
}

function localDateTime(): string {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}

export function IpOppositionSpecializedPaths({
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
  const [action, setAction] = useState<SpecializedAction>("scope_review_recorded");
  const [effectiveAt, setEffectiveAt] = useState(localDateTime);
  const [sourceReference, setSourceReference] = useState("");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [documentRefs, setDocumentRefs] = useState("");
  const [acknowledgeBackdated, setAcknowledgeBackdated] = useState(false);
  const [fields, setFields] = useState<Fields>({
    certainty: "certain",
    revision: "1",
    translatedLanguage: "English",
    noticeStatus: "unknown",
    minimumNoticeDays: "30",
    feeStatus: "not_required",
    priorAdjournments: "0",
    allowedAdjournments: "2",
    adjournmentOutcome: "pending",
    appearanceStatus: "attended",
    paymentStatus: "pending",
    enhancementAmount: "0",
    outcomeKind: "final_decision",
    reviewStatus: "pending",
  });
  const [scopeStatuses, setScopeStatuses] = useState<Record<string, ScopeStatus>>({});
  const [scopeSegments, setScopeSegments] = useState<Record<string, string>>({});
  const [scopeOutcomes, setScopeOutcomes] = useState<Record<string, string>>({});
  const set = (name: string, value: string) => setFields((current) => ({ ...current, [name]: value }));

  const service = {
    method: fields.serviceMethod,
    destination: fields.serviceDestination,
    served_on: fields.servedOn,
    starts_response_period: false,
    evidence_refs: refs(fields.serviceEvidence ?? ""),
  };
  const selectedHearingId = fields.hearingId ?? workflow.data?.shared_hearings[0]?.id ?? "";
  const selectedTriggerId = fields.triggerEventId ?? workspace.stage_events.at(-1)?.id ?? "";
  const scopeDecisions = (workflow.data?.application_scopes ?? []).flatMap((scope) => {
    const status = scopeStatuses[scope.id] ?? "unreviewed";
    return status === "unreviewed" ? [] : [{
      application_scope_id: scope.id,
      challenged_segment: scopeSegments[scope.id] || scope.specification,
      status,
      outcome: status === "decided" ? scopeOutcomes[scope.id] : null,
    }];
  });

  const details = {
    scopeReview: {
      revision: Number(fields.revision),
      source_scope_certainty: fields.certainty,
      source_confirmation_reference: fields.certainty === "certain" ? null : fields.scopeConfirmation,
      decisions: scopeDecisions,
      related_application_id: fields.relatedApplicationId || null,
      amendment_or_division_reference: fields.relatedApplicationId ? fields.divisionReference : null,
      preserve_unlisted_scopes: true,
    },
    translation: {
      source_document_ref: fields.sourceDocumentRef,
      source_document_sha256: fields.sourceHash,
      source_language: fields.sourceLanguage,
      translated_document_ref: fields.translatedDocumentRef,
      translated_document_sha256: fields.translatedHash,
      translated_language: fields.translatedLanguage,
      translator_name: fields.translatorName,
      translator_credential: fields.translatorCredential,
      attested_on: fields.attestedOn,
      attestation_reference: fields.attestationReference,
      service,
    },
    hearingNotice: {
      shared_hearing_id: selectedHearingId,
      notice_received_on: fields.noticeReceivedOn,
      notice_document_ref: fields.noticeDocumentRef,
      minimum_notice_days: Number(fields.minimumNoticeDays),
      notice_status: fields.noticeStatus,
      applicable_rule_version: fields.ruleVersion,
      confirmation_reference: fields.policyConfirmation,
    },
    adjournment: {
      shared_hearing_id: selectedHearingId,
      requested_on: fields.requestedOn,
      request_form_ref: fields.requestFormRef,
      request_reason: fields.requestReason,
      fee_status: fields.feeStatus,
      fee_amount_minor: fields.feeStatus === "paid" ? Number(fields.feeAmount) : null,
      fee_evidence_ref: fields.feeStatus === "paid" ? fields.feeEvidence : null,
      prior_adjournment_count: Number(fields.priorAdjournments),
      allowed_count_candidate: Number(fields.allowedAdjournments),
      applicable_rule_version: fields.ruleVersion,
      policy_confirmation_reference: fields.policyConfirmation,
      outcome: fields.adjournmentOutcome,
    },
    writtenArguments: {
      shared_hearing_id: selectedHearingId,
      filed_on: fields.filedOn,
      filing_reference: fields.filingReference,
      document_refs: refs(fields.argumentDocuments ?? ""),
      service,
    },
    attendance: {
      shared_hearing_id: selectedHearingId,
      appearance_status: fields.appearanceStatus,
      attendee_membership_ids: refs(fields.attendeeIds ?? ""),
      attendance_source_ref: fields.attendanceSource,
      nonappearance_consequence_candidate: fields.appearanceStatus === "nonappearance" ? fields.consequence : null,
      applicable_rule_version: fields.ruleVersion,
      consequence_confirmation_reference: fields.appearanceStatus === "nonappearance" ? fields.policyConfirmation : null,
    },
    securityForCosts: {
      direction_reference: fields.directionReference,
      directed_on: fields.directedOn,
      amount_minor: Number(fields.amount),
      enhancement_amount_minor: Number(fields.enhancementAmount),
      due_on: fields.dueOn,
      payment_status: fields.paymentStatus,
      paid_on: fields.paymentStatus === "paid" ? fields.paidOn : null,
      payment_reference: fields.paymentStatus === "paid" ? fields.paymentReference : null,
      consequence_candidate: fields.consequence,
      applicable_rule_version: fields.ruleVersion,
      fee_classification: "security_for_costs",
    },
    dispositionReview: {
      trigger_event_id: selectedTriggerId,
      outcome_kind: fields.outcomeKind,
      affected_application_scope_ids: refs(fields.affectedScopeIds ?? ""),
      recommended_application_disposition: fields.recommendation,
      review_status: fields.reviewStatus,
      review_reference: fields.reviewReference,
      no_automatic_application_update: true,
    },
    madridDesignation: {
      application_id: proceeding.application_id,
      international_registration_number: fields.irNumber,
      wipo_reference: fields.wipoReference,
      india_designation_identifier: fields.indiaDesignation,
      designation_status: fields.designationStatus,
      lifecycle_source_reference: fields.lifecycleSource,
    },
  };

  const commonReady = Boolean(canReview && currentMembershipId && sourceReference.trim().length >= 2
    && effectiveAt && reason.trim().length >= 5 && confirmation.trim().length >= 2 && refs(evidenceRefs).length);
  const serviceReady = Boolean(fields.serviceMethod && fields.serviceDestination && fields.servedOn && refs(fields.serviceEvidence ?? "").length);
  const hearingReady = Boolean(selectedHearingId);
  const detailReady = action === "scope_review_recorded" ? scopeDecisions.length > 0
    && (fields.certainty === "certain" || Boolean(fields.scopeConfirmation))
    && (!fields.relatedApplicationId || Boolean(fields.divisionReference))
    : action === "translation_recorded" ? Boolean(fields.sourceDocumentRef && fields.sourceHash?.length === 64
      && fields.sourceLanguage && fields.translatedDocumentRef && fields.translatedHash?.length === 64
      && fields.translatorName && fields.translatorCredential && fields.attestedOn && fields.attestationReference && serviceReady)
      : action === "hearing_notice_recorded" ? Boolean(hearingReady && fields.noticeReceivedOn && fields.noticeDocumentRef && fields.ruleVersion && fields.policyConfirmation)
        : action === "adjournment_recorded" ? Boolean(hearingReady && fields.requestedOn && fields.requestFormRef && fields.requestReason?.length >= 5
          && fields.ruleVersion && fields.policyConfirmation && (fields.feeStatus !== "paid" || (fields.feeAmount && fields.feeEvidence)))
          : action === "written_arguments_recorded" ? Boolean(hearingReady && fields.filedOn && fields.filingReference && refs(fields.argumentDocuments ?? "").length && serviceReady)
            : action === "attendance_recorded" ? Boolean(hearingReady && fields.attendanceSource && fields.ruleVersion
              && (fields.appearanceStatus !== "attended" || refs(fields.attendeeIds ?? "").length)
              && (fields.appearanceStatus !== "nonappearance" || (fields.consequence && fields.policyConfirmation)))
              : action === "security_for_costs_recorded" ? Boolean(fields.directionReference && fields.directedOn && fields.amount && fields.dueOn
                && fields.consequence?.length >= 5 && fields.ruleVersion && (fields.paymentStatus !== "paid" || (fields.paidOn && fields.paymentReference)))
                : action === "disposition_review_recorded" ? Boolean(selectedTriggerId && refs(fields.affectedScopeIds ?? "").length
                  && fields.recommendation && fields.reviewReference)
                  : Boolean(proceeding.application_id && fields.irNumber && fields.wipoReference && fields.indiaDesignation
                    && fields.designationStatus && fields.lifecycleSource);

  const record = useMutation({
    mutationFn: () => {
      if (!currentMembershipId) throw new Error("A responsible member is required.");
      return recordIpOppositionSharedAction({
        docketId: docket.id,
        proceedingId: proceeding.id,
        lifecycleVersion: docket.lifecycle_version,
        proceedingVersion: proceeding.version,
        responsibleMembershipId: currentMembershipId,
        actionKind: action,
        sourceReference,
        effectiveAt: new Date(effectiveAt).toISOString(),
        reason,
        authorizedConfirmation: confirmation,
        evidenceRefs: refs(evidenceRefs),
        documentRefs: refs(documentRefs),
        acknowledgeBackdated,
        ...(action === "scope_review_recorded" ? { scopeReview: details.scopeReview } : {}),
        ...(action === "translation_recorded" ? { translation: details.translation } : {}),
        ...(action === "hearing_notice_recorded" ? { hearingNotice: details.hearingNotice } : {}),
        ...(action === "adjournment_recorded" ? { adjournment: details.adjournment } : {}),
        ...(action === "written_arguments_recorded" ? { writtenArguments: details.writtenArguments } : {}),
        ...(action === "attendance_recorded" ? { attendance: details.attendance } : {}),
        ...(action === "security_for_costs_recorded" ? { securityForCosts: details.securityForCosts } : {}),
        ...(action === "disposition_review_recorded" ? { dispositionReview: details.dispositionReview } : {}),
        ...(action === "madrid_designation_link_recorded" ? { madridDesignation: details.madridDesignation } : {}),
      });
    },
    onSuccess: async () => {
      toast.success("Specialized opposition record added.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey }),
        queryClient.invalidateQueries({ queryKey: ["ip", "opposition-workspace", docket.id, proceeding.id] }),
      ]);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "The specialized opposition record was rejected.")),
  });

  if (workflow.isLoading) return <Skeleton className="h-32 w-full" />;
  if (workflow.isError) return <QueryErrorState error={workflow.error} onRetry={() => workflow.refetch()} />;
  if (!workflow.data) return null;

  const hearingField = <Field label="Canonical hearing"><select data-testid="ip-opposition-specialized-hearing" className={SELECT_CLASS} value={selectedHearingId} onChange={(event) => set("hearingId", event.target.value)}><option value="">Select hearing</option>{workflow.data.shared_hearings.map((row) => <option key={row.id} value={row.id}>{row.hearing_on} - {row.forum_name} - {row.status}</option>)}</select></Field>;
  const serviceFields = <><Field label="Service method"><Input value={fields.serviceMethod ?? ""} onChange={(event) => set("serviceMethod", event.target.value)} /></Field><Field label="Service destination"><Input value={fields.serviceDestination ?? ""} onChange={(event) => set("serviceDestination", event.target.value)} /></Field><Field label="Served on"><Input type="date" value={fields.servedOn ?? ""} onChange={(event) => set("servedOn", event.target.value)} /></Field><Field label="Service evidence"><Input value={fields.serviceEvidence ?? ""} onChange={(event) => set("serviceEvidence", event.target.value)} placeholder="Comma separated" /></Field></>;

  return <section data-testid="ip-opposition-specialized-paths" className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4">
    <div><h4 className="font-semibold">Specialized opposition paths</h4><p className="text-sm text-[var(--color-mute)]">Class-level scope and procedural records remain linked to the canonical opposition timeline.</p></div>
    <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); record.mutate(); }}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Field label="Record type"><select data-testid="ip-opposition-specialized-action" className={SELECT_CLASS} value={action} onChange={(event) => setAction(event.target.value as SpecializedAction)}>{ACTIONS.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}</select></Field>
        <Field label="Effective at"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></Field>
        <Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field>
        <Field label="Lawyer confirmation"><Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></Field>
      </div>

      {action === "scope_review_recorded" ? <div className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="Revision"><Input type="number" min={1} value={fields.revision} onChange={(event) => set("revision", event.target.value)} /></Field><Field label="Registry scope certainty"><select className={SELECT_CLASS} value={fields.certainty} onChange={(event) => set("certainty", event.target.value)}><option value="certain">Certain</option><option value="partial">Partial</option><option value="missing">Missing</option></select></Field>{fields.certainty !== "certain" ? <Field label="Source confirmation"><Input value={fields.scopeConfirmation ?? ""} onChange={(event) => set("scopeConfirmation", event.target.value)} /></Field> : null}<Field label="Related application ID"><Input value={fields.relatedApplicationId ?? ""} onChange={(event) => set("relatedApplicationId", event.target.value)} /></Field>{fields.relatedApplicationId ? <Field label="Amendment or division reference"><Input value={fields.divisionReference ?? ""} onChange={(event) => set("divisionReference", event.target.value)} /></Field> : null}</div>
        <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)]"><th className="p-2">Class</th><th className="p-2">Current specification</th><th className="p-2">Decision</th><th className="p-2">Challenged segment</th><th className="p-2">Outcome</th></tr></thead><tbody>{workflow.data.application_scopes.map((scope) => { const status = scopeStatuses[scope.id] ?? "unreviewed"; return <tr key={scope.id} className="border-b border-[var(--color-line)]"><td className="p-2 font-medium">{scope.class_number}</td><td className="p-2">{scope.specification}</td><td className="p-2"><select aria-label={`Class ${scope.class_number} decision`} className={SELECT_CLASS} value={status} onChange={(event) => setScopeStatuses((current) => ({ ...current, [scope.id]: event.target.value as ScopeStatus }))}><option value="unreviewed">Not reviewed</option><option value="challenged">Challenged</option><option value="continuing">Continuing</option><option value="withdrawn">Withdrawn</option><option value="decided">Decided</option></select></td><td className="p-2"><Input aria-label={`Class ${scope.class_number} challenged segment`} value={scopeSegments[scope.id] ?? scope.specification} onChange={(event) => setScopeSegments((current) => ({ ...current, [scope.id]: event.target.value }))} /></td><td className="p-2"><Input aria-label={`Class ${scope.class_number} outcome`} disabled={status !== "decided"} value={scopeOutcomes[scope.id] ?? ""} onChange={(event) => setScopeOutcomes((current) => ({ ...current, [scope.id]: event.target.value }))} /></td></tr>; })}</tbody></table></div>
      </div> : null}

      {action === "translation_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="Source document"><Input value={fields.sourceDocumentRef ?? ""} onChange={(event) => set("sourceDocumentRef", event.target.value)} /></Field><Field label="Source SHA-256"><Input value={fields.sourceHash ?? ""} onChange={(event) => set("sourceHash", event.target.value)} /></Field><Field label="Source language"><Input value={fields.sourceLanguage ?? ""} onChange={(event) => set("sourceLanguage", event.target.value)} /></Field><Field label="Translated document"><Input value={fields.translatedDocumentRef ?? ""} onChange={(event) => set("translatedDocumentRef", event.target.value)} /></Field><Field label="Translation SHA-256"><Input value={fields.translatedHash ?? ""} onChange={(event) => set("translatedHash", event.target.value)} /></Field><Field label="Translated language"><select className={SELECT_CLASS} value={fields.translatedLanguage} onChange={(event) => set("translatedLanguage", event.target.value)}><option value="English">English</option><option value="Hindi">Hindi</option></select></Field><Field label="Translator"><Input value={fields.translatorName ?? ""} onChange={(event) => set("translatorName", event.target.value)} /></Field><Field label="Translator credential"><Input value={fields.translatorCredential ?? ""} onChange={(event) => set("translatorCredential", event.target.value)} /></Field><Field label="Attested on"><Input type="date" value={fields.attestedOn ?? ""} onChange={(event) => set("attestedOn", event.target.value)} /></Field><Field label="Attestation reference"><Input value={fields.attestationReference ?? ""} onChange={(event) => set("attestationReference", event.target.value)} /></Field>{serviceFields}</div> : null}

      {action === "hearing_notice_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{hearingField}<Field label="Notice received"><Input type="date" value={fields.noticeReceivedOn ?? ""} onChange={(event) => set("noticeReceivedOn", event.target.value)} /></Field><Field label="Notice document"><Input value={fields.noticeDocumentRef ?? ""} onChange={(event) => set("noticeDocumentRef", event.target.value)} /></Field><Field label="Minimum notice days"><Input type="number" min={0} value={fields.minimumNoticeDays} onChange={(event) => set("minimumNoticeDays", event.target.value)} /></Field><Field label="Notice status"><select className={SELECT_CLASS} value={fields.noticeStatus} onChange={(event) => set("noticeStatus", event.target.value)}><option value="unknown">Unknown</option><option value="sufficient">Sufficient</option><option value="short">Short</option></select></Field><Field label="Rule version"><Input value={fields.ruleVersion ?? ""} onChange={(event) => set("ruleVersion", event.target.value)} /></Field><Field label="Policy confirmation"><Input value={fields.policyConfirmation ?? ""} onChange={(event) => set("policyConfirmation", event.target.value)} /></Field></div> : null}

      {action === "adjournment_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{hearingField}<Field label="Requested on"><Input type="date" value={fields.requestedOn ?? ""} onChange={(event) => set("requestedOn", event.target.value)} /></Field><Field label="Request form"><Input value={fields.requestFormRef ?? ""} onChange={(event) => set("requestFormRef", event.target.value)} /></Field><Field label="Request reason"><Textarea value={fields.requestReason ?? ""} onChange={(event) => set("requestReason", event.target.value)} /></Field><Field label="Fee status"><select className={SELECT_CLASS} value={fields.feeStatus} onChange={(event) => set("feeStatus", event.target.value)}><option value="not_required">Not required</option><option value="pending">Pending</option><option value="paid">Paid</option></select></Field>{fields.feeStatus === "paid" ? <><Field label="Fee amount (minor unit)"><Input type="number" min={0} value={fields.feeAmount ?? ""} onChange={(event) => set("feeAmount", event.target.value)} /></Field><Field label="Fee evidence"><Input value={fields.feeEvidence ?? ""} onChange={(event) => set("feeEvidence", event.target.value)} /></Field></> : null}<Field label="Prior adjournments"><Input type="number" min={0} value={fields.priorAdjournments} onChange={(event) => set("priorAdjournments", event.target.value)} /></Field><Field label="Allowed-count candidate"><Input type="number" min={0} value={fields.allowedAdjournments} onChange={(event) => set("allowedAdjournments", event.target.value)} /></Field><Field label="Outcome"><select className={SELECT_CLASS} value={fields.adjournmentOutcome} onChange={(event) => set("adjournmentOutcome", event.target.value)}><option value="pending">Pending</option><option value="granted">Granted</option><option value="refused">Refused</option></select></Field><Field label="Rule version"><Input value={fields.ruleVersion ?? ""} onChange={(event) => set("ruleVersion", event.target.value)} /></Field><Field label="Policy confirmation"><Input value={fields.policyConfirmation ?? ""} onChange={(event) => set("policyConfirmation", event.target.value)} /></Field></div> : null}

      {action === "written_arguments_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{hearingField}<Field label="Filed on"><Input type="date" value={fields.filedOn ?? ""} onChange={(event) => set("filedOn", event.target.value)} /></Field><Field label="Filing reference"><Input value={fields.filingReference ?? ""} onChange={(event) => set("filingReference", event.target.value)} /></Field><Field label="Argument documents"><Input value={fields.argumentDocuments ?? ""} onChange={(event) => set("argumentDocuments", event.target.value)} placeholder="Comma separated" /></Field>{serviceFields}</div> : null}

      {action === "attendance_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{hearingField}<Field label="Appearance"><select className={SELECT_CLASS} value={fields.appearanceStatus} onChange={(event) => set("appearanceStatus", event.target.value)}><option value="attended">Attended</option><option value="unrepresented">Unrepresented</option><option value="nonappearance">Nonappearance</option></select></Field>{fields.appearanceStatus === "attended" ? <Field label="Attendee membership IDs"><Input value={fields.attendeeIds ?? ""} onChange={(event) => set("attendeeIds", event.target.value)} placeholder="Comma separated" /></Field> : null}<Field label="Attendance source"><Input value={fields.attendanceSource ?? ""} onChange={(event) => set("attendanceSource", event.target.value)} /></Field><Field label="Rule version"><Input value={fields.ruleVersion ?? ""} onChange={(event) => set("ruleVersion", event.target.value)} /></Field>{fields.appearanceStatus === "nonappearance" ? <><Field label="Consequence candidate"><Textarea value={fields.consequence ?? ""} onChange={(event) => set("consequence", event.target.value)} /></Field><Field label="Consequence confirmation"><Input value={fields.policyConfirmation ?? ""} onChange={(event) => set("policyConfirmation", event.target.value)} /></Field></> : null}</div> : null}

      {action === "security_for_costs_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="Direction reference"><Input value={fields.directionReference ?? ""} onChange={(event) => set("directionReference", event.target.value)} /></Field><Field label="Directed on"><Input type="date" value={fields.directedOn ?? ""} onChange={(event) => set("directedOn", event.target.value)} /></Field><Field label="Amount (minor unit)"><Input type="number" min={0} value={fields.amount ?? ""} onChange={(event) => set("amount", event.target.value)} /></Field><Field label="Enhancement amount"><Input type="number" min={0} value={fields.enhancementAmount} onChange={(event) => set("enhancementAmount", event.target.value)} /></Field><Field label="Due on"><Input type="date" value={fields.dueOn ?? ""} onChange={(event) => set("dueOn", event.target.value)} /></Field><Field label="Payment status"><select className={SELECT_CLASS} value={fields.paymentStatus} onChange={(event) => set("paymentStatus", event.target.value)}><option value="pending">Pending</option><option value="paid">Paid</option><option value="overdue">Overdue</option><option value="waived">Waived</option></select></Field>{fields.paymentStatus === "paid" ? <><Field label="Paid on"><Input type="date" value={fields.paidOn ?? ""} onChange={(event) => set("paidOn", event.target.value)} /></Field><Field label="Payment reference"><Input value={fields.paymentReference ?? ""} onChange={(event) => set("paymentReference", event.target.value)} /></Field></> : null}<Field label="Consequence candidate"><Textarea value={fields.consequence ?? ""} onChange={(event) => set("consequence", event.target.value)} /></Field><Field label="Rule version"><Input value={fields.ruleVersion ?? ""} onChange={(event) => set("ruleVersion", event.target.value)} /></Field></div> : null}

      {action === "disposition_review_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="Trigger event"><select className={SELECT_CLASS} value={selectedTriggerId} onChange={(event) => set("triggerEventId", event.target.value)}><option value="">Select order or stage outcome</option>{workspace.stage_events.map((event) => <option key={event.id} value={event.id}>{event.resulting_stage ?? event.event_kind} - {event.source_reference ?? event.id}</option>)}</select></Field><Field label="Outcome kind"><select className={SELECT_CLASS} value={fields.outcomeKind} onChange={(event) => set("outcomeKind", event.target.value)}><option value="dismissal">Dismissal</option><option value="abandonment">Abandonment</option><option value="withdrawal">Withdrawal</option><option value="settlement">Settlement</option><option value="final_decision">Final decision</option></select></Field><Field label="Affected scope IDs"><Input value={fields.affectedScopeIds ?? ""} onChange={(event) => set("affectedScopeIds", event.target.value)} placeholder="Comma separated" /></Field><Field label="Review status"><select className={SELECT_CLASS} value={fields.reviewStatus} onChange={(event) => set("reviewStatus", event.target.value)}><option value="pending">Pending</option><option value="confirmed">Confirmed</option><option value="not_applicable">Not applicable</option></select></Field><Field label="Recommended application disposition"><Textarea value={fields.recommendation ?? ""} onChange={(event) => set("recommendation", event.target.value)} /></Field><Field label="Review reference"><Input value={fields.reviewReference ?? ""} onChange={(event) => set("reviewReference", event.target.value)} /></Field></div> : null}

      {action === "madrid_designation_link_recorded" ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="International registration number"><Input value={fields.irNumber ?? ""} onChange={(event) => set("irNumber", event.target.value)} /></Field><Field label="WIPO reference"><Input value={fields.wipoReference ?? ""} onChange={(event) => set("wipoReference", event.target.value)} /></Field><Field label="India designation identifier"><Input value={fields.indiaDesignation ?? ""} onChange={(event) => set("indiaDesignation", event.target.value)} /></Field><Field label="Designation status"><Input value={fields.designationStatus ?? ""} onChange={(event) => set("designationStatus", event.target.value)} /></Field><Field label="Lifecycle source"><Input value={fields.lifecycleSource ?? ""} onChange={(event) => set("lifecycleSource", event.target.value)} /></Field></div> : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Field label="Evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} placeholder="Comma separated" /></Field><Field label="Document references"><Input value={documentRefs} onChange={(event) => setDocumentRefs(event.target.value)} placeholder="Comma separated" /></Field><Field label="Reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field><label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={acknowledgeBackdated} onChange={(event) => setAcknowledgeBackdated(event.target.checked)} /> Recalculation preview reviewed</label></div>
      <Button data-testid="ip-opposition-specialized-submit" type="submit" disabled={!commonReady || !detailReady || record.isPending}>{action === "translation_recorded" ? <Languages className="h-4 w-4" /> : action === "security_for_costs_recorded" ? <Scale className="h-4 w-4" /> : <ClipboardCheck className="h-4 w-4" />}Record specialized action</Button>
    </form>
  </section>;
}
