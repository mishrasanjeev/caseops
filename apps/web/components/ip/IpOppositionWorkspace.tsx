"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ExternalLink, Plus, Save, Scale, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { IpOppositionApplicantWorkflow } from "@/components/ip/IpOppositionApplicantWorkflow";
import { IpOppositionOpponentWorkflow } from "@/components/ip/IpOppositionOpponentWorkflow";
import { IpOppositionSharedWorkflow } from "@/components/ip/IpOppositionSharedWorkflow";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createIpOppositionProceeding,
  fetchIpCoreRecords,
  fetchIpOppositionWorkspace,
  saveIpOppositionWorkspace,
  transitionIpOppositionStage,
  type IpDocket,
  type IpOppositionGround,
  type IpOppositionProfile,
} from "@/lib/api/endpoints";

const TODAY = new Date().toISOString().slice(0, 10);
const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

type PartyDraft = {
  role: "applicant" | "opponent" | "agent" | "counsel";
  party_name: string;
  source: string;
};
type ScopeDraft = { class_number: number; goods_services_segment: string };
type RightDraft = IpOppositionProfile["relied_on_rights"][number];

const EMPTY_PARTIES: PartyDraft[] = [
  { role: "applicant", party_name: "", source: "opposition notice" },
  { role: "opponent", party_name: "", source: "opposition notice" },
];
const EMPTY_GROUND: IpOppositionGround = {
  category: "earlier_mark",
  lawyer_detail: "",
  classification_source: "manual",
};
const EMPTY_SCOPE: ScopeDraft = { class_number: 1, goods_services_segment: "" };
const EMPTY_RIGHT: RightDraft = {
  mark_or_right: "",
  jurisdiction: "IN",
  identifier: null,
  status: "registered",
  owner: "",
  goods_services: "",
  reputation_claim: null,
  use_claim: null,
  evidence_refs: [],
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Label className="block min-w-0 space-y-1.5">
      <span className="block">{label}</span>
      {children}
    </Label>
  );
}

function splitRefs(value: string): string[] {
  return value.split(",").map((row) => row.trim()).filter(Boolean);
}

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

function verifiedHttpSource(reference: string | null | undefined): string | null {
  if (!reference) return null;
  try {
    const parsed = new URL(reference);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? reference : null;
  } catch {
    return null;
  }
}

