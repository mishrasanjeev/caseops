"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileCheck2, Plus, Save, ShieldAlert } from "lucide-react";
import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import {
  createIpPostRegistrationProceeding,
  fetchIpCoreRecords,
  fetchIpPostRegistrationWorkspace,
  recordIpPostRegistrationAction,
  saveIpPostRegistrationWorkspace,
  type IpDocket,
  type IpPostRegistrationActionKind,
  type IpPostRegistrationKind,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]";
const POST_REGISTRATION_KINDS: IpPostRegistrationKind[] = [
  "rectification",
  "cancellation",
  "non_use_removal",
];
const ACTIONS: IpPostRegistrationActionKind[] = [
  "stage_update",
  "parallel_proceeding_link",
  "interim_stay",
  "stay_lifted",
  "order_recorded",
  "closure",
  "disposition_candidate",
  "disposition_review",
];
const STAGES = [
  "petition_filed",
  "service_pending",
  "counterstatement_due",
  "counterstatement_filed",
  "claimant_evidence_due",
  "claimant_evidence_filed",
  "respondent_evidence_due",
  "respondent_evidence_filed",
  "reply_evidence_due",
  "reply_evidence_filed",
  "hearing_pending",
  "hearing_scheduled",
  "reserved_for_order",
  "decided",
  "compliance_pending",
  "appeal_pending",
];
const DISPOSITIONS: Record<
  IpPostRegistrationKind,
  Array<
    "rectify_registration" | "cancel_registration" | "remove_for_non_use" | "no_change"
  >
> = {
  rectification: ["rectify_registration", "no_change"],
  cancellation: ["cancel_registration", "no_change"],
  non_use_removal: ["remove_for_non_use", "no_change"],
};

function readable(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function refs(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {isValidElement(children)
        ? cloneElement(children as ReactElement<{ id?: string }>, { id })
        : children}
    </div>
  );
}

