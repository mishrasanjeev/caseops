"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgeIndianRupee, FileCheck2, Plus, Scale } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  addIpCostItem,
  addIpRelatedRightObligation,
  addIpTitleInterest,
  bulkReassignIpCoverage,
  completeIpRelatedRightObligation,
  createIpDocket,
  discoverIpEvidence,
  fetchIpDockets,
  fetchIpWorkspaceReadiness,
  reconcileIpCosts,
  reviewIpEvidenceCandidate,
  type IpDocket,
  type IpEvidenceCandidate,
  type IpFeatureReadiness,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

const TODAY = new Date().toISOString().slice(0, 10);

export default function IpDocketPage() {
  const queryClient = useQueryClient();
  const canView = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canReview = useCapability("ip:approve");
  const canFinance = useCapability("ip:fees_manage");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const readiness = useQuery({
    queryKey: ["ip", "readiness"],
    queryFn: fetchIpWorkspaceReadiness,
    enabled: canView,
  });
  const listing = useQuery({
    queryKey: ["ip", "dockets"],
    queryFn: fetchIpDockets,
    enabled: canView && readiness.data?.workspace_available === true,
  });
  const dockets = listing.data?.dockets ?? [];
  const selected = useMemo(
    () => dockets.find((row) => row.id === selectedId) ?? dockets[0] ?? null,
    [dockets, selectedId],
  );

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ip", "dockets"] });
  };

  if (!canView) {
    return (
      <EmptyState
        title="IP docket access required"
        description="Your role does not include permission to view intellectual-property records."
      />
    );
  }

  if (readiness.isPending) {
    return (
      <Card>
        <CardContent className="py-10 text-sm">Checking IP workspace readiness…</CardContent>
      </Card>
    );
  }

  if (readiness.isError) {
    return (
      <EmptyState
        title="IP workspace is unavailable"
        description={apiErrorMessage(
          readiness.error,
          "Readiness could not be verified, so IP operations remain disabled.",
        )}
        action={<Button onClick={() => readiness.refetch()}>Retry readiness check</Button>}
      />
    );
  }

  if (!readiness.data.workspace_available) {
    return <IpReadinessGate features={readiness.data.features} timezone={readiness.data.timezone} />;
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Intellectual property"
        title="Trademark docket"
        description="Form-versioned particulars, evidence links, deadline control, title history, and costs anchored to existing CaseOps owners."
        actions={
          canWrite ? (
            <Button size="sm" onClick={() => setShowCreate((value) => !value)}>
              <Plus className="h-4 w-4" aria-hidden /> New trademark
            </Button>
          ) : null
        }
      />

      {readiness.data.features.some((feature) => !feature.available) ? (
        <IpAutomationReadiness features={readiness.data.features} />
      ) : null}

      {showCreate && canWrite ? (
        <CreateTrademarkCard
          onCreated={async (docket) => {
            setSelectedId(docket.id);
            setShowCreate(false);
            await refresh();
          }}
        />
      ) : null}

      {listing.isPending ? (
        <Card><CardContent className="py-10 text-sm">Loading IP docket…</CardContent></Card>
      ) : listing.isError ? (
        <EmptyState
          title="Could not load the IP docket"
          description={apiErrorMessage(listing.error, "The IP API did not respond.")}
          action={<Button onClick={() => listing.refetch()}>Retry</Button>}
        />
      ) : dockets.length === 0 ? (
        <EmptyState
          title="No IP records yet"
          description="Create a trademark record to validate filing particulars and begin the evidence-backed docket."
        />
      ) : (
        <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]">
          <Card className="min-w-0">
            <CardHeader><CardTitle as="h2">Portfolio</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              {dockets.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => setSelectedId(row.id)}
                  className={`min-w-0 rounded-lg border p-3 text-left ${
                    selected?.id === row.id
                      ? "border-[var(--color-brand-500)] bg-[var(--color-brand-50)]"
                      : "border-[var(--color-line)] bg-white"
                  }`}
                  data-testid={`ip-docket-${row.id}`}
                >
                  <span className="block truncate font-semibold">{row.title}</span>
                  <span className="mt-1 block text-xs text-[var(--color-mute)]">
                    {row.primary_identifier ?? "Unfiled"} · {row.status} · v{row.current_version}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          {selected ? (
            <DocketWorkspace
              docket={selected}
              canReview={canReview}
              canFinance={canFinance}
              onChanged={refresh}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}

const READINESS_REASON: Record<IpFeatureReadiness["reason"], string> = {
  available: "Available",
  unknown_feature: "Feature is not in the approved catalogue",
  missing_capability: "Your role does not include the required capability",
  missing_entitlement: "The workspace plan does not include this feature",
  rollout_disabled: "The safety rollout has not been enabled",
  rollout_expired: "The approved pilot window has expired",
};

function IpReadinessGate({
  features,
  timezone,
}: {
  features: IpFeatureReadiness[];
  timezone: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Intellectual property"
        title="IP workspace setup"
        description="Operational records stay hidden until server capability, plan entitlement, and safety rollout are all ready."
      />
      <Card className="min-w-0">
        <CardHeader><CardTitle as="h2">Readiness checks</CardTitle></CardHeader>
        <CardContent className="flex min-w-0 flex-col gap-3">
          <p className="text-sm text-[var(--color-mute)]">Workspace timezone: {timezone}</p>
          {features.map((feature) => (
            <div
              key={feature.feature_id}
              className="flex min-w-0 w-full flex-col gap-2 rounded-lg border border-[var(--color-line)] p-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between"
              data-testid={`ip-readiness-${feature.feature_id}`}
            >
              <div className="min-w-0">
                <div className="break-words font-semibold">{feature.feature_id.replaceAll("_", " ")}</div>
                <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
                  {READINESS_REASON[feature.reason]} · owner {feature.owner}
                </div>
              </div>
              <span className={feature.available ? "text-sm font-semibold text-emerald-700" : "text-sm font-semibold text-amber-700"}>
                {feature.available ? "Ready" : "Disabled"}
              </span>
              {!feature.available && feature.manual_fallback_feature_id ? (
                <div className="w-full break-words text-xs text-[var(--color-mute)]">
                  Manual fallback: {feature.manual_fallback_feature_id.replaceAll("_", " ")}
                </div>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function IpAutomationReadiness({ features }: { features: IpFeatureReadiness[] }) {
  const blocked = features.filter((feature) => !feature.available);
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h2">Automation readiness</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-2">
        {blocked.map((feature) => (
          <div
            key={feature.feature_id}
            className="flex min-w-0 w-full flex-col gap-1 rounded-md bg-[var(--color-bg-2)] p-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between"
            data-testid={`ip-automation-${feature.feature_id}`}
          >
            <div className="min-w-0 break-words text-sm font-semibold">
              {feature.feature_id.replaceAll("_", " ")}
            </div>
            <div className="min-w-0 break-words text-xs text-[var(--color-mute)] sm:text-right">
              Disabled · {READINESS_REASON[feature.reason]} · owner {feature.owner}
            </div>
            {feature.manual_fallback_feature_id ? (
              <div className="w-full break-words text-xs text-[var(--color-mute)]">
                Manual fallback remains {feature.manual_fallback_feature_id.replaceAll("_", " ")}.
              </div>
            ) : null}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function CreateTrademarkCard({ onCreated }: { onCreated: (docket: IpDocket) => void }) {
  const [title, setTitle] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [markText, setMarkText] = useState("");
  const [classNumber, setClassNumber] = useState("9");
  const [specification, setSpecification] = useState("");
  const [applicant, setApplicant] = useState("");
  const [evidence, setEvidence] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createIpDocket({
        title,
        primaryIdentifier: identifier || null,
        markText,
        classNumber: Number(classNumber),
        specification,
        applicantName: applicant,
        evidenceReference: evidence,
      }),
    onSuccess: (row) => {
      toast.success("Trademark docket created and readiness-validated.");
      onCreated(row);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create IP docket.")),
  });
  const valid =
    title.trim().length >= 2 &&
    markText.trim().length >= 1 &&
    specification.trim().length >= 3 &&
    applicant.trim().length >= 2 &&
    evidence.trim().length >= 3;

  return (
    <Card>
      <CardHeader><CardTitle as="h2">New trademark particulars</CardTitle></CardHeader>
      <CardContent>
        <form
          className="grid min-w-0 gap-4 md:grid-cols-2"
          onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}
        >
          <Field label="Docket title"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Application / client reference"><Input value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></Field>
          <Field label="Word mark"><Input value={markText} onChange={(e) => setMarkText(e.target.value)} /></Field>
          <Field label="Nice class"><Input type="number" min={1} max={45} value={classNumber} onChange={(e) => setClassNumber(e.target.value)} /></Field>
          <Field label="Goods / services specification"><Input value={specification} onChange={(e) => setSpecification(e.target.value)} /></Field>
          <Field label="Applicant"><Input value={applicant} onChange={(e) => setApplicant(e.target.value)} /></Field>
          <Field label="Representation evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="attachment:… or drive:…" /></Field>
          <div className="flex items-end"><Button type="submit" disabled={!valid || mutation.isPending}>Validate and create</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

function DocketWorkspace({
  docket,
  canReview,
  canFinance,
  onChanged,
}: {
  docket: IpDocket;
  canReview: boolean;
  canFinance: boolean;
  onChanged: () => Promise<void>;
}) {
  const classes = docket.current_particulars.classes_json;
  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid="ip-docket-workspace">
      <Card className="min-w-0">
        <CardHeader><CardTitle as="h2">{docket.title}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Readiness" value={docket.current_particulars.readiness_status} icon={FileCheck2} />
          <Metric label="Form" value={`${docket.current_particulars.form_key} ${docket.current_particulars.form_version}`} icon={Scale} />
          <Metric label="Deadline incidents" value={String(docket.deadline_incidents.length)} icon={AlertTriangle} />
          <Metric label="Cost items" value={String(docket.cost_items.length)} icon={BadgeIndianRupee} />
          <div className="sm:col-span-2 xl:col-span-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Class scope</div>
            <ul className="mt-2 flex min-w-0 flex-col gap-2">
              {classes.map((row) => (
                <li key={row.class_number} className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3 text-sm">
                  <strong>Class {row.class_number}</strong> · <span className="break-words">{row.specification}</span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        <EvidenceCard docket={docket} enabled={canReview} onChanged={onChanged} />
        <CoverageCard docket={docket} enabled={canReview} onChanged={onChanged} />
        <TitleCard docket={docket} enabled={canReview} onChanged={onChanged} />
        <ObligationCard docket={docket} enabled={canReview} onChanged={onChanged} />
        <CostCard docket={docket} enabled={canFinance} onChanged={onChanged} />
      </div>

      <Card>
        <CardHeader><CardTitle as="h3">Operational links</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Metric label="Accepted notices" value={String(docket.notice_links.length)} icon={FileCheck2} />
          <Metric label="Deadline coverage" value={String(docket.deadline_coverages.length)} icon={FileCheck2} />
          <Metric label="Title entries" value={String(docket.title_interests.length)} icon={Scale} />
        </CardContent>
      </Card>
    </div>
  );
}

function EvidenceCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const discover = useMutation({
    mutationFn: () => discoverIpEvidence(docket.id),
    onSuccess: async (result) => {
      toast.success(`Evidence scan complete: ${result.discovered_count} new, ${result.duplicate_count} duplicate.`);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not scan Matter evidence.")),
  });
  const review = useMutation({
    mutationFn: ({ candidate, action }: { candidate: IpEvidenceCandidate; action: "accept" | "reject" }) =>
      reviewIpEvidenceCandidate({ docketId: docket.id, candidate, action }),
    onSuccess: async () => { toast.success("Evidence review recorded."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not review evidence.")),
  });
  const pending = docket.evidence_candidates.filter((row) => row.status === "needs_review" || row.status === "duplicate");
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Matter evidence intake</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <p className="text-xs text-[var(--color-mute)]">Discover linked notices, mailbox communications, attachments, and Drive candidates. Every result requires review; duplicates never auto-link.</p>
        {pending.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <div className="break-words font-semibold">{String(row.metadata_json?.label ?? row.evidence_kind)}</div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">{row.source_type} · {row.status.replaceAll("_", " ")}</div>
            {enabled ? (
              <div className="mt-3 flex min-w-0 w-full flex-wrap gap-2">
                <Button size="sm" onClick={() => review.mutate({ candidate: row, action: "accept" })} disabled={review.isPending}>Accept and link</Button>
                <Button size="sm" variant="secondary" onClick={() => review.mutate({ candidate: row, action: "reject" })} disabled={review.isPending}>Reject</Button>
              </div>
            ) : null}
          </div>
        ))}
        {enabled && docket.matter_id ? (
          <Button size="sm" className="w-full sm:w-auto" onClick={() => discover.mutate()} disabled={discover.isPending}>{discover.isPending ? "Scanning…" : "Discover Matter evidence"}</Button>
        ) : <p className="text-xs text-[var(--color-mute)]">Link this docket to a Matter to enable evidence discovery.</p>}
      </CardContent>
    </Card>
  );
}

function CoverageCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [fromMembershipId, setFromMembershipId] = useState("");
  const [toMembershipId, setToMembershipId] = useState("");
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => bulkReassignIpCoverage({
      fromMembershipId,
      toMembershipId,
      reason,
      expectedVersions: Object.fromEntries(docket.deadline_coverages.filter((row) => row.responsible_membership_id === fromMembershipId || row.backup_membership_id === fromMembershipId).map((row) => [row.id, row.reassignment_version])),
    }),
    onSuccess: async (result) => { toast.success(`${result.reassigned_count} deadline coverage assignment(s) transferred.`); setReason(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not transfer deadline coverage.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Deadline continuity</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.deadline_coverages.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <div className="break-all font-semibold">Responsible: {row.responsible_membership_id}</div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">{row.coverage_status} · calendar {row.calendar_projection_status} · v{row.reassignment_version}</div>
          </div>
        ))}
        {enabled && docket.deadline_coverages.length ? (
          <form className="grid min-w-0 gap-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
            <Field label="Current membership ID"><Input value={fromMembershipId} onChange={(event) => setFromMembershipId(event.target.value)} /></Field>
            <Field label="Replacement membership ID"><Input value={toMembershipId} onChange={(event) => setToMembershipId(event.target.value)} /></Field>
            <Field label="Transfer reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={!fromMembershipId || !toMembershipId || reason.length < 5 || mutation.isPending}>Transfer covered deadlines</Button>
          </form>
        ) : <p className="text-xs text-[var(--color-mute)]">No covered deadlines are attached to this docket.</p>}
      </CardContent>
    </Card>
  );
}

function TitleCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [party, setParty] = useState("");
  const [evidence, setEvidence] = useState("");
  const mutation = useMutation({
    mutationFn: () => addIpTitleInterest(docket.id, { interestType: "ownership", partyName: party, effectiveFrom: TODAY, evidenceReference: evidence }),
    onSuccess: async () => { toast.success("Title evidence added."); setParty(""); setEvidence(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add title evidence.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Chain of title</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.title_interests.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <strong className="break-words">{row.party_name}</strong> · {row.interest_type} from {row.effective_from}
            {row.conflict_flags_json.length ? <div className="mt-1 text-xs text-red-700">Overlap requires review</div> : null}
          </div>
        ))}
        {enabled ? (
          <form className="grid min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
            <Field label="Owner / assignee"><Input value={party} onChange={(e) => setParty(e.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
            <Button size="sm" type="submit" disabled={party.length < 2 || evidence.length < 3 || mutation.isPending}>Add ownership evidence</Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ObligationCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [ownerMembershipId, setOwnerMembershipId] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [evidence, setEvidence] = useState("");
  const [completionEvidence, setCompletionEvidence] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () => addIpRelatedRightObligation(docket.id, { title, obligationType: "recordal", ownerMembershipId, dueOn: dueOn || null, evidenceReference: evidence }),
    onSuccess: async () => { toast.success("Related-right obligation added."); setTitle(""); setDueOn(""); setEvidence(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add obligation.")),
  });
  const complete = useMutation({
    mutationFn: (obligationId: string) => completeIpRelatedRightObligation({ docketId: docket.id, obligationId, completionEvidenceReference: completionEvidence[obligationId] ?? "" }),
    onSuccess: async () => { toast.success("Obligation completed with evidence."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not complete obligation.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Related rights and obligations</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.related_right_obligations.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <div className="break-words font-semibold">{row.title}</div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">{row.obligation_type} · {row.status}{row.due_on ? ` · due ${row.due_on}` : ""}</div>
            {enabled && row.status === "open" ? (
              <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
                <Input className="min-w-0 flex-1" aria-label={`Completion evidence for ${row.title}`} placeholder="Completion evidence reference" value={completionEvidence[row.id] ?? ""} onChange={(event) => setCompletionEvidence((current) => ({ ...current, [row.id]: event.target.value }))} />
                <Button size="sm" className="w-full sm:w-auto" onClick={() => complete.mutate(row.id)} disabled={(completionEvidence[row.id] ?? "").length < 3 || complete.isPending}>Complete</Button>
              </div>
            ) : null}
          </div>
        ))}
        {enabled ? (
          <form className="grid min-w-0 gap-2" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
            <Field label="Obligation"><Input value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
            <Field label="Owner membership ID"><Input value={ownerMembershipId} onChange={(event) => setOwnerMembershipId(event.target.value)} /></Field>
            <Field label="Due date (optional)"><Input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} /></Field>
            <Field label="Obligation evidence"><Input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></Field>
            <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={title.length < 3 || !ownerMembershipId || evidence.length < 3 || create.isPending}>Add recordal obligation</Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CostCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [billingLinkType, setBillingLinkType] = useState<"" | "invoice" | "invoice_line_item" | "time_entry">("");
  const [billingLinkId, setBillingLinkId] = useState("");
  const mutation = useMutation({
    mutationFn: () => addIpCostItem(docket.id, {
      category: "official_fee",
      description,
      amountMinor: Math.round(Number(amount) * 100),
      evidenceReference: evidence,
      billingLinkType: billingLinkType || null,
      billingLinkId: billingLinkId || null,
    }),
    onSuccess: async () => {
      toast.success("Immutable cost evidence added.");
      setDescription(""); setAmount(""); setEvidence(""); setBillingLinkId("");
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add cost evidence.")),
  });
  const reconcile = useMutation({
    mutationFn: () => reconcileIpCosts(docket.id),
    onSuccess: async (report) => {
      toast.success(`Reconciled: ${report.matched_count} matched, ${report.mismatch_count} mismatched.`);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not reconcile IP costs.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">IP cost evidence</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.cost_items.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <strong className="break-words">{row.description}</strong> · {row.currency} {(row.amount_minor / 100).toFixed(2)}
          </div>
        ))}
        {enabled && docket.matter_id ? (
          <form className="grid min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
            <Field label="Description"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            <Field label="Amount (INR)"><Input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
            <Field label="Matter billing link type">
              <select className="h-10 min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={billingLinkType} onChange={(event) => setBillingLinkType(event.target.value as typeof billingLinkType)}>
                <option value="">No billing link</option>
                <option value="invoice">Invoice</option>
                <option value="invoice_line_item">Invoice line item</option>
                <option value="time_entry">Time entry</option>
              </select>
            </Field>
            {billingLinkType ? <Field label="Matter billing record ID"><Input value={billingLinkId} onChange={(event) => setBillingLinkId(event.target.value)} /></Field> : null}
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={description.length < 3 || !amount || evidence.length < 3 || Boolean(billingLinkType) !== Boolean(billingLinkId) || mutation.isPending}>Add cost evidence</Button>
              <Button size="sm" className="w-full sm:w-auto" type="button" variant="secondary" onClick={() => reconcile.mutate()} disabled={reconcile.isPending}>Reconcile with Matter billing</Button>
            </div>
          </form>
        ) : (
          <p className="text-xs text-[var(--color-mute)]">Cost items require a linked Matter so Matter billing remains the accounting owner.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex min-w-0 flex-col gap-1"><Label>{label}</Label>{children}</label>;
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Scale }) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
      <div className="flex items-center gap-2 text-xs text-[var(--color-mute)]"><Icon className="h-4 w-4" aria-hidden />{label}</div>
      <div className="mt-1 truncate font-semibold capitalize">{value.replaceAll("_", " ")}</div>
    </div>
  );
}