export function IpOppositionWorkspace({
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
  const oppositions = useMemo(
    () => (core.data?.proceedings ?? []).filter((row) => row.proceeding_kind === "opposition"),
    [core.data?.proceedings],
  );
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    if (!selectedId && oppositions[0]) setSelectedId(oppositions[0].id);
    if (selectedId && !oppositions.some((row) => row.id === selectedId)) {
      setSelectedId(oppositions[0]?.id ?? "");
    }
  }, [oppositions, selectedId]);

  const workspace = useQuery({
    queryKey: ["ip", "opposition-workspace", docket.id, selectedId],
    queryFn: () => fetchIpOppositionWorkspace({ docketId: docket.id, proceedingId: selectedId }),
    enabled: Boolean(selectedId),
  });

  const [applicationId, setApplicationId] = useState("");
  const [side, setSide] = useState<"applicant" | "opponent">("applicant");
  const [originKind, setOriginKind] = useState<
    "linked_application" | "registry_event" | "watch_hit" | "manual_intake"
  >("registry_event");
  const [office, setOffice] = useState("Trade Marks Registry Delhi");
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [oppositionNumber, setOppositionNumber] = useState("");
  const [numberSource, setNumberSource] = useState("registry notice");

  useEffect(() => {
    if (!applicationId && core.data?.applications[0]) {
      setApplicationId(core.data.applications[0].id);
    }
  }, [applicationId, core.data?.applications]);

  const refreshCore = () => queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] });
  const refreshWorkspace = () => queryClient.invalidateQueries({ queryKey: ["ip", "opposition-workspace", docket.id, selectedId] });
  const refreshApplicantWorkflow = () => queryClient.invalidateQueries({ queryKey: ["ip", "opposition-applicant-workflow", docket.id, selectedId] });
  const refreshOpponentWorkflow = () => queryClient.invalidateQueries({ queryKey: ["ip", "opposition-opponent-workflow", docket.id, selectedId] });
  const refreshSharedWorkflow = () => queryClient.invalidateQueries({ queryKey: ["ip", "opposition-shared-workflow", docket.id, selectedId] });
  const create = useMutation({
    mutationFn: createIpOppositionProceeding,
    onSuccess: async (row) => {
      setSelectedId(row.id);
      setOppositionNumber("");
      toast.success("Opposition proceeding created.");
      await refreshCore();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the opposition.")),
  });

  const profile = workspace.data?.profile;
  const [ruleVersion, setRuleVersion] = useState("");
  const [forum, setForum] = useState("");
  const [noticeRef, setNoticeRef] = useState("");
  const [noticeDocumentRef, setNoticeDocumentRef] = useState("");
  const [profileSource, setProfileSource] = useState<"manual" | "registry" | "integration" | "system">("manual");
  const [profileSourceRef, setProfileSourceRef] = useState("");
  const [profileReason, setProfileReason] = useState("Lawyer confirmed the opposition profile from the source record.");
  const [instructionState, setInstructionState] = useState<"pending" | "confirmed" | "not_required">("pending");
  const [instructionRef, setInstructionRef] = useState("");
  const [limitationDate, setLimitationDate] = useState("");
  const [parties, setParties] = useState<PartyDraft[]>(EMPTY_PARTIES);
  const [grounds, setGrounds] = useState<IpOppositionGround[]>([EMPTY_GROUND]);
  const [scope, setScope] = useState<ScopeDraft[]>([EMPTY_SCOPE]);
  const [rights, setRights] = useState<RightDraft[]>([]);
  const [serviceMethod, setServiceMethod] = useState("");
  const [serviceDestination, setServiceDestination] = useState("");
  const [servedOn, setServedOn] = useState("");
  const [serviceEvidence, setServiceEvidence] = useState("");
  const [startsResponse, setStartsResponse] = useState(true);
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [documentRefs, setDocumentRefs] = useState("");

  useEffect(() => {
    if (!workspace.data) return;
    const current = workspace.data.profile;
    setRuleVersion(current?.applicable_rule_version ?? "");
    setForum(current?.forum ?? workspace.data.proceeding.office);
    setNoticeRef(current?.source_notice_reference ?? "");
    setNoticeDocumentRef(current?.source_notice_document_ref ?? "");
    setInstructionState(current?.client_instruction_state ?? (workspace.data.proceeding.side === "applicant" ? "not_required" : "pending"));
    setInstructionRef(current?.client_instruction_reference ?? "");
    setLimitationDate(current?.limitation_date ?? "");
    setParties(workspace.data.parties.length
      ? workspace.data.parties.map(({ role, party_name, source }) => ({ role, party_name, source }))
      : EMPTY_PARTIES);
    setGrounds(current?.grounds.length ? current.grounds : [EMPTY_GROUND]);
    setScope(current?.challenged_scope.length ? current.challenged_scope : [EMPTY_SCOPE]);
    setRights(current?.relied_on_rights ?? []);
    setServiceMethod(current?.service?.method ?? "");
    setServiceDestination(current?.service?.destination ?? "");
    setServedOn(current?.service?.served_on ?? "");
    setServiceEvidence(current?.service?.evidence_refs.join(", ") ?? "");
    setStartsResponse(current?.service?.starts_response_period ?? true);
    setEvidenceRefs(workspace.data.profile_event?.evidence_refs_json.join(", ") ?? "");
    setDocumentRefs(workspace.data.profile_event?.document_refs_json.join(", ") ?? "");
  }, [workspace.data]);

  const saveInput = workspace.data && currentMembershipId ? {
    docketId: docket.id,
    proceedingId: workspace.data.proceeding.id,
    lifecycleVersion: docket.lifecycle_version,
    proceedingVersion: workspace.data.proceeding.version,
    expectedProfileEventId: workspace.data.profile_event?.id ?? null,
    source: profileSource,
    sourceReference: profileSourceRef || null,
    sourceNoticeReference: noticeRef || null,
    sourceNoticeDocumentRef: noticeDocumentRef || null,
    effectiveAt: new Date().toISOString(),
    responsibleMembershipId: currentMembershipId,
    reason: profileReason,
    applicableRuleVersion: ruleVersion,
    forum,
    clientInstructionState: instructionState,
    clientInstructionReference: instructionRef || null,
    limitationDate: limitationDate || null,
    parties: parties.filter((row) => row.party_name.trim()).map((row) => ({ ...row, party_name: row.party_name.trim(), source: row.source.trim() })),
    grounds: grounds.filter((row) => row.lawyer_detail.trim()),
    challengedScope: scope.filter((row) => row.goods_services_segment.trim()),
    reliedOnRights: rights.filter((row) => row.mark_or_right.trim()),
    service: serviceMethod.trim() && serviceDestination.trim() && servedOn && serviceEvidence.trim()
      ? {
          method: serviceMethod.trim(),
          destination: serviceDestination.trim(),
          served_on: servedOn,
          acknowledgement: null,
          defect: null,
          reservice_on: null,
          starts_response_period: startsResponse,
          evidence_refs: splitRefs(serviceEvidence),
        }
      : null,
    evidenceRefs: splitRefs(evidenceRefs),
    documentRefs: splitRefs(documentRefs),
  } : null;
  const save = useMutation({
    mutationFn: saveIpOppositionWorkspace,
    onSuccess: async () => {
      toast.success("Lawyer-confirmed opposition profile saved.");
      await refreshWorkspace();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save the opposition profile.")),
  });

  const [toStage, setToStage] = useState("notice_filed");
  const [transitionKind, setTransitionKind] = useState<"normal" | "skipped" | "waived" | "extended" | "superseded">("normal");
  const [transitionReason, setTransitionReason] = useState("");
  const [transitionSourceRef, setTransitionSourceRef] = useState("");
  const [authorityRef, setAuthorityRef] = useState("");
  const [transitionEvidence, setTransitionEvidence] = useState("");
  const [outcome, setOutcome] = useState("");
  const [outcomeDate, setOutcomeDate] = useState("");
  const [authorizedConfirmation, setAuthorizedConfirmation] = useState("");
  const transitionInput = workspace.data && currentMembershipId ? {
    docketId: docket.id,
    proceedingId: workspace.data.proceeding.id,
    lifecycleVersion: docket.lifecycle_version,
    proceedingVersion: workspace.data.proceeding.version,
    toStage,
    transitionKind,
    source: "manual" as const,
    sourceReference: transitionSourceRef || null,
    effectiveAt: new Date().toISOString(),
    responsibleMembershipId: currentMembershipId,
    reason: transitionReason,
    authorityReference: authorityRef || null,
    evidenceRefs: splitRefs(transitionEvidence),
    outcome: outcome || null,
    outcomeEffectiveDate: outcomeDate || null,
    authorizedConfirmation: authorizedConfirmation || null,
  } : null;
  const transition = useMutation({
    mutationFn: transitionIpOppositionStage,
    onSuccess: async () => {
      toast.success("Opposition stage updated.");
      setTransitionReason("");
      await Promise.all([
        refreshCore(),
        refreshWorkspace(),
        refreshApplicantWorkflow(),
        refreshOpponentWorkflow(),
        refreshSharedWorkflow(),
      ]);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update the opposition stage.")),
  });

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-opposition-workspace">
      <CardHeader>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <CardTitle as="h3">Trademark opposition</CardTitle>
          {workspace.data ? <Badge tone={workspace.data.ready_for_stage_progression ? "success" : "warning"}>{workspace.data.ready_for_stage_progression ? "Ready" : "Incomplete"}</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        {core.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {core.isError ? <QueryErrorState error={core.error} title="Could not load opposition records" onRetry={() => core.refetch()} /> : null}

        {oppositions.length ? (
          <Field label="Opposition proceeding">
            <select className={SELECT_CLASS} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
              {oppositions.map((row) => <option key={row.id} value={row.id}>{row.side} · {readable(row.stage)} · {row.office}</option>)}
            </select>
          </Field>
        ) : null}

        {canWrite && core.data?.applications.length ? (
          <form className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); create.mutate({ docketId: docket.id, applicationId, side, office, jurisdiction, originKind, oppositionNumber: oppositionNumber || null, identifierSource: numberSource, identifierEffectiveFrom: TODAY }); }}>
            <Field label="Trademark application"><select className={SELECT_CLASS} value={applicationId} onChange={(event) => setApplicationId(event.target.value)}>{core.data.applications.map((row) => <option key={row.id} value={row.id}>{core.data.identifiers.find((id) => id.application_id === row.id && id.identifier_kind === "application")?.raw_value ?? "Application number pending"} · {row.office}</option>)}</select></Field>
            <fieldset className="block min-w-0 space-y-1.5">
              <legend className="text-sm font-medium">Represented side</legend>
              <div className="grid h-10 grid-cols-2 overflow-hidden rounded-md border border-[var(--color-line)]">
                <button
                  type="button"
                  aria-pressed={side === "applicant"}
                  className={side === "applicant" ? "bg-[var(--color-primary)] text-white" : "bg-white"}
                  onClick={() => setSide("applicant")}
                >
                  Applicant
                </button>
                <button
                  type="button"
                  aria-pressed={side === "opponent"}
                  className={side === "opponent" ? "bg-[var(--color-primary)] text-white" : "bg-white"}
                  onClick={() => setSide("opponent")}
                >
                  Opponent
                </button>
              </div>
            </fieldset>
            <Field label="Intake source"><select className={SELECT_CLASS} value={originKind} onChange={(event) => setOriginKind(event.target.value as typeof originKind)}><option value="registry_event">Registry event</option><option value="linked_application">Linked application</option><option value="watch_hit">Watch hit</option><option value="manual_intake">Manual intake</option></select></Field>
            <Field label="Opposition number"><Input value={oppositionNumber} onChange={(event) => setOppositionNumber(event.target.value)} placeholder="Pending allocation" /></Field>
            <Field label="Registry office"><Input value={office} onChange={(event) => setOffice(event.target.value)} /></Field>
            <Field label="Jurisdiction"><Input value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)} /></Field>
            <Field label="Number source"><Input value={numberSource} onChange={(event) => setNumberSource(event.target.value)} /></Field>
            <div className="flex items-end"><Button className="w-full" type="submit" disabled={!applicationId || !office.trim() || !jurisdiction.trim() || create.isPending}><Plus className="h-4 w-4" /> Create opposition</Button></div>
          </form>
        ) : null}

        {workspace.isPending ? <Skeleton className="h-80 w-full" /> : null}
        {workspace.isError ? <QueryErrorState error={workspace.error} title="Could not load the opposition workspace" onRetry={() => workspace.refetch()} /> : null}
        {workspace.data ? (
          <>
            <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3"><div className="text-xs text-[var(--color-mute)]">Application number</div><div className="break-all font-mono text-sm font-semibold">{workspace.data.application_identifiers.map((row) => row.raw_value).join(", ") || "Pending"}</div></div>
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3"><div className="text-xs text-[var(--color-mute)]">Opposition number</div><div className="break-all font-mono text-sm font-semibold">{workspace.data.opposition_identifiers.map((row) => row.raw_value).join(", ") || "Pending allocation"}</div></div>
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3"><div className="text-xs text-[var(--color-mute)]">Stage</div><div className="text-sm font-semibold">{readable(workspace.data.proceeding.stage)}</div></div>
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3"><div className="text-xs text-[var(--color-mute)]">Matter</div><div className="break-all text-sm font-semibold">{workspace.data.linked_matter_id ?? "Not linked"}</div></div>
            </div>
            {verifiedHttpSource(workspace.data.profile_event?.source_reference) ? (
              <a className="inline-flex w-fit items-center gap-1 break-all text-sm font-semibold text-[var(--color-primary)] underline" href={verifiedHttpSource(workspace.data.profile_event?.source_reference) ?? undefined} target="_blank" rel="noreferrer">
                Open profile source <ExternalLink className="h-4 w-4 shrink-0" />
              </a>
            ) : null}

            {workspace.data.readiness_gaps.length ? <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm"><strong>Stage progression blocked</strong><div className="mt-1 flex flex-wrap gap-2">{workspace.data.readiness_gaps.map((gap) => <span key={gap}>{readable(gap)}</span>)}</div></div> : null}

            <form className="flex min-w-0 flex-col gap-4 border-t border-[var(--color-line)] pt-4" onSubmit={(event) => { event.preventDefault(); if (saveInput) save.mutate(saveInput); }}>
              <div className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4">
                <Field label="Applicable rule version"><Input value={ruleVersion} onChange={(event) => setRuleVersion(event.target.value)} /></Field>
                <Field label="Forum"><Input value={forum} onChange={(event) => setForum(event.target.value)} /></Field>
                <Field label="Notice source reference"><Input value={noticeRef} onChange={(event) => setNoticeRef(event.target.value)} /></Field>
                <Field label="Notice document reference"><Input value={noticeDocumentRef} onChange={(event) => setNoticeDocumentRef(event.target.value)} /></Field>
                <Field label="Profile source"><select className={SELECT_CLASS} value={profileSource} onChange={(event) => setProfileSource(event.target.value as typeof profileSource)}><option value="manual">Manual</option><option value="registry">Registry</option><option value="integration">Integration</option><option value="system">System</option></select></Field>
                <Field label="Profile source URL or reference"><Input value={profileSourceRef} onChange={(event) => setProfileSourceRef(event.target.value)} /></Field>
                <Field label="Client instruction"><select className={SELECT_CLASS} value={instructionState} onChange={(event) => setInstructionState(event.target.value as typeof instructionState)}><option value="pending">Pending</option><option value="confirmed">Confirmed</option><option value="not_required">Not required</option></select></Field>
                <Field label="Instruction reference"><Input value={instructionRef} onChange={(event) => setInstructionRef(event.target.value)} /></Field>
                <Field label="Limitation date"><Input type="date" value={limitationDate} onChange={(event) => setLimitationDate(event.target.value)} /></Field>
                <Field label="Evidence references"><Input value={evidenceRefs} onChange={(event) => setEvidenceRefs(event.target.value)} /></Field>
                <Field label="Document references"><Input value={documentRefs} onChange={(event) => setDocumentRefs(event.target.value)} /></Field>
                <Field label="Revision reason"><Textarea value={profileReason} onChange={(event) => setProfileReason(event.target.value)} /></Field>
              </div>

              <section className="min-w-0 space-y-3"><div className="flex items-center justify-between"><h4 className="font-semibold">Parties and roles</h4><Button type="button" size="sm" variant="secondary" onClick={() => setParties((rows) => [...rows, { role: "counsel", party_name: "", source: "client instruction" }])}><Plus className="h-4 w-4" /> Add party</Button></div>{parties.map((party, index) => <div key={`${party.role}-${index}`} className="grid min-w-0 gap-2 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[160px_1fr_1fr_auto]"><select aria-label={`Party ${index + 1} role`} className={SELECT_CLASS} value={party.role} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, role: event.target.value as PartyDraft["role"] } : row))}><option value="applicant">Applicant</option><option value="opponent">Opponent</option><option value="agent">Agent</option><option value="counsel">Counsel</option></select><Input aria-label={`Party ${index + 1} name`} value={party.party_name} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, party_name: event.target.value } : row))} placeholder="Party name" /><Input aria-label={`Party ${index + 1} source`} value={party.source} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, source: event.target.value } : row))} placeholder="Source" /><Button type="button" size="sm" className="w-10 px-0" variant="ghost" title="Remove party" onClick={() => setParties((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></Button></div>)}</section>

              <section className="min-w-0 space-y-3"><div className="flex items-center justify-between"><h4 className="font-semibold">Grounds</h4><Button type="button" size="sm" variant="secondary" onClick={() => setGrounds((rows) => [...rows, { ...EMPTY_GROUND }])}><Plus className="h-4 w-4" /> Add ground</Button></div>{grounds.map((ground, index) => <div key={index} className="grid min-w-0 gap-2 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[180px_180px_1fr_auto]"><select aria-label={`Ground ${index + 1} category`} className={SELECT_CLASS} value={ground.category} onChange={(event) => setGrounds((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, category: event.target.value as IpOppositionGround["category"] } : row))}>{["earlier_mark", "passing_off", "well_known_mark", "descriptiveness", "non_distinctive", "prohibited_mark", "bad_faith", "other"].map((value) => <option key={value} value={value}>{readable(value)}</option>)}</select><select aria-label={`Ground ${index + 1} classification source`} className={SELECT_CLASS} value={ground.classification_source} onChange={(event) => setGrounds((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, classification_source: event.target.value as IpOppositionGround["classification_source"] } : row))}><option value="manual">Manual</option><option value="ai_assisted">AI assisted</option></select><Textarea aria-label={`Ground ${index + 1} lawyer detail`} value={ground.lawyer_detail} onChange={(event) => setGrounds((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, lawyer_detail: event.target.value } : row))} placeholder="Lawyer-confirmed pleaded ground" /><Button type="button" size="sm" className="w-10 px-0" variant="ghost" title="Remove ground" onClick={() => setGrounds((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></Button></div>)}</section>

              <section className="min-w-0 space-y-3"><div className="flex items-center justify-between"><h4 className="font-semibold">Challenged goods and services</h4><Button type="button" size="sm" variant="secondary" onClick={() => setScope((rows) => [...rows, { ...EMPTY_SCOPE }])}><Plus className="h-4 w-4" /> Add class segment</Button></div>{scope.map((row, index) => <div key={index} className="grid min-w-0 gap-2 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[120px_1fr_auto]"><Input aria-label={`Scope ${index + 1} class`} type="number" min={1} max={45} value={row.class_number} onChange={(event) => setScope((rows) => rows.map((item, rowIndex) => rowIndex === index ? { ...item, class_number: Number(event.target.value) } : item))} /><Textarea aria-label={`Scope ${index + 1} goods and services`} value={row.goods_services_segment} onChange={(event) => setScope((rows) => rows.map((item, rowIndex) => rowIndex === index ? { ...item, goods_services_segment: event.target.value } : item))} placeholder="Challenged segment" /><Button type="button" size="sm" className="w-10 px-0" variant="ghost" title="Remove class segment" onClick={() => setScope((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></Button></div>)}</section>

              {workspace.data.proceeding.side === "opponent" ? <section className="min-w-0 space-y-3"><div className="flex items-center justify-between"><h4 className="font-semibold">Relied-on rights</h4><Button type="button" size="sm" variant="secondary" onClick={() => setRights((rows) => [...rows, { ...EMPTY_RIGHT }])}><Plus className="h-4 w-4" /> Add right</Button></div>{rights.map((right, index) => <div key={index} className="grid min-w-0 gap-2 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-2 xl:grid-cols-4"><Input aria-label={`Right ${index + 1} mark`} value={right.mark_or_right} onChange={(event) => setRights((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, mark_or_right: event.target.value } : row))} placeholder="Mark or right" /><Input aria-label={`Right ${index + 1} identifier`} value={right.identifier ?? ""} onChange={(event) => setRights((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, identifier: event.target.value || null } : row))} placeholder="Registration number" /><Input aria-label={`Right ${index + 1} owner`} value={right.owner} onChange={(event) => setRights((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, owner: event.target.value } : row))} placeholder="Owner" /><Input aria-label={`Right ${index + 1} status`} value={right.status} onChange={(event) => setRights((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, status: event.target.value } : row))} placeholder="Status" /><Textarea className="md:col-span-2 xl:col-span-3" aria-label={`Right ${index + 1} goods and services`} value={right.goods_services} onChange={(event) => setRights((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, goods_services: event.target.value } : row))} placeholder="Goods and services" /><Button type="button" size="sm" className="w-10 px-0" variant="ghost" title="Remove relied-on right" onClick={() => setRights((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></Button></div>)}</section> : null}

              {workspace.data.proceeding.side === "applicant" ? <section className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4"><h4 className="font-semibold md:col-span-2 xl:col-span-4">Service</h4><Field label="Method"><Input value={serviceMethod} onChange={(event) => setServiceMethod(event.target.value)} /></Field><Field label="Destination"><Input value={serviceDestination} onChange={(event) => setServiceDestination(event.target.value)} /></Field><Field label="Served on"><Input type="date" value={servedOn} onChange={(event) => setServedOn(event.target.value)} /></Field><Field label="Service evidence"><Input value={serviceEvidence} onChange={(event) => setServiceEvidence(event.target.value)} /></Field><label className="flex items-center gap-2 text-sm md:col-span-2"><input type="checkbox" checked={startsResponse} onChange={(event) => setStartsResponse(event.target.checked)} /> Starts response period</label></section> : null}

              <Button className="w-full sm:w-auto sm:self-start" type="submit" disabled={!canReview || !currentMembershipId || ruleVersion.trim().length < 2 || forum.trim().length < 2 || profileReason.trim().length < 5 || save.isPending}><Save className="h-4 w-4" /> {profile ? "Save profile revision" : "Confirm opposition profile"}</Button>
            </form>

            {workspace.data.proceeding.side === "applicant" && workspace.data.profile ? <IpOppositionApplicantWorkflow docket={docket} workspace={workspace.data} canReview={canReview} currentMembershipId={currentMembershipId} /> : null}
            {workspace.data.proceeding.side === "opponent" && workspace.data.profile ? <IpOppositionOpponentWorkflow docket={docket} workspace={workspace.data} canReview={canReview} currentMembershipId={currentMembershipId} /> : null}
            {workspace.data.profile ? <IpOppositionSharedWorkflow docket={docket} workspace={workspace.data} canReview={canReview} currentMembershipId={currentMembershipId} /> : null}

            <form data-testid="ip-opposition-stage-form" className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); if (transitionInput) transition.mutate(transitionInput); }}>
              <div className="md:col-span-2 xl:col-span-4"><h4 className="flex items-center gap-2 font-semibold"><Scale className="h-4 w-4" /> Stage transition</h4></div>
              <Field label="Next stage"><select className={SELECT_CLASS} value={toStage} onChange={(event) => setToStage(event.target.value)}>{["notice_filed", "service_pending", "counterstatement_due", "counterstatement_filed", "opponent_evidence_due", "opponent_evidence_filed", "applicant_evidence_due", "applicant_evidence_filed", "reply_evidence_due", "reply_evidence_filed", "hearing_pending", "hearing_scheduled", "reserved_for_order", "decided", "appeal_pending", "appealed", "withdrawn", "closed"].map((value) => <option key={value} value={value}>{readable(value)}</option>)}</select></Field>
              <Field label="Transition kind"><select className={SELECT_CLASS} value={transitionKind} onChange={(event) => setTransitionKind(event.target.value as typeof transitionKind)}><option value="normal">Normal</option><option value="skipped">Skipped</option><option value="waived">Waived</option><option value="extended">Extended</option><option value="superseded">Superseded</option></select></Field>
              <Field label="Source reference"><Input value={transitionSourceRef} onChange={(event) => setTransitionSourceRef(event.target.value)} /></Field>
              <Field label="Evidence references"><Input value={transitionEvidence} onChange={(event) => setTransitionEvidence(event.target.value)} /></Field>
              <Field label="Reason"><Textarea value={transitionReason} onChange={(event) => setTransitionReason(event.target.value)} /></Field>
              {transitionKind !== "normal" ? <><Field label="Authority reference"><Input value={authorityRef} onChange={(event) => setAuthorityRef(event.target.value)} /></Field><Field label="Authorized confirmation"><Input value={authorizedConfirmation} onChange={(event) => setAuthorizedConfirmation(event.target.value)} /></Field></> : null}
              {toStage === "closed" ? <><Field label="Outcome"><Input value={outcome} onChange={(event) => setOutcome(event.target.value)} /></Field><Field label="Outcome date"><Input type="date" value={outcomeDate} onChange={(event) => setOutcomeDate(event.target.value)} /></Field>{transitionKind === "normal" ? <Field label="Authorized confirmation"><Input value={authorizedConfirmation} onChange={(event) => setAuthorizedConfirmation(event.target.value)} /></Field> : null}</> : null}
              <div className="flex items-end"><Button className="w-full" type="submit" disabled={!canReview || !workspace.data.ready_for_stage_progression || transitionReason.trim().length < 5 || (transitionKind !== "normal" && (!transitionSourceRef.trim() || !transitionEvidence.trim() || !authorityRef.trim() || !authorizedConfirmation.trim())) || (toStage === "closed" && (!outcome.trim() || !outcomeDate || !transitionSourceRef.trim() || !transitionEvidence.trim() || !authorizedConfirmation.trim())) || transition.isPending}><ArrowRight className="h-4 w-4" /> Apply stage</Button></div>
            </form>

            {workspace.data.stage_events.length ? <section className="border-t border-[var(--color-line)] pt-4"><h4 className="font-semibold">Stage history</h4><ol className="mt-2 space-y-2">{[...workspace.data.stage_events].reverse().map((event) => <li key={event.id} className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3 text-sm"><strong>{readable(event.before_phase ?? "intake")} → {readable(event.after_phase ?? event.resulting_stage ?? "recorded")}</strong><div className="break-words text-xs text-[var(--color-mute)]">{new Date(event.effective_at).toLocaleString()} · {event.reason}</div></li>)}</ol></section> : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