export function IpPostRegistrationWorkspace({
  docket,
  canWrite,
  canReview,
  currentMembershipId,
}: {
  docket: IpDocket;
  canWrite: boolean;
  canReview: boolean;
  currentMembershipId: string | null;
}) {
  const queryClient = useQueryClient();
  const core = useQuery({
    queryKey: ["ip", "core-records", docket.id],
    queryFn: () => fetchIpCoreRecords(docket.id),
  });
  const proceedings = useMemo(
    () =>
      (core.data?.proceedings ?? []).filter((row) =>
        POST_REGISTRATION_KINDS.includes(
          row.proceeding_kind as IpPostRegistrationKind,
        ),
      ),
    [core.data?.proceedings],
  );
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    if (!selectedId && proceedings[0]) setSelectedId(proceedings[0].id);
    if (selectedId && !proceedings.some((row) => row.id === selectedId)) {
      setSelectedId(proceedings[0]?.id ?? "");
    }
  }, [proceedings, selectedId]);

  const workspace = useQuery({
    queryKey: ["ip", "post-registration-workspace", docket.id, selectedId],
    queryFn: () =>
      fetchIpPostRegistrationWorkspace({
        docketId: docket.id,
        proceedingId: selectedId,
      }),
    enabled: Boolean(selectedId),
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["ip", "core-records", docket.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["ip", "post-registration-workspace", docket.id, selectedId],
      }),
    ]);
  };

  const [applicationId, setApplicationId] = useState("");
  const [proceedingKind, setProceedingKind] =
    useState<IpPostRegistrationKind>("rectification");
  const [side, setSide] = useState<"claimant" | "respondent">("claimant");
  const [number, setNumber] = useState("");
  const [numberSource, setNumberSource] = useState("registry record");
  const [office, setOffice] = useState("Trade Marks Registry Delhi");
  useEffect(() => {
    if (!applicationId && core.data?.applications[0]) {
      setApplicationId(core.data.applications[0].id);
    }
  }, [applicationId, core.data?.applications]);
  const create = useMutation({
    mutationFn: createIpPostRegistrationProceeding,
    onSuccess: async (row) => {
      setSelectedId(row.id);
      setNumber("");
      toast.success(`${readable(row.proceeding_kind)} proceeding created.`);
      await refresh();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not create the proceeding.")),
  });

  const profile = workspace.data?.profile;
  const [legalBasis, setLegalBasis] = useState("");
  const [targetRight, setTargetRight] = useState("");
  const [applicantName, setApplicantName] = useState("");
  const [respondentName, setRespondentName] = useState("");
  const [classNumber, setClassNumber] = useState("9");
  const [scope, setScope] = useState("");
  const [grounds, setGrounds] = useState("");
  const [forum, setForum] = useState("Trade Marks Registry Delhi");
  const [formKey, setFormKey] = useState("TM-O");
  const [feeStatus, setFeeStatus] = useState<
    "required" | "paid" | "not_required" | "manual_review"
  >("manual_review");
  const [feeReference, setFeeReference] = useState("");
  const [serviceStatus, setServiceStatus] = useState<
    "not_started" | "prepared" | "served" | "not_required"
  >("not_started");
  const [serviceReference, setServiceReference] = useState("");
  const [ruleVersion, setRuleVersion] = useState("lawyer-reviewed-v1");
  const [authorityReference, setAuthorityReference] = useState("");
  const [legalSource, setLegalSource] = useState("");
  const [mutatis, setMutatis] = useState(false);
  const [mappedFrom, setMappedFrom] = useState("");
  const [mappedProvisions, setMappedProvisions] = useState("");
  const [excludedProvisions, setExcludedProvisions] = useState("");
  const [mappingConfirmation, setMappingConfirmation] = useState("");
  const [profileSource, setProfileSource] = useState("");
  const [profileDocument, setProfileDocument] = useState("");
  const [profileReason, setProfileReason] = useState(
    "Counsel confirmed the post-registration profile from the source record.",
  );
  useEffect(() => {
    if (!profile) return;
    setLegalBasis(profile.legal_basis);
    setTargetRight(profile.target_right_reference);
    setApplicantName(profile.applicant_name);
    setRespondentName(profile.respondent_name);
    setClassNumber(String(profile.challenged_scope[0]?.class_number ?? 9));
    setScope(profile.challenged_scope[0]?.goods_services_segment ?? "");
    setGrounds(profile.grounds.join("\n"));
    setForum(profile.forum);
    setFormKey(profile.form_key);
    setFeeStatus(profile.fee_status);
    setFeeReference(profile.fee_reference ?? "");
    setServiceStatus(profile.service_status);
    setServiceReference(profile.service_reference ?? "");
    setRuleVersion(profile.rule_map.template_version);
    setAuthorityReference(profile.rule_map.authority_reference);
    setLegalSource(profile.rule_map.source_reference);
    setMutatis(profile.rule_map.mutatis_mutandis);
    setMappedFrom(profile.rule_map.mapped_from_rule ?? "");
    setMappedProvisions(profile.rule_map.mapped_provisions.join(", "));
    setExcludedProvisions(profile.rule_map.excluded_provisions.join(", "));
    setMappingConfirmation(profile.rule_map.lawyer_confirmation ?? "");
  }, [profile]);
  const save = useMutation({
    mutationFn: saveIpPostRegistrationWorkspace,
    onSuccess: async () => {
      toast.success("Post-registration profile confirmed.");
      await refresh();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save the profile.")),
  });

  const [actionKind, setActionKind] =
    useState<IpPostRegistrationActionKind>("stage_update");
  const [stage, setStage] = useState("petition_filed");
  const [actionSource, setActionSource] = useState("");
  const [actionDocument, setActionDocument] = useState("");
  const [actionAuthority, setActionAuthority] = useState("");
  const [parallelId, setParallelId] = useState("");
  const [legalEffect, setLegalEffect] = useState("");
  const [legalEffectDate, setLegalEffectDate] = useState("");
  const [candidateDisposition, setCandidateDisposition] = useState<
    | "rectify_registration"
    | "cancel_registration"
    | "remove_for_non_use"
    | "no_change"
  >("rectify_registration");
  const [candidateEventId, setCandidateEventId] = useState("");
  const [reviewDecision, setReviewDecision] = useState<"approved" | "rejected">(
    "approved",
  );
  const [authorizedConfirmation, setAuthorizedConfirmation] = useState("");
  const [actionReason, setActionReason] = useState(
    "Counsel reviewed and confirmed the sourced procedural action.",
  );
  const candidates = (workspace.data?.action_events ?? []).filter(
    (row) => row.payload_json.action_kind === "disposition_candidate",
  );
  const selectedKind = workspace.data?.proceeding
    .proceeding_kind as IpPostRegistrationKind | undefined;
  const availableDispositions = selectedKind
    ? DISPOSITIONS[selectedKind]
    : DISPOSITIONS.rectification;
  useEffect(() => {
    if (!availableDispositions.includes(candidateDisposition)) {
      setCandidateDisposition(availableDispositions[0]);
    }
  }, [availableDispositions, candidateDisposition]);
  const action = useMutation({
    mutationFn: recordIpPostRegistrationAction,
    onSuccess: async () => {
      toast.success("Post-registration action recorded.");
      await refresh();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not record the action.")),
  });

  return (
    <Card
      className="min-w-0 xl:col-span-2"
      data-testid="ip-post-registration-workspace"
    >
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle as="h3">Rectification, cancellation and non-use</CardTitle>
          {workspace.data?.active_stay ? (
            <Badge tone="warning">
              <ShieldAlert className="h-3.5 w-3.5" /> Interim stay
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <form
          data-testid="ip-post-registration-create-form"
          className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!applicationId) return;
            create.mutate({
              docketId: docket.id,
              applicationId,
              proceedingKind,
              side,
              office,
              jurisdiction: "IN",
              originKind: "registry_event",
              proceedingNumber: number || null,
              identifierSource: numberSource,
              identifierEffectiveFrom: new Date().toISOString().slice(0, 10),
            });
          }}
        >
          <Field label="Target application">
            <select
              className={SELECT_CLASS}
              value={applicationId}
              onChange={(event) => setApplicationId(event.target.value)}
            >
              {(core.data?.applications ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.office} · {row.filing_phase}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Proceeding type">
            <select
              className={SELECT_CLASS}
              value={proceedingKind}
              onChange={(event) =>
                setProceedingKind(event.target.value as IpPostRegistrationKind)
              }
            >
              {POST_REGISTRATION_KINDS.map((value) => (
                <option key={value} value={value}>
                  {readable(value)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Represented side">
            <select
              className={SELECT_CLASS}
              value={side}
              onChange={(event) => setSide(event.target.value as typeof side)}
            >
              <option value="claimant">Claimant</option>
              <option value="respondent">Respondent</option>
            </select>
          </Field>
          <Field label="Office">
            <Input
              value={office}
              onChange={(event) => setOffice(event.target.value)}
            />
          </Field>
          <Field label="Proceeding number">
            <Input
              value={number}
              onChange={(event) => setNumber(event.target.value)}
              placeholder="Pending allocation when blank"
            />
          </Field>
          <Field label="Number source">
            <Input
              value={numberSource}
              onChange={(event) => setNumberSource(event.target.value)}
            />
          </Field>
          <div className="flex items-end">
            <Button
              className="w-full"
              type="submit"
              disabled={!canWrite || !applicationId || create.isPending}
            >
              <Plus className="h-4 w-4" /> Create proceeding
            </Button>
          </div>
        </form>

        {proceedings.length ? (
          <Field label="Selected proceeding">
            <select
              className={SELECT_CLASS}
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {proceedings.map((row) => (
                <option key={row.id} value={row.id}>
                  {readable(row.proceeding_kind)} · {row.stage}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {workspace.isError ? (
          <QueryErrorState
            error={workspace.error}
            onRetry={() => workspace.refetch()}
          />
        ) : null}
        {workspace.data ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge
                tone={
                  workspace.data.ready_for_stage_progression
                    ? "success"
                    : "warning"
                }
              >
                {workspace.data.ready_for_stage_progression
                  ? "Profile ready"
                  : "Profile incomplete"}
              </Badge>
              <Badge>
                {readable(workspace.data.proceeding.proceeding_kind)}
              </Badge>
              <Badge>{readable(workspace.data.proceeding.stage)}</Badge>
              {workspace.data.identifiers.map((row) => (
                <Badge key={row.id}>{row.raw_value}</Badge>
              ))}
            </div>

            <form
              data-testid="ip-post-registration-profile-form"
              className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-4 md:grid-cols-2 xl:grid-cols-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!currentMembershipId) return;
                const kind = workspace.data.proceeding
                  .proceeding_kind as IpPostRegistrationKind;
                save.mutate({
                  docketId: docket.id,
                  proceedingId: workspace.data.proceeding.id,
                  lifecycleVersion: docket.lifecycle_version,
                  proceedingVersion: workspace.data.proceeding.version,
                  expectedProfileEventId:
                    workspace.data.profile_event?.id ?? null,
                  effectiveAt: new Date().toISOString(),
                  responsibleMembershipId: currentMembershipId,
                  source: "manual",
                  sourceReference: profileSource,
                  reason: profileReason,
                  documentRefs: refs(profileDocument),
                  profile: {
                    proceeding_type: kind,
                    legal_basis: legalBasis,
                    target_right_reference: targetRight,
                    applicant_name: applicantName,
                    respondent_name: respondentName,
                    challenged_scope: [
                      {
                        class_number: Number(classNumber),
                        goods_services_segment: scope,
                      },
                    ],
                    grounds: grounds
                      .split("\n")
                      .map((row) => row.trim())
                      .filter(Boolean),
                    forum,
                    form_key: formKey,
                    fee_status: feeStatus,
                    fee_reference: feeReference || null,
                    service_status: serviceStatus,
                    service_reference: serviceReference || null,
                    rule_map: {
                      template_key: `post-registration/${kind}`,
                      template_version: ruleVersion,
                      authority_reference: authorityReference,
                      source_reference: legalSource,
                      mutatis_mutandis: mutatis,
                      mapped_from_rule: mutatis ? mappedFrom : null,
                      mapped_provisions: mutatis ? refs(mappedProvisions) : [],
                      excluded_provisions: mutatis
                        ? refs(excludedProvisions)
                        : [],
                      lawyer_confirmation: mutatis ? mappingConfirmation : null,
                    },
                  },
                });
              }}
            >
              <div className="md:col-span-2 xl:col-span-4">
                <h4 className="flex items-center gap-2 font-semibold">
                  <FileCheck2 className="h-4 w-4" /> Proceeding profile
                </h4>
              </div>
              <Field label="Legal basis">
                <Textarea
                  value={legalBasis}
                  onChange={(event) => setLegalBasis(event.target.value)}
                />
              </Field>
              <Field label="Target right">
                <Input
                  value={targetRight}
                  onChange={(event) => setTargetRight(event.target.value)}
                />
              </Field>
              <Field label="Applicant">
                <Input
                  value={applicantName}
                  onChange={(event) => setApplicantName(event.target.value)}
                />
              </Field>
              <Field label="Respondent">
                <Input
                  value={respondentName}
                  onChange={(event) => setRespondentName(event.target.value)}
                />
              </Field>
              <Field label="Class">
                <Input
                  type="number"
                  min={1}
                  max={45}
                  value={classNumber}
                  onChange={(event) => setClassNumber(event.target.value)}
                />
              </Field>
              <Field label="Challenged scope">
                <Textarea
                  value={scope}
                  onChange={(event) => setScope(event.target.value)}
                />
              </Field>
              <Field label="Grounds">
                <Textarea
                  value={grounds}
                  onChange={(event) => setGrounds(event.target.value)}
                />
              </Field>
              <Field label="Forum">
                <Input
                  value={forum}
                  onChange={(event) => setForum(event.target.value)}
                />
              </Field>
              <Field label="Form">
                <Input
                  value={formKey}
                  onChange={(event) => setFormKey(event.target.value)}
                />
              </Field>
              <Field label="Fee status">
                <select
                  className={SELECT_CLASS}
                  value={feeStatus}
                  onChange={(event) =>
                    setFeeStatus(event.target.value as typeof feeStatus)
                  }
                >
                  {["required", "paid", "not_required", "manual_review"].map(
                    (value) => (
                      <option key={value} value={value}>
                        {readable(value)}
                      </option>
                    ),
                  )}
                </select>
              </Field>
              <Field label="Fee reference">
                <Input
                  value={feeReference}
                  onChange={(event) => setFeeReference(event.target.value)}
                />
              </Field>
              <Field label="Service status">
                <select
                  className={SELECT_CLASS}
                  value={serviceStatus}
                  onChange={(event) =>
                    setServiceStatus(event.target.value as typeof serviceStatus)
                  }
                >
                  {["not_started", "prepared", "served", "not_required"].map(
                    (value) => (
                      <option key={value} value={value}>
                        {readable(value)}
                      </option>
                    ),
                  )}
                </select>
              </Field>
              <Field label="Service reference">
                <Input
                  value={serviceReference}
                  onChange={(event) => setServiceReference(event.target.value)}
                />
              </Field>
              <Field label="Rule version">
                <Input
                  value={ruleVersion}
                  onChange={(event) => setRuleVersion(event.target.value)}
                />
              </Field>
              <Field label="Legal authority">
                <Input
                  value={authorityReference}
                  onChange={(event) =>
                    setAuthorityReference(event.target.value)
                  }
                />
              </Field>
              <Field label="Legal source">
                <Input
                  value={legalSource}
                  onChange={(event) => setLegalSource(event.target.value)}
                />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={mutatis}
                  onChange={(event) => setMutatis(event.target.checked)}
                />{" "}
                Mutatis mutandis mapping
              </label>
              {mutatis ? (
                <>
                  <Field label="Mapped from rule">
                    <Input
                      value={mappedFrom}
                      onChange={(event) => setMappedFrom(event.target.value)}
                    />
                  </Field>
                  <Field label="Mapped provisions">
                    <Input
                      value={mappedProvisions}
                      onChange={(event) =>
                        setMappedProvisions(event.target.value)
                      }
                    />
                  </Field>
                  <Field label="Excluded provisions">
                    <Input
                      value={excludedProvisions}
                      onChange={(event) =>
                        setExcludedProvisions(event.target.value)
                      }
                    />
                  </Field>
                  <Field label="Lawyer confirmation">
                    <Textarea
                      value={mappingConfirmation}
                      onChange={(event) =>
                        setMappingConfirmation(event.target.value)
                      }
                    />
                  </Field>
                </>
              ) : null}
              <Field label="Record source">
                <Input
                  value={profileSource}
                  onChange={(event) => setProfileSource(event.target.value)}
                />
              </Field>
              <Field label="Source documents">
                <Input
                  value={profileDocument}
                  onChange={(event) => setProfileDocument(event.target.value)}
                />
              </Field>
              <Field label="Reason">
                <Textarea
                  value={profileReason}
                  onChange={(event) => setProfileReason(event.target.value)}
                />
              </Field>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  type="submit"
                  disabled={
                    !canReview ||
                    !currentMembershipId ||
                    !profileSource.trim() ||
                    !profileDocument.trim() ||
                    save.isPending
                  }
                >
                  <Save className="h-4 w-4" /> Confirm profile
                </Button>
              </div>
            </form>

            <form
              data-testid="ip-post-registration-action-form"
              className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-4 md:grid-cols-2 xl:grid-cols-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!currentMembershipId) return;
                action.mutate({
                  docketId: docket.id,
                  proceedingId: workspace.data.proceeding.id,
                  lifecycleVersion: docket.lifecycle_version,
                  proceedingVersion: workspace.data.proceeding.version,
                  actionKind,
                  effectiveAt: new Date().toISOString(),
                  responsibleMembershipId: currentMembershipId,
                  source: "manual",
                  sourceReference: actionSource,
                  reason: actionReason,
                  documentRefs: refs(actionDocument),
                  stage:
                    actionKind === "stage_update" || actionKind === "closure"
                      ? stage
                      : null,
                  authorityReference: actionAuthority || null,
                  parallelProceedingId: parallelId || null,
                  legalEffect: legalEffect || null,
                  legalEffectiveDate: legalEffectDate || null,
                  candidateDisposition:
                    actionKind === "disposition_candidate"
                      ? candidateDisposition
                      : null,
                  candidateEventId: candidateEventId || null,
                  reviewDecision:
                    actionKind === "disposition_review" ? reviewDecision : null,
                  authorizedConfirmation: authorizedConfirmation || null,
                });
              }}
            >
              <div className="md:col-span-2 xl:col-span-4">
                <h4 className="flex items-center gap-2 font-semibold">
                  <ArrowRight className="h-4 w-4" /> Procedural action
                </h4>
              </div>
              <Field label="Action">
                <select
                  className={SELECT_CLASS}
                  value={actionKind}
                  onChange={(event) => {
                    const value = event.target
                      .value as IpPostRegistrationActionKind;
                    setActionKind(value);
                    if (value === "closure") setStage("settled");
                  }}
                >
                  {ACTIONS.map((value) => (
                    <option key={value} value={value}>
                      {readable(value)}
                    </option>
                  ))}
                </select>
              </Field>
              {actionKind === "stage_update" || actionKind === "closure" ? (
                <Field label="Stage">
                  <select
                    className={SELECT_CLASS}
                    value={stage}
                    onChange={(event) => setStage(event.target.value)}
                  >
                    {(actionKind === "closure"
                      ? ["withdrawn", "settled", "closed"]
                      : STAGES
                    ).map((value) => (
                      <option key={value} value={value}>
                        {readable(value)}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : null}
              {actionKind === "parallel_proceeding_link" ? (
                <Field label="Parallel proceeding">
                  <select
                    className={SELECT_CLASS}
                    value={parallelId}
                    onChange={(event) => setParallelId(event.target.value)}
                  >
                    <option value="">Select</option>
                    {(core.data?.proceedings ?? [])
                      .filter((row) => row.id !== selectedId)
                      .map((row) => (
                        <option key={row.id} value={row.id}>
                          {readable(row.proceeding_kind)} · {row.stage}
                        </option>
                      ))}
                  </select>
                </Field>
              ) : null}
              {actionKind === "disposition_candidate" ? (
                <Field label="Candidate disposition">
                  <select
                    className={SELECT_CLASS}
                    value={candidateDisposition}
                    onChange={(event) =>
                      setCandidateDisposition(
                        event.target.value as typeof candidateDisposition,
                      )
                    }
                  >
                    {availableDispositions.map((value) => (
                      <option key={value} value={value}>
                        {readable(value)}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : null}
              {actionKind === "disposition_review" ? (
                <>
                  <Field label="Disposition candidate">
                    <select
                      className={SELECT_CLASS}
                      value={candidateEventId}
                      onChange={(event) =>
                        setCandidateEventId(event.target.value)
                      }
                    >
                      <option value="">Select</option>
                      {candidates.map((row) => (
                        <option key={row.id} value={row.id}>
                          {String(
                            row.payload_json.candidate_disposition ?? row.id,
                          )}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Review decision">
                    <select
                      className={SELECT_CLASS}
                      value={reviewDecision}
                      onChange={(event) =>
                        setReviewDecision(
                          event.target.value as typeof reviewDecision,
                        )
                      }
                    >
                      <option value="approved">Approved</option>
                      <option value="rejected">Rejected</option>
                    </select>
                  </Field>
                </>
              ) : null}
              <Field label="Source reference">
                <Input
                  value={actionSource}
                  onChange={(event) => setActionSource(event.target.value)}
                />
              </Field>
              <Field label="Source documents">
                <Input
                  value={actionDocument}
                  onChange={(event) => setActionDocument(event.target.value)}
                />
              </Field>
              <Field label="Authority reference">
                <Input
                  value={actionAuthority}
                  onChange={(event) => setActionAuthority(event.target.value)}
                />
              </Field>
              {actionKind === "closure" ||
              actionKind === "disposition_candidate" ? (
                <Field label="Legal effect">
                  <Textarea
                    value={legalEffect}
                    onChange={(event) => setLegalEffect(event.target.value)}
                  />
                </Field>
              ) : null}
              {actionKind === "closure" ? (
                <Field label="Legal effect date">
                  <Input
                    type="date"
                    value={legalEffectDate}
                    onChange={(event) => setLegalEffectDate(event.target.value)}
                  />
                </Field>
              ) : null}
              {actionKind === "closure" ||
              actionKind === "disposition_review" ? (
                <Field label="Authorized confirmation">
                  <Textarea
                    value={authorizedConfirmation}
                    onChange={(event) =>
                      setAuthorizedConfirmation(event.target.value)
                    }
                  />
                </Field>
              ) : null}
              <Field label="Reason">
                <Textarea
                  value={actionReason}
                  onChange={(event) => setActionReason(event.target.value)}
                />
              </Field>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  type="submit"
                  disabled={
                    !canReview ||
                    !currentMembershipId ||
                    !workspace.data.ready_for_stage_progression ||
                    !actionSource.trim() ||
                    action.isPending
                  }
                >
                  <ArrowRight className="h-4 w-4" /> Record action
                </Button>
              </div>
            </form>

            {workspace.data.action_events.length ? (
              <section className="border-t border-[var(--color-line)] pt-4">
                <h4 className="font-semibold">Proceeding history</h4>
                <ol className="mt-2 space-y-2">
                  {[...workspace.data.action_events].reverse().map((row) => (
                    <li
                      key={row.id}
                      className="rounded-md bg-[var(--color-bg-2)] p-3 text-sm"
                    >
                      <strong>
                        {readable(
                          String(
                            row.payload_json.action_kind ?? row.event_kind,
                          ),
                        )}
                      </strong>
                      <div className="break-words text-xs text-[var(--color-mute)]">
                        {new Date(row.effective_at).toLocaleString()} ·{" "}
                        {row.reason}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
