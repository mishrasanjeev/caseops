"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BadgeIndianRupee,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileCheck2,
  Plus,
  Scale,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { IpAccessWorkspace } from "@/components/ip/IpAccessWorkspace";
import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";
import { IpOppositionWorkspace } from "@/components/ip/IpOppositionWorkspace";
import { IpPostRegistrationWorkspace } from "@/components/ip/IpPostRegistrationWorkspace";
import { IpMatterLinksPanel } from "@/components/ip/IpMatterLinksPanel";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { PersonName, PersonPicker } from "@/components/ui/PersonPicker";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import {
  addIpCostItem,
  addIpRelatedRightObligation,
  addIpTitleInterest,
  activateIpDeadlineRule,
  activateIpWorkingCalendar,
  appendIpDocketEvent,
  bulkReassignIpCoverage,
  completeIpLegalDeadline,
  completeIpRelatedRightObligation,
  confirmIpLegalDeadline,
  createIpDeadlineIncident,
  createManualTrademarkApplication,
  createIpSharedHearing,
  correctIpIdentifier,
  decideIpCoverageTransfer,
  decideIpDeadlineIncidentNotification,
  discoverIpEvidence,
  enableIpWorkspace,
  fetchIpCoreRecords,
  fetchIpCoverageTransfersAwaitingMe,
  fetchIpDeadlineImpact,
  fetchIpDeadlineDependencies,
  fetchIpDeadlineRuleImpact,
  fetchIpDeadlineWorkspace,
  fetchIpDocket,
  fetchIpDockets,
  fetchIpSharedHearings,
  fetchIpProsecutionWorkspace,
  fetchIpWorkspaceReadiness,
  listCalendarConnections,
  previewIpDocketEvent,
  previewIpIdentifierDuplicates,
  previewIpDocketLifecycle,
  proposeIpDeadlineRule,
  proposeIpLegalDeadline,
  proposeIpWorkingCalendar,
  recalculateIpLegalDeadline,
  recordIpDeadlineIncidentAction,
  recordIpDeadlineIncidentImpact,
  reconcileIpCosts,
  resolveIpIdentifierDuplicate,
  reviewIpEvidenceCandidate,
  releaseIpIncidentKillSwitch,
  resolveIpDeadlineIncident,
  runIpWorkspaceTest,
  saveIpWorkspaceConfiguration,
  syncHearingToGoogleCalendar,
  syncHearingToOutlook,
  transitionIpDocketLifecycle,
  transitionIpDeadlineRule,
  overrideIpLegalDeadline,
  type IpCoreRecords,
  type IpDocket,
  type IpDeadlineIncident,
  type IpDeadlineRuleVersion,
  type IpLegalDeadline,
  type IpSharedHearing,
  type IpResponsibilityAssignmentInput,
  type IpDocketEventInput,
  type IpEvidenceCandidate,
  type IpFeatureReadiness,
  type IpIdentifier,
  type IpWorkspaceConfigurationStatus,
  type IpWorkspaceTestResult,
  type IpWorkingCalendarVersion,
  updateIpSharedHearing,
  updateTrademarkApplicationPhase,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const TODAY = new Date().toISOString().slice(0, 10);
const FORM_SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";
const DOCKET_VIEWS = ["overview", "proceedings", "schedule", "access"] as const;
type DocketView = (typeof DOCKET_VIEWS)[number];

function requestedDocketView(value: string | null): DocketView {
  return DOCKET_VIEWS.includes(value as DocketView) ? (value as DocketView) : "overview";
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

export default function IpDocketPage() {
  const searchParams = useSearchParams();
  const requestedDocketId = searchParams.get("docket");
  const requestedView = requestedDocketView(searchParams.get("view"));
  const requestedProceedingId = searchParams.get("proceeding");
  const requestedDraftId = searchParams.get("draft");
  const queryClient = useQueryClient();
  const canView = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canUploadDocuments = useCapability("documents:upload");
  const canManageDocuments = useCapability("documents:manage");
  const canReview = useCapability("ip:approve");
  const canCreateDraft = useCapability("drafts:create");
  const canEditDraft = useCapability("drafts:edit");
  const canGenerateDraft = useCapability("drafts:generate");
  const canReviewDraft = useCapability("drafts:review");
  const canFinalizeDraft = useCapability("drafts:finalize");
  const canProposeRules = useCapability("ip:rules_propose");
  const canActivateRules = useCapability("ip:rules_activate");
  const canFinance = useCapability("ip:fees_manage");
  const canConfigure = useCapability("ip:taxonomy_admin");
  const canManageAccess = useCapability("matter_access:manage");
  const session = useSession();
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    requestedDocketId,
  );
  const [showCreate, setShowCreate] = useState(false);

  const readiness = useQuery({
    queryKey: ["ip", "readiness"],
    queryFn: fetchIpWorkspaceReadiness,
    enabled: canView,
  });
  const requestedDocket = useQuery({
    queryKey: ["ip", "dockets", requestedDocketId],
    queryFn: () => fetchIpDocket(requestedDocketId!),
    enabled:
      canView &&
      readiness.data?.workspace_available === true &&
      Boolean(requestedDocketId),
  });
  const deepLinkDocketPending = Boolean(requestedDocketId) && requestedDocket.isPending;
  const listing = useQuery({
    queryKey: ["ip", "dockets"],
    queryFn: fetchIpDockets,
    enabled:
      canView &&
      readiness.data?.workspace_available === true &&
      !requestedDocketId,
  });
  const dockets = listing.data?.dockets ?? [];
  const selected = useMemo(
    () =>
      (selectedId === requestedDocketId ? requestedDocket.data : null) ??
      dockets.find((row) => row.id === selectedId) ??
      dockets[0] ??
      null,
    [dockets, requestedDocket.data, requestedDocketId, selectedId],
  );
  const portfolioDockets = useMemo(
    () =>
      selected && !dockets.some((row) => row.id === selected.id)
        ? [selected, ...dockets]
        : dockets,
    [dockets, selected],
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
    return (
      <IpReadinessGate
        features={readiness.data.features}
        timezone={readiness.data.timezone}
        configurationStatus={readiness.data.configuration_status}
        canConfigure={canConfigure}
        currentMembershipId={session.context?.membership.id ?? null}
        onChanged={async () => {
          await queryClient.invalidateQueries({ queryKey: ["ip", "readiness"] });
        }}
      />
    );
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

      <Tabs defaultValue="docket" className="min-w-0">
        <TabsList className="h-auto w-full min-w-0 flex-wrap sm:w-auto" aria-label="IP workspace areas">
          <TabsTrigger value="docket">Docket</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
        </TabsList>
        <TabsContent value="documents">
          <IpDocumentWorkspace
            dockets={portfolioDockets}
            canUpload={canWrite && canUploadDocuments}
            canManage={canWrite && canManageDocuments}
            canReview={canReview}
            canConfigure={canConfigure}
          />
        </TabsContent>
        <TabsContent value="docket">
          {deepLinkDocketPending && requestedView === "access" && canManageAccess ? (
            <IpAccessWorkspaceLoading />
          ) : deepLinkDocketPending ? (
            <Card><CardContent className="py-10 text-sm">Loading IP docket…</CardContent></Card>
          ) : requestedDocketId && requestedDocket.isError ? (
            <EmptyState
              title="Could not load the linked IP docket"
              description={apiErrorMessage(requestedDocket.error, "The selected IP record is unavailable.")}
              action={<Button onClick={() => requestedDocket.refetch()}>Retry linked docket</Button>}
            />
          ) : listing.isPending && !selected ? (
            <Card><CardContent className="py-10 text-sm">Loading IP docket…</CardContent></Card>
          ) : listing.isError && !selected ? (
            <EmptyState
              title="Could not load the IP docket"
              description={apiErrorMessage(listing.error, "The IP API did not respond.")}
              action={<Button onClick={() => listing.refetch()}>Retry</Button>}
            />
          ) : portfolioDockets.length === 0 ? (
            <EmptyState
              title="No IP records yet"
              description="Create a trademark record to validate filing particulars and begin the evidence-backed docket."
            />
          ) : (
            <div className="flex min-w-0 flex-col gap-5">
              {!requestedDocketId ? <CoverageDecisionsCard onChanged={refresh} /> : null}
              <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]">
          <Card className="min-w-0">
            <CardHeader><CardTitle as="h2">Portfolio</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              {requestedDocketId ? (
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-line)] pb-3 text-xs text-[var(--color-mute)]" role="status">
                  <span>Showing the record selected by this link.</span>
                  <Link className="font-semibold text-[var(--color-brand-700)]" href="/app/ip/portfolio">
                    Open full portfolio
                  </Link>
                </div>
              ) : listing.isFetching ? (
                <p className="text-sm text-[var(--color-mute)]" role="status">
                  Loading the portfolio…
                </p>
              ) : listing.isError ? (
                <Button variant="secondary" onClick={() => listing.refetch()}>
                  Retry portfolio
                </Button>
              ) : null}
              {listing.data?.has_more ? (
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-line)] pb-3 text-xs text-[var(--color-mute)]" role="status">
                  <span>Showing the 100 most recently updated records.</span>
                  <Link className="font-semibold text-[var(--color-brand-700)]" href="/app/ip/portfolio">
                    Open full portfolio
                  </Link>
                </div>
              ) : null}
              {portfolioDockets.map((row) => (
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
              key={selected.id}
              docket={selected}
              canWrite={canWrite}
              canReview={canReview}
              canCreateDraft={canCreateDraft}
              canEditDraft={canEditDraft}
              canGenerateDraft={canGenerateDraft}
              canReviewDraft={canReviewDraft}
              canFinalizeDraft={canFinalizeDraft}
              canFinance={canFinance}
              canProposeRules={canProposeRules}
              canActivateRules={canActivateRules}
              canManageAccess={canManageAccess}
              initialView={requestedDocketId === selected.id ? requestedView : "overview"}
              initialProceedingId={
                requestedDocketId === selected.id ? requestedProceedingId : null
              }
              initialDraftId={requestedDocketId === selected.id ? requestedDraftId : null}
              currentMembershipId={session.context?.membership.id ?? null}
              onChanged={refresh}
            />
          ) : null}
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function IpAccessWorkspaceLoading() {
  return (
    <Card className="min-w-0" data-testid="ip-access-workspace-loading">
      <CardHeader>
        <CardTitle as="h3">Internal access and ethical walls</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <p className="text-sm text-[var(--color-mute)]">
          IP access is independent from a linked Matter. Linked Matter permissions are never
          copied.
        </p>
        <p className="text-sm" role="status">
          Loading the selected docket and its access policy…
        </p>
      </CardContent>
    </Card>
  );
}

const READINESS_REASON: Record<IpFeatureReadiness["reason"], string> = {
  available: "Available",
  unknown_feature: "Feature is not in the approved catalogue",
  missing_capability: "Your role does not include the required capability",
  missing_entitlement: "The workspace plan does not include this feature",
  rollout_disabled: "The safety rollout has not been enabled",
  rollout_expired: "The approved pilot window has expired",
  workspace_not_configured: "Tenant setup has not been saved",
  tenant_disabled: "Tenant enablement has not passed",
  readiness_test_failed: "The latest required readiness test has not passed",
  incident_kill_switch: "A risk incident has stopped this automation",
};

const DUE_FORMAT = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function duePhrase(dueOn: string | null, daysUntilDue: number | null) {
  if (!dueOn) return "No due date recorded";
  const on = DUE_FORMAT.format(new Date(`${dueOn}T00:00:00`));
  if (daysUntilDue === null) return `Due ${on}`;
  if (daysUntilDue < 0) return `Due ${on} · ${Math.abs(daysUntilDue)} days overdue`;
  if (daysUntilDue === 0) return `Due ${on} · today`;
  return `Due ${on} · in ${daysUntilDue} ${daysUntilDue === 1 ? "day" : "days"}`;
}

/**
 * Coverage transfers waiting on the signed-in member (CAL-OPS-08).
 *
 * Rendered above the portfolio because a pending decision blocks someone
 * else's work, and it is omitted entirely when there is nothing to decide —
 * a permanently empty band would train people to ignore the space.
 */
function CoverageDecisionsCard({ onChanged }: { onChanged: () => Promise<void> }) {
  const [decliningId, setDecliningId] = useState<string | null>(null);
  const [declineReason, setDeclineReason] = useState("");
  const awaiting = useQuery({
    queryKey: ["ip-coverage-awaiting-me"],
    queryFn: fetchIpCoverageTransfersAwaitingMe,
  });

  const decide = useMutation({
    mutationFn: (input: {
      coverageId: string;
      decision: "accepted" | "rejected";
      reason?: string;
    }) => decideIpCoverageTransfer(input.coverageId, {
      decision: input.decision,
      reason: input.reason,
    }),
    onSuccess: async (_result, input) => {
      toast.success(
        input.decision === "accepted"
          ? "You are now responsible for this deadline."
          : "Declined. The deadline stays with a named owner.",
      );
      setDecliningId(null);
      setDeclineReason("");
      await awaiting.refetch();
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record your decision.")),
  });

  const transfers = useMemo(() => {
    const rows = awaiting.data?.transfers ?? [];
    // Soonest first: the decision that can still be acted on matters most.
    return [...rows].sort((a, b) => {
      if (a.due_on === b.due_on) return a.docket_title.localeCompare(b.docket_title);
      if (!a.due_on) return 1;
      if (!b.due_on) return -1;
      return a.due_on < b.due_on ? -1 : 1;
    });
  }, [awaiting.data]);

  const initialDecisionError = awaiting.isError && awaiting.data === undefined;
  const showDecisionCard =
    awaiting.isPending || initialDecisionError || transfers.length > 0;

  // The target is query-backed and usually does not exist when the browser
  // first processes /app/ip#coverage-decisions. Honor the deep link once the
  // asynchronous card has actually mounted.
  useEffect(() => {
    if (
      showDecisionCard &&
      window.location.hash === "#coverage-decisions"
    ) {
      document.getElementById("coverage-decisions")?.scrollIntoView({
        block: "start",
      });
    }
  }, [showDecisionCard]);

  if (!showDecisionCard) return null;

  return (
    <Card
      id="coverage-decisions"
      className="min-w-0 scroll-mt-6"
      data-testid="ip-coverage-decisions"
    >
      <CardHeader>
        <CardTitle as="h2">Coverage awaiting your decision</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {awaiting.isPending ? (
          <div
            className="flex min-w-0 flex-col gap-2"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="ip-coverage-decisions-loading"
          >
            <span className="sr-only">Loading coverage decisions.</span>
            <Skeleton className="h-20 w-full" aria-hidden="true" />
          </div>
        ) : initialDecisionError ? (
          <QueryErrorState
            error={awaiting.error}
            title="Could not load coverage decisions"
            onRetry={() => awaiting.refetch()}
          />
        ) : transfers.map((row) => {
          const isDeclining = decliningId === row.coverage_id;
          const reasonId = `decline-reason-${row.coverage_id}`;
          return (
            <div
              key={row.coverage_id}
              className="min-w-0 rounded-lg border border-[var(--color-line)] bg-white p-4"
              data-testid={`ip-coverage-decision-${row.coverage_id}`}
            >
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="min-w-0 break-words font-semibold">{row.docket_title}</span>
                {row.docket_identifier ? (
                  <span className="font-mono text-xs text-[var(--color-mute)] tabular-nums">
                    {row.docket_identifier}
                  </span>
                ) : null}
                {row.critical ? <Badge tone="warning">Critical</Badge> : null}
              </div>

              <p className="mt-1 text-sm tabular-nums text-[var(--color-ink-2)]">
                {row.deadline_title ? `${row.deadline_title} · ` : ""}
                {duePhrase(row.due_on, row.days_until_due)}
              </p>

              <p className="mt-2 max-w-[70ch] text-sm text-[var(--color-mute)]">
                {row.transfer_kind === "immediate"
                  ? `You already hold this deadline. Declining moves it to ${
                      row.escalation_label ?? "the escalation owner"
                    }.`
                  : `${row.responsible_label} remains responsible until you accept.`}
              </p>

              {row.reason ? (
                <p className="mt-1 max-w-[70ch] text-sm text-[var(--color-mute)]">
                  Reason given: {row.reason}
                </p>
              ) : null}

              {isDeclining ? (
                <div className="mt-3 flex min-w-0 flex-col gap-2">
                  <Label htmlFor={reasonId}>Why are you declining?</Label>
                  <Textarea
                    id={reasonId}
                    value={declineReason}
                    onChange={(event) => setDeclineReason(event.target.value)}
                    placeholder="This is recorded against the deadline."
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={declineReason.trim().length < 5 || decide.isPending}
                      onClick={() =>
                        decide.mutate({
                          coverageId: row.coverage_id,
                          decision: "rejected",
                          reason: declineReason.trim(),
                        })
                      }
                    >
                      Confirm decline
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setDecliningId(null);
                        setDeclineReason("");
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({ coverageId: row.coverage_id, decision: "accepted" })
                    }
                  >
                    Accept responsibility
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={decide.isPending}
                    onClick={() => {
                      setDecliningId(row.coverage_id);
                      setDeclineReason("");
                    }}
                  >
                    Decline
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function IpReadinessGate({
  features,
  timezone,
  configurationStatus,
  canConfigure,
  currentMembershipId,
  onChanged,
}: {
  features: IpFeatureReadiness[];
  timezone: string;
  configurationStatus?: IpWorkspaceConfigurationStatus;
  canConfigure: boolean;
  currentMembershipId: string | null;
  onChanged: () => Promise<void>;
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
      {canConfigure ? (
        <IpWorkspaceSetupCard
          status={configurationStatus}
          currentMembershipId={currentMembershipId}
          onChanged={onChanged}
        />
      ) : null}
    </div>
  );
}

function IpWorkspaceSetupCard({
  status,
  currentMembershipId,
  onChanged,
}: {
  status?: IpWorkspaceConfigurationStatus;
  currentMembershipId: string | null;
  onChanged: () => Promise<void>;
}) {
  const configuration = status?.configuration ?? null;
  const [jurisdiction, setJurisdiction] = useState(
    configuration?.jurisdictions_json[0] ?? "IN",
  );
  const [office, setOffice] = useState(configuration?.offices_json[0] ?? "IP India");
  const [timezone, setTimezone] = useState(configuration?.timezone ?? "Asia/Kolkata");
  const [holidayCalendar, setHolidayCalendar] = useState(
    configuration?.holiday_calendar_key ?? "IN-CENTRAL-2026",
  );
  const [providerKey, setProviderKey] = useState(
    configuration?.provider_keys_json[0] ?? "",
  );
  const [acceptTerms, setAcceptTerms] = useState(
    configuration?.provider_terms_accepted_at != null,
  );
  const [automations, setAutomations] = useState({
    registry_sync: configuration?.enabled_automations_json.includes("registry_sync") ?? false,
    deadline_automation:
      configuration?.enabled_automations_json.includes("deadline_automation") ?? false,
    notification_automation:
      configuration?.enabled_automations_json.includes("notification_automation") ?? false,
  });
  const escalationOwner =
    configuration?.escalation_owner_membership_id ?? currentMembershipId ?? "";
  const providerAdapters = status?.provider_adapters ?? [];
  const selectedAdapter = providerAdapters.find(
    (adapter) => adapter.provider === providerKey,
  );

  const save = useMutation({
    mutationFn: () =>
      saveIpWorkspaceConfiguration({
        expectedVersion: configuration?.version ?? null,
        jurisdiction,
        office,
        timezone,
        holidayCalendarKey: holidayCalendar,
        escalationOwnerMembershipId: escalationOwner,
        providerKey,
        acceptProviderTerms: acceptTerms,
      }),
    onSuccess: async () => {
      toast.success("IP workspace configuration saved; prior tests and enablement were reset.");
      await onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save IP workspace configuration.")),
  });
  const test = useMutation({
    mutationFn: (testKind: IpWorkspaceTestResult["test_kind"]) => {
      if (!configuration) throw new Error("Save the configuration before running tests.");
      return runIpWorkspaceTest({
        version: configuration.version,
        testKind,
        providerKey:
          testKind === "connection" || testKind === "source_open"
            ? providerKey || null
            : null,
      });
    },
    onSuccess: async (result) => {
      if (result.status === "passed") toast.success(`${result.test_kind} test passed.`);
      else toast.error(`${result.test_kind} failed: ${result.failure_code ?? "unknown failure"}.`);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Readiness test could not run.")),
  });
  const enable = useMutation({
    mutationFn: (includeAutomations: boolean) => {
      if (!configuration) throw new Error("Save the configuration before enabling.");
      const enabledAutomations = includeAutomations
        ? (Object.entries(automations)
            .filter(([, enabled]) => enabled)
            .map(([feature]) => feature) as Array<
            "registry_sync" | "deadline_automation" | "notification_automation"
          >)
        : [];
      return enableIpWorkspace({ version: configuration.version, enabledAutomations });
    },
    onSuccess: async (result) => {
      toast.success(
        result.configuration?.enabled_automations_json.length
          ? "IP workspace and tested automations enabled for this tenant."
          : "Manual IP workspace enabled; provider automation remains disabled.",
      );
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "IP workspace is not ready.")),
  });

  const tests = status?.tests ?? [];
  const latest = new Map<string, IpWorkspaceTestResult>();
  tests.forEach((row) => {
    if (!latest.has(row.test_kind)) latest.set(row.test_kind, row);
  });

  return (
    <Card className="min-w-0" data-testid="ip-workspace-configuration">
      <CardHeader><CardTitle as="h2">Configure pilot workspace</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <Field label="Enabled asset type">
            <Input value="Trademark" disabled aria-label="Enabled asset type" />
          </Field>
          <Field label="Jurisdiction">
            <Input value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)} />
          </Field>
          <Field label="Office">
            <Input value={office} onChange={(event) => setOffice(event.target.value)} />
          </Field>
          <Field label="IANA timezone">
            <Input value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          </Field>
          <Field label="Holiday calendar">
            <Input
              value={holidayCalendar}
              onChange={(event) => setHolidayCalendar(event.target.value)}
            />
          </Field>
          <Field label="Permitted registry provider (optional)">
            <select
              className={FORM_SELECT_CLASS}
              value={providerKey}
              onChange={(event) => {
                setProviderKey(event.target.value);
                setAcceptTerms(false);
                setAutomations((current) => ({ ...current, registry_sync: false }));
              }}
              aria-label="Permitted registry provider"
            >
              <option value="">Manual docketing only</option>
              {providerAdapters.map((adapter) => (
                <option key={adapter.provider} value={adapter.provider}>
                  {adapter.display_name} ({adapter.adapter_status.replaceAll("_", " ")})
                </option>
              ))}
            </select>
          </Field>
        </div>

        {selectedAdapter ? (
          <div
            className="rounded-md border border-[var(--color-line)] p-3 text-sm"
            data-testid="ip-provider-contract"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{selectedAdapter.display_name}</span>
              <Badge
                tone={selectedAdapter.adapter_status === "implemented" ? "success" : "warning"}
              >
                {selectedAdapter.adapter_status.replaceAll("_", " ")}
              </Badge>
              <Badge tone="neutral">
                {selectedAdapter.commercial_terms_status.replaceAll("_", " ")}
              </Badge>
            </div>
            {selectedAdapter.legal_coverage.map((coverage) => (
              <div key={`${coverage.jurisdiction}:${coverage.office}`} className="mt-2 text-xs">
                {coverage.jurisdiction} · {coverage.office} · {coverage.asset_types.join(", ")}
                {" · "}{coverage.coverage_status} legal coverage
              </div>
            ))}
            {selectedAdapter.activation_blockers.length ? (
              <div className="mt-2 break-words text-xs text-amber-800">
                Activation blocked: {selectedAdapter.activation_blockers.join(", ")}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="rounded-lg border border-[var(--color-line)] p-3 text-sm">
          <div className="font-semibold">Seeded governance contract</div>
          <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
            Taxonomy ip-taxonomy-2026.1 · event catalogue ip-events-v1 · jurisdiction rule
            2026.1 · Monday–Friday working policy · in-app notification · 30-minute critical
            escalation.
          </div>
        </div>

        <label className="flex min-w-0 items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={acceptTerms}
            onChange={(event) => setAcceptTerms(event.target.checked)}
            disabled={!providerKey.trim()}
          />
          <span className="min-w-0 break-words">
            Accept provider attribution and cost terms version 2026.1. No credential is stored
            here; secrets remain in server-side integration settings.
          </span>
        </label>

        <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button
            className="w-full sm:w-auto"
            onClick={() => save.mutate()}
            disabled={
              !jurisdiction.trim() ||
              !office.trim() ||
              !timezone.trim() ||
              !holidayCalendar.trim() ||
              !escalationOwner ||
              (Boolean(providerKey.trim()) && !acceptTerms) ||
              save.isPending
            }
          >
            Save configuration
          </Button>
          <Link
            href="/app/admin/roles"
            className="w-full rounded-md border border-[var(--color-line)] px-3 py-2 text-center text-sm font-semibold sm:w-auto"
          >
            Map IP roles
          </Link>
          <Link
            href="/app/admin/teams"
            className="w-full rounded-md border border-[var(--color-line)] px-3 py-2 text-center text-sm font-semibold sm:w-auto"
          >
            Configure pilot teams
          </Link>
          <Link
            href="/app/admin/integrations"
            className="w-full rounded-md border border-[var(--color-line)] px-3 py-2 text-center text-sm font-semibold sm:w-auto"
          >
            Configure provider secrets
          </Link>
        </div>

        <div className="grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {([
            ["connection", "Test provider connection"],
            ["source_open", "Test source open"],
            ["notification", "Test notification (dry run)"],
            ["deadline_calculation", "Test sample deadline"],
          ] as const).map(([kind, label]) => {
            const result = latest.get(kind);
            return (
              <div key={kind} className="flex min-w-0 flex-col gap-2 rounded-md bg-[var(--color-bg-2)] p-3">
                <div className="break-words text-xs text-[var(--color-mute)]">
                  {result ? `${result.status}${result.failure_code ? ` · ${result.failure_code}` : ""}` : "Not run"}
                </div>
                <Button
                  size="sm"
                  className="w-full"
                  variant="secondary"
                  onClick={() => test.mutate(kind)}
                  disabled={
                    !configuration ||
                    ((kind === "connection" || kind === "source_open") && !providerKey.trim()) ||
                    test.isPending
                  }
                >
                  {label}
                </Button>
              </div>
            );
          })}
        </div>

        <fieldset className="min-w-0 rounded-lg border border-[var(--color-line)] p-3">
          <legend className="px-1 text-sm font-semibold">Affected automation only</legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {(Object.keys(automations) as Array<keyof typeof automations>).map((feature) => (
              <label key={feature} className="flex min-w-0 items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={automations[feature]}
                  disabled={
                    feature === "registry_sync" &&
                    selectedAdapter?.adapter_status !== "implemented"
                  }
                  onChange={(event) =>
                    setAutomations((current) => ({ ...current, [feature]: event.target.checked }))
                  }
                />
                <span className="break-words">{feature.replaceAll("_", " ")}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {status?.enablement_blockers.length ? (
          <div className="break-words text-xs text-amber-800" data-testid="ip-setup-blockers">
            Current blockers: {status.enablement_blockers.join(", ")}
          </div>
        ) : null}
        <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button
            className="w-full sm:w-auto"
            variant="secondary"
            onClick={() => enable.mutate(false)}
            disabled={!configuration || enable.isPending}
          >
            Enable manual workspace
          </Button>
          <Button
            className="w-full sm:w-auto"
            onClick={() => enable.mutate(true)}
            disabled={!configuration || enable.isPending}
          >
            Enable selected tested automations
          </Button>
        </div>
      </CardContent>
    </Card>
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
  const [markText, setMarkText] = useState("");
  const [classNumber, setClassNumber] = useState("9");
  const [specification, setSpecification] = useState("");
  const [applicant, setApplicant] = useState("");
  const [evidence, setEvidence] = useState("");
  const [matterId, setMatterId] = useState("");
  const [restricted, setRestricted] = useState(false);
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [office, setOffice] = useState("IP India");
  const [filingPhase, setFilingPhase] = useState<"draft" | "pre_filing" | "filed">(
    "pre_filing",
  );
  const [applicationNumber, setApplicationNumber] = useState("");
  const [numberSource, setNumberSource] = useState("manual");
  const [numberEffectiveFrom, setNumberEffectiveFrom] = useState(TODAY);
  const [pendingAllocation, setPendingAllocation] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      createManualTrademarkApplication({
        title,
        matterId: matterId.trim() || null,
        restricted,
        assetTitle: markText,
        jurisdiction,
        office,
        filingPhase,
        sourcePendingIdentifierAllocation:
          filingPhase === "filed" && !applicationNumber.trim() && pendingAllocation,
        applicationNumber: applicationNumber.trim() || null,
        identifierSource: numberSource,
        identifierEffectiveFrom: numberEffectiveFrom,
        markText,
        classNumber: Number(classNumber),
        specification,
        applicantName: applicant,
        evidenceReference: evidence,
      }),
    onSuccess: (result) => {
      toast.success(
        result.duplicate_candidates.length
          ? "Draft created. Review the possible duplicate before marking it filed."
          : "Trademark application created with its canonical identity records.",
      );
      onCreated(result.docket);
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not create the trademark application.")),
  });
  const filedAllocationValid =
    filingPhase !== "filed" || Boolean(applicationNumber.trim()) || pendingAllocation;
  const valid =
    title.trim().length >= 2 &&
    markText.trim().length >= 1 &&
    jurisdiction.trim().length >= 2 &&
    office.trim().length >= 2 &&
    specification.trim().length >= 3 &&
    applicant.trim().length >= 2 &&
    evidence.trim().length >= 3 &&
    filedAllocationValid;

  return (
    <Card>
      <CardHeader><CardTitle as="h2">New trademark application</CardTitle></CardHeader>
      <CardContent>
        <form
          className="grid min-w-0 gap-4 md:grid-cols-2"
          onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}
        >
          <Field label="Docket title"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Matter ID (optional)"><Input value={matterId} onChange={(e) => setMatterId(e.target.value)} /></Field>
          <Field label="Word mark"><Input value={markText} onChange={(e) => setMarkText(e.target.value)} /></Field>
          <Field label="Nice class"><Input type="number" min={1} max={45} value={classNumber} onChange={(e) => setClassNumber(e.target.value)} /></Field>
          <Field label="Goods / services specification"><Input value={specification} onChange={(e) => setSpecification(e.target.value)} /></Field>
          <Field label="Applicant"><Input value={applicant} onChange={(e) => setApplicant(e.target.value)} /></Field>
          <Field label="Representation evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="attachment:… or drive:…" /></Field>
          <Field label="Jurisdiction"><Input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value.toUpperCase())} /></Field>
          <Field label="Registry office"><Input value={office} onChange={(e) => setOffice(e.target.value)} /></Field>
          <Field label="Filing phase">
            <select className={FORM_SELECT_CLASS} value={filingPhase} onChange={(event) => setFilingPhase(event.target.value as typeof filingPhase)}>
              <option value="draft">Draft</option>
              <option value="pre_filing">Pre-filing</option>
              <option value="filed">Filed</option>
            </select>
          </Field>
          <Field label="Application number (optional before filing)"><Input value={applicationNumber} onChange={(event) => { setApplicationNumber(event.target.value); if (event.target.value) setPendingAllocation(false); }} /></Field>
          {applicationNumber ? (
            <>
              <Field label="Number source"><Input value={numberSource} onChange={(event) => setNumberSource(event.target.value)} /></Field>
              <Field label="Effective from"><Input type="date" value={numberEffectiveFrom} onChange={(event) => setNumberEffectiveFrom(event.target.value)} /></Field>
            </>
          ) : null}
          {filingPhase === "filed" && !applicationNumber ? (
            <label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2">
              <input type="checkbox" className="mt-1" checked={pendingAllocation} onChange={(event) => setPendingAllocation(event.target.checked)} />
              Registry source confirms the application number is still pending allocation
            </label>
          ) : null}
          <label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2">
            <input type="checkbox" className="mt-1" checked={restricted} onChange={(event) => setRestricted(event.target.checked)} />
            Restrict this pre-engagement record to explicitly granted members
          </label>
          <div className="flex items-end md:col-span-2"><Button type="submit" disabled={!valid || mutation.isPending}>Create application</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

const IDENTIFIER_LABEL: Record<IpIdentifier["identifier_kind"], string> = {
  application: "Application no.",
  registration: "Registration no.",
  opposition: "Opposition no.",
  rectification: "Rectification no.",
  cancellation: "Cancellation no.",
  non_use_removal: "Non-use proceeding no.",
  appeal: "Appeal no.",
  court: "Court reference",
};

function IdentityCard({ docket, enabled }: { docket: IpDocket; enabled: boolean }) {
  const queryClient = useQueryClient();
  const core = useQuery({
    queryKey: ["ip", "core-records", docket.id],
    queryFn: () => fetchIpCoreRecords(docket.id),
  });
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] });

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-identity-workspace">
      <CardHeader><CardTitle as="h3">Application identity and duplicate review</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {core.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {core.isError ? <QueryErrorState error={core.error} title="Could not load application identity" onRetry={() => core.refetch()} /> : null}
        {core.data?.applications.map((application) => (
          <ApplicationPhaseControl
            key={application.id}
            application={application}
            identifiers={core.data.identifiers}
            enabled={enabled}
            onChanged={refresh}
          />
        ))}
        {core.data && core.data.identifiers.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">No registry identifier has been allocated yet.</p>
        ) : null}
        {core.data?.identifiers.map((identifier) => (
          <IdentifierControl
            key={identifier.id}
            docket={docket}
            identifier={identifier}
            enabled={enabled}
            onChanged={refresh}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function ApplicationPhaseControl({ application, identifiers, enabled, onChanged }: {
  application: IpCoreRecords["applications"][number];
  identifiers: IpIdentifier[];
  enabled: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [phase, setPhase] = useState<"draft" | "pre_filing" | "filed">(
    application.filing_phase as "draft" | "pre_filing" | "filed",
  );
  const [pendingAllocation, setPendingAllocation] = useState(
    application.source_pending_identifier_allocation,
  );
  const confirmedApplicationNumber = identifiers.some(
    (row) =>
      row.application_id === application.id &&
      row.identifier_kind === "application" &&
      row.reconciliation_status === "confirmed" &&
      row.effective_until === null,
  );
  const mutation = useMutation({
    mutationFn: () => updateTrademarkApplicationPhase({
      applicationId: application.id,
      expectedVersion: application.version,
      filingPhase: phase,
      sourcePendingIdentifierAllocation: phase === "filed" && !confirmedApplicationNumber && pendingAllocation,
    }),
    onSuccess: async () => { toast.success("Application filing phase updated."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update the filing phase.")),
  });
  const canApply =
    enabled &&
    phase !== application.filing_phase &&
    (phase !== "filed" || confirmedApplicationNumber || pendingAllocation);

  return (
    <div className="grid min-w-0 gap-3 border-b border-[var(--color-line)] pb-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
      <div className="min-w-0 text-sm">
        <div className="font-semibold">Trademark application</div>
        <div className="text-xs text-[var(--color-mute)]">{application.office} · {application.jurisdiction} · v{application.version}</div>
      </div>
      <Field label="Filing phase">
        <select className={FORM_SELECT_CLASS} value={phase} disabled={!enabled} onChange={(event) => setPhase(event.target.value as typeof phase)}>
          <option value="draft">Draft</option>
          <option value="pre_filing">Pre-filing</option>
          <option value="filed">Filed</option>
        </select>
      </Field>
      <Button size="sm" disabled={!canApply || mutation.isPending} onClick={() => mutation.mutate()}>Update phase</Button>
      {phase === "filed" && !confirmedApplicationNumber ? (
        <label className="flex min-w-0 items-start gap-2 text-xs md:col-span-3">
          <input type="checkbox" checked={pendingAllocation} onChange={(event) => setPendingAllocation(event.target.checked)} />
          Registry source confirms the number is pending allocation
        </label>
      ) : null}
    </div>
  );
}

function IdentifierControl({ docket, identifier, enabled, onChanged }: {
  docket: IpDocket;
  identifier: IpIdentifier;
  enabled: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctedValue, setCorrectedValue] = useState(identifier.raw_value);
  const [correctionReason, setCorrectionReason] = useState("");
  const preview = useQuery({
    queryKey: ["ip", "identifier-duplicates", docket.id, identifier.id],
    queryFn: () => previewIpIdentifierDuplicates(docket.id, identifier.id),
    enabled: identifier.reconciliation_status === "needs_review",
  });
  useEffect(() => {
    if (!candidateId && preview.data?.candidates[0]) {
      setCandidateId(preview.data.candidates[0].identifier_id);
    }
  }, [candidateId, preview.data]);
  const resolve = useMutation({
    mutationFn: (decision: "distinct" | "supersede") => resolveIpIdentifierDuplicate({
      docketId: docket.id,
      identifierId: identifier.id,
      decision,
      decisionToken: preview.data!.decision_token,
      reason,
      supersededByIdentifierId: decision === "supersede" ? candidateId : null,
    }),
    onSuccess: async (_result, decision) => {
      toast.success(decision === "distinct" ? "Identifier confirmed as a separate filing." : "Identifier superseded; both dockets and their evidence remain intact.");
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not resolve the duplicate.")),
  });
  const correct = useMutation({
    mutationFn: () => correctIpIdentifier({
      docketId: docket.id,
      identifier,
      rawValue: correctedValue,
      reason: correctionReason,
      effectiveFrom: TODAY,
    }),
    onSuccess: async (result) => {
      toast.success(result.duplicate_candidates.length ? "Correction saved and flagged for duplicate review." : "Correction saved with the prior value retained in history.");
      setShowCorrection(false);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not correct the identifier.")),
  });

  return (
    <div className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold">{IDENTIFIER_LABEL[identifier.identifier_kind]}</div>
          <div className="break-all font-mono tabular-nums">{identifier.raw_value}</div>
          <div className="mt-1 text-xs text-[var(--color-mute)]">{identifier.office} · {identifier.jurisdiction} · source {identifier.source}</div>
        </div>
        <Badge tone={identifier.reconciliation_status === "confirmed" ? "success" : "warning"}>{identifier.reconciliation_status.replaceAll("_", " ")}</Badge>
      </div>
      {identifier.effective_until ? <p className="mt-2 text-xs text-[var(--color-mute)]">Historical value through {identifier.effective_until}</p> : null}
      {identifier.correction_reason ? <p className="mt-2 text-xs text-[var(--color-mute)]">Correction reason: {identifier.correction_reason}</p> : null}

      {identifier.reconciliation_status === "needs_review" ? (
        <div className="mt-3 flex min-w-0 flex-col gap-3 border-t border-[var(--color-line)] pt-3">
          {preview.isPending ? <Skeleton className="h-16 w-full" /> : null}
          {preview.isError ? <QueryErrorState error={preview.error} title="Could not preview duplicate candidates" onRetry={() => preview.refetch()} /> : null}
          {preview.data ? (
            <>
              <p className="text-xs text-[var(--color-mute)]">This preview changes nothing. Superseding retires this number only; it does not merge or delete either docket.</p>
              {preview.data.blocking_reasons.length ? <p className="text-xs text-red-700">Automatic supersession blocked: {preview.data.blocking_reasons.join(", ").replaceAll("_", " ")}</p> : null}
              {preview.data.candidates.map((candidate) => (
                <label key={candidate.identifier_id} className="flex min-w-0 items-start gap-2 rounded-md bg-[var(--color-bg-2)] p-2">
                  <input type="radio" name={`candidate-${identifier.id}`} checked={candidateId === candidate.identifier_id} onChange={() => setCandidateId(candidate.identifier_id)} />
                  <span className="min-w-0"><strong className="break-words">{candidate.docket_title}</strong><span className="block break-all font-mono text-xs">{candidate.raw_value}</span></span>
                </label>
              ))}
              <Field label="Decision reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap">
                {preview.data.allowed_decisions.includes("distinct") ? <Button size="sm" className="w-full sm:w-auto" disabled={!enabled || reason.trim().length < 5 || resolve.isPending} onClick={() => resolve.mutate("distinct")}>Confirm separate filing</Button> : null}
                {preview.data.allowed_decisions.includes("supersede") ? <Button size="sm" variant="secondary" className="w-full sm:w-auto" disabled={!enabled || !candidateId || reason.trim().length < 5 || resolve.isPending} onClick={() => resolve.mutate("supersede")}>Supersede this number</Button> : null}
              </div>
            </>
          ) : null}
        </div>
      ) : enabled && !identifier.effective_until ? (
        <div className="mt-3">
          {showCorrection ? (
            <form className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); correct.mutate(); }}>
              <Field label={`Corrected ${IDENTIFIER_LABEL[identifier.identifier_kind].toLowerCase()}`}><Input value={correctedValue} onChange={(event) => setCorrectedValue(event.target.value)} /></Field>
              <Field label="Correction reason"><Textarea value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} /></Field>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row md:col-span-2"><Button size="sm" type="submit" disabled={correctedValue.trim() === identifier.raw_value || correctionReason.trim().length < 5 || correct.isPending}>Save correction</Button><Button size="sm" type="button" variant="ghost" onClick={() => setShowCorrection(false)}>Cancel</Button></div>
            </form>
          ) : <Button size="sm" variant="ghost" onClick={() => setShowCorrection(true)}>Correct identifier</Button>}
        </div>
      ) : null}
    </div>
  );
}

function DocketWorkspace({
  docket,
  canWrite,
  canReview,
  canCreateDraft,
  canEditDraft,
  canGenerateDraft,
  canReviewDraft,
  canFinalizeDraft,
  canFinance,
  canProposeRules,
  canActivateRules,
  canManageAccess,
  initialView,
  initialProceedingId,
  initialDraftId,
  currentMembershipId,
  onChanged,
}: {
  docket: IpDocket;
  canWrite: boolean;
  canReview: boolean;
  canCreateDraft: boolean;
  canEditDraft: boolean;
  canGenerateDraft: boolean;
  canReviewDraft: boolean;
  canFinalizeDraft: boolean;
  canFinance: boolean;
  canProposeRules: boolean;
  canActivateRules: boolean;
  canManageAccess: boolean;
  initialView: DocketView;
  initialProceedingId: string | null;
  initialDraftId: string | null;
  currentMembershipId: string | null;
  onChanged: () => Promise<void>;
}) {
  const classes = docket.current_particulars.classes_json;
  const [activeView, setActiveView] = useState<DocketView>(initialView);
  const [focusDraftOnly, setFocusDraftOnly] = useState(
    Boolean(initialProceedingId && initialDraftId),
  );
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

      <Tabs
        value={activeView}
        onValueChange={(value) => setActiveView(value as typeof activeView)}
        className="min-w-0"
      >
        <TabsList className="h-auto w-full min-w-0 flex-wrap sm:w-auto" aria-label="Docket work areas">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="proceedings">Proceedings</TabsTrigger>
          <TabsTrigger value="schedule">Hearings and deadlines</TabsTrigger>
          <TabsTrigger value="access">Access and links</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            <IdentityCard docket={docket} enabled={canWrite} />
            <LifecycleCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <EvidenceCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <CoverageCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <IncidentCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <TitleCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <ObligationCard docket={docket} enabled={canReview} onChanged={onChanged} />
            <CostCard docket={docket} enabled={canFinance} onChanged={onChanged} />
          </div>
        </TabsContent>
        <TabsContent value="proceedings">
          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            <IpOppositionWorkspace
              docket={docket}
              canWrite={canWrite}
              canReview={canReview}
              canCreateDraft={canCreateDraft}
              canEditDraft={canEditDraft}
              canGenerateDraft={canGenerateDraft}
              canReviewDraft={canReviewDraft}
              canFinalizeDraft={canFinalizeDraft}
              currentMembershipId={currentMembershipId}
              initialProceedingId={initialProceedingId}
              initialDraftId={initialDraftId}
              focusDraftOnly={focusDraftOnly}
            />
            {focusDraftOnly ? (
              <div className="flex min-w-0 items-start xl:col-span-2">
                <Button variant="secondary" onClick={() => setFocusDraftOnly(false)}>
                  Open all proceeding tools
                </Button>
              </div>
            ) : (
              <>
                <IpPostRegistrationWorkspace
                  docket={docket}
                  canWrite={canWrite}
                  canReview={canReview}
                  currentMembershipId={currentMembershipId}
                />
                <ProsecutionCard
                  docket={docket}
                  enabled={canWrite}
                  currentMembershipId={currentMembershipId}
                  onChanged={onChanged}
                />
              </>
            )}
          </div>
        </TabsContent>
        <TabsContent value="schedule">
          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            <HearingWorkflowCard
              docket={docket}
              enabled={canWrite}
              currentMembershipId={currentMembershipId}
            />
            <DeadlineWorkspaceCard
              docket={docket}
              enabled={canReview}
              currentMembershipId={currentMembershipId}
              onChanged={onChanged}
            />
            <DeadlineGovernanceCard
              docket={docket}
              canPropose={canProposeRules}
              canActivate={canActivateRules}
              currentMembershipId={currentMembershipId}
            />
          </div>
        </TabsContent>
        <TabsContent value="access">
          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            {canManageAccess ? (
              <IpAccessWorkspace docket={docket} onChanged={onChanged} />
            ) : null}
            <IpMatterLinksPanel docket={docket} canWrite={canWrite} onChanged={onChanged} />
          </div>
        </TabsContent>
      </Tabs>

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

function HearingWorkflowCard({
  docket,
  enabled,
  currentMembershipId,
}: {
  docket: IpDocket;
  enabled: boolean;
  currentMembershipId: string | null;
}) {
  const queryClient = useQueryClient();
  const hearingQueryKey = ["ip", "hearings", docket.id] as const;
  const hearings = useQuery({
    queryKey: hearingQueryKey,
    queryFn: () => fetchIpSharedHearings(docket.id),
  });
  const connections = useQuery({
    queryKey: ["calendar", "connections"],
    queryFn: listCalendarConnections,
  });
  const [hearingOn, setHearingOn] = useState(TODAY);
  const [timeStatus, setTimeStatus] = useState<
    "exact" | "session" | "time_not_published"
  >("time_not_published");
  const [hearingTime, setHearingTime] = useState("10:00");
  const [sessionLabel, setSessionLabel] = useState("Morning board");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [forumName, setForumName] = useState("Trade Marks Registry");
  const [purpose, setPurpose] = useState("Hearing");
  const [mode, setMode] = useState<"physical" | "virtual" | "hybrid" | "unknown">(
    "unknown",
  );
  const [locationText, setLocationText] = useState("");
  const [meetingUrl, setMeetingUrl] = useState("");
  const [source, setSource] = useState("manual");
  const [offsets, setOffsets] = useState("48, 24");
  const [emailReminder, setEmailReminder] = useState(true);
  const [inAppReminder, setInAppReminder] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [rescheduleDates, setRescheduleDates] = useState<Record<string, string>>({});
  const [confirmationTimes, setConfirmationTimes] = useState<Record<string, string>>({});
  const offsetValues = offsets
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isInteger(value) && value >= 0);
  const reminderChannels: Array<"email" | "in_app"> = [
    ...(emailReminder ? (["email"] as const) : []),
    ...(inAppReminder ? (["in_app"] as const) : []),
  ];
  const recipientIds = currentMembershipId ? [currentMembershipId] : [];

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: hearingQueryKey });
  const cacheHearing = (hearing: IpSharedHearing) =>
    queryClient.setQueryData<{ docket_id: string; hearings: IpSharedHearing[] }>(
      hearingQueryKey,
      (current) => ({
        docket_id: docket.id,
        hearings: current?.hearings.some((row) => row.id === hearing.id)
          ? current.hearings.map((row) => (row.id === hearing.id ? hearing : row))
          : [hearing, ...(current?.hearings ?? [])],
      }),
    );
  const create = useMutation({
    mutationFn: () =>
      createIpSharedHearing({
        docketId: docket.id,
        hearingOn,
        timeStatus,
        hearingTime: timeStatus === "exact" ? hearingTime : null,
        sessionLabel: timeStatus === "session" ? sessionLabel : null,
        timezone,
        forumName,
        purpose,
        hearingMode: mode,
        locationText: locationText || null,
        meetingUrl: meetingUrl || null,
        source,
        responsibleMembershipId: currentMembershipId,
        attendeeMembershipIds: recipientIds,
        reminderOffsetsHours: offsetValues,
        reminderChannels,
        reminderRecipientMembershipIds: recipientIds,
      }),
    onSuccess: (hearing) => {
      cacheHearing(hearing);
      setPreviewing(false);
      toast.success("Hearing and idempotent reminders scheduled.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not schedule hearing.")),
  });
  const update = useMutation({
    mutationFn: (input: {
      hearingId: string;
      hearingOn?: string;
      timeStatus?: "exact" | "session" | "time_not_published";
      hearingTime?: string | null;
      sessionLabel?: string | null;
      status?: "scheduled" | "completed" | "adjourned" | "cancelled";
    }) => updateIpSharedHearing({ docketId: docket.id, ...input }),
    onSuccess: (hearing, variables) => {
      cacheHearing(hearing);
      setConfirmationTimes((current) => {
        const next = { ...current };
        delete next[variables.hearingId];
        return next;
      });
      toast.success("Hearing updated; dependent reminders were superseded.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update hearing.")),
  });
  const sync = useMutation({
    mutationFn: ({ provider, hearingId }: { provider: string; hearingId: string }) =>
      provider === "outlook"
        ? syncHearingToOutlook(hearingId)
        : syncHearingToGoogleCalendar(hearingId),
    onSuccess: async () => {
      toast.success("Calendar projection synchronized; CaseOps remains authoritative.");
      await refresh();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Calendar projection could not be synchronized.")),
  });
  const connectedProviders = new Set(
    (connections.data?.connections ?? [])
      .filter((row) => row.status === "connected")
      .map((row) => row.provider),
  );

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-hearing-workflow">
      <CardHeader><CardTitle as="h3">Hearings, reminders, and calendar copies</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <p className="text-sm text-[var(--color-mute)]">
          CaseOps is authoritative. External calendars receive a minimal date-only copy and a
          secure source link; provider edits never alter this docket.
        </p>
        {enabled ? (
          <form
            className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (previewing) create.mutate();
              else setPreviewing(true);
            }}
          >
            <Field label="Hearing date"><Input type="date" value={hearingOn} onChange={(event) => setHearingOn(event.target.value)} /></Field>
            <Field label="Time precision">
              <select className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={timeStatus} onChange={(event) => { setTimeStatus(event.target.value as typeof timeStatus); setPreviewing(false); }}>
                <option value="time_not_published">Time not published</option>
                <option value="session">Session / board</option>
                <option value="exact">Exact time</option>
              </select>
            </Field>
            {timeStatus === "exact" ? <Field label="Exact local time"><Input type="time" value={hearingTime} onChange={(event) => setHearingTime(event.target.value)} /></Field> : null}
            {timeStatus === "session" ? <Field label="Session label"><Input value={sessionLabel} onChange={(event) => setSessionLabel(event.target.value)} /></Field> : null}
            <Field label="IANA timezone"><Input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></Field>
            <Field label="Forum"><Input value={forumName} onChange={(event) => setForumName(event.target.value)} /></Field>
            <Field label="Purpose"><Input value={purpose} onChange={(event) => setPurpose(event.target.value)} /></Field>
            <Field label="Mode">
              <select className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}>
                <option value="unknown">Not confirmed</option><option value="physical">Physical</option><option value="virtual">Virtual</option><option value="hybrid">Hybrid</option>
              </select>
            </Field>
            <Field label="Location"><Input value={locationText} onChange={(event) => setLocationText(event.target.value)} /></Field>
            <Field label="Virtual hearing link"><Input type="url" value={meetingUrl} onChange={(event) => setMeetingUrl(event.target.value)} /></Field>
            <Field label="Source"><Input value={source} onChange={(event) => setSource(event.target.value)} /></Field>
            <Field label="Reminder offsets (hours)"><Input value={offsets} onChange={(event) => setOffsets(event.target.value)} /></Field>
            <fieldset className="min-w-0 rounded-md border border-[var(--color-line)] p-3 sm:col-span-2">
              <legend className="px-1 text-sm font-semibold">Reminder channels</legend>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={emailReminder} onChange={(event) => setEmailReminder(event.target.checked)} /> Email</label>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={inAppReminder} onChange={(event) => setInAppReminder(event.target.checked)} /> In app</label>
              </div>
            </fieldset>
            {previewing ? (
              <div className="min-w-0 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm sm:col-span-2 xl:col-span-4" data-testid="ip-hearing-preview">
                <strong>Confirm reminder policy</strong>
                <div className="mt-1 break-words">{timeStatus === "exact" ? `Exact time ${hearingTime}` : timeStatus === "session" ? `Session: ${sessionLabel}` : "Date-based reminder only; no hearing time will be invented."}</div>
                <div className="mt-1 break-words">Recipients: {recipientIds.join(", ") || "none"} · Offsets: {offsetValues.join(", ") || "none"} hours · Channels: {reminderChannels.join(", ") || "none"}</div>
              </div>
            ) : null}
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:col-span-2 xl:col-span-4">
              <Button className="w-full sm:w-auto" type="submit" disabled={!hearingOn || !forumName.trim() || !purpose.trim() || !offsetValues.length || !reminderChannels.length || !recipientIds.length || create.isPending}>
                {previewing ? "Confirm hearing and reminders" : "Preview recipients and policy"}
              </Button>
              {previewing ? <Button className="w-full sm:w-auto" type="button" variant="secondary" onClick={() => setPreviewing(false)}>Edit details</Button> : null}
            </div>
          </form>
        ) : null}

        {hearings.isPending ? <p className="text-sm">Loading hearings…</p> : null}
        {hearings.isError ? <p className="break-words text-sm text-red-700">{apiErrorMessage(hearings.error, "Hearings could not be loaded.")}</p> : null}
        <div className="flex min-w-0 flex-col gap-3">
          {(hearings.data?.hearings ?? []).map((hearing: IpSharedHearing) => {
            const reminderGenerations = [...new Set(
              hearing.reminders.map((row) => row.schedule_generation),
            )].sort((left, right) => right - left);
            return (
              <article key={hearing.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3">
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h4 className="break-words font-semibold">{hearing.purpose}</h4>
                    <p className="break-words text-xs text-[var(--color-mute)]">{hearing.hearing_on} · {hearing.time_status === "exact" ? hearing.hearing_time : hearing.session_label ?? "Time not published"} · {hearing.timezone} · {hearing.forum_name} · {hearing.hearing_mode}</p>
                    {hearing.time_confirmation_required ? (
                      <p className="mt-1 text-xs font-semibold text-amber-800">Time confirmation pending. Date-based reminders remain active.</p>
                    ) : null}
                  </div>
                  <span className="text-sm font-semibold">{hearing.status}</span>
                </div>
                <div className="mt-3 min-w-0 space-y-3" role="group" aria-label={`Reminder delivery for ${hearing.purpose}`}>
                  {reminderGenerations.map((generation) => {
                    const generationRows = hearing.reminders.filter(
                      (row) => row.schedule_generation === generation,
                    );
                    const replacementGeneration = generationRows.find(
                      (row) => row.replacement_generation !== null,
                    )?.replacement_generation;
                    return (
                      <section key={generation} aria-label={`Reminder generation ${generation}`}>
                        <div className="mb-1 flex min-w-0 flex-wrap items-center gap-2 text-xs font-semibold">
                          <span>Reminder generation {generation}</span>
                          {replacementGeneration ? (
                            <span className="text-[var(--color-mute)]">Superseded by generation {replacementGeneration}</span>
                          ) : generation === hearing.current_schedule_generation ? (
                            <span className="text-emerald-700">Current schedule</span>
                          ) : null}
                        </div>
                        <div className="grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                          {generationRows.map((reminder) => (
                            <div key={reminder.id} className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-2 text-xs">
                              <strong>{reminder.channel}</strong> · {reminder.status}
                              <div className="break-words text-[var(--color-mute)]">{new Date(reminder.scheduled_for).toLocaleString()} · attempts {reminder.attempts}{reminder.last_error ? ` · ${reminder.last_error}` : ""}</div>
                            </div>
                          ))}
                        </div>
                      </section>
                    );
                  })}
                </div>
                <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
                  {hearing.time_confirmation_required ? (
                    <>
                      <Input
                        aria-label={`Published time for ${hearing.purpose}`}
                        className="w-full sm:w-auto"
                        type="time"
                        value={confirmationTimes[hearing.id] ?? ""}
                        onChange={(event) => setConfirmationTimes((current) => ({
                          ...current,
                          [hearing.id]: event.target.value,
                        }))}
                      />
                      <Button
                        className="w-full sm:w-auto"
                        size="sm"
                        variant="secondary"
                        disabled={!confirmationTimes[hearing.id] || update.isPending}
                        onClick={() => update.mutate({
                          hearingId: hearing.id,
                          timeStatus: "exact",
                          hearingTime: confirmationTimes[hearing.id],
                          sessionLabel: null,
                        })}
                      >
                        Confirm published time
                      </Button>
                    </>
                  ) : null}
                  <Input aria-label={`Reschedule ${hearing.purpose}`} className="w-full sm:w-auto" type="date" value={rescheduleDates[hearing.id] ?? hearing.hearing_on} onChange={(event) => setRescheduleDates((current) => ({ ...current, [hearing.id]: event.target.value }))} />
                  <Button className="w-full sm:w-auto" size="sm" variant="secondary" onClick={() => update.mutate({ hearingId: hearing.id, hearingOn: rescheduleDates[hearing.id] ?? hearing.hearing_on })}>Reschedule</Button>
                  <Button className="w-full sm:w-auto" size="sm" variant="secondary" onClick={() => update.mutate({ hearingId: hearing.id, status: "cancelled" })}>Cancel hearing</Button>
                  {connectedProviders.has("outlook") ? <Button className="w-full sm:w-auto" size="sm" variant="secondary" onClick={() => sync.mutate({ provider: "outlook", hearingId: hearing.id })}>Sync Outlook</Button> : null}
                  {connectedProviders.has("google_calendar") ? <Button className="w-full sm:w-auto" size="sm" variant="secondary" onClick={() => sync.mutate({ provider: "google_calendar", hearingId: hearing.id })}>Sync Google Calendar</Button> : null}
                </div>
              </article>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function DeadlineProvenance({
  deadline,
  rule,
  calendar,
}: {
  deadline: IpLegalDeadline;
  rule: IpDeadlineRuleVersion | undefined;
  calendar: IpWorkingCalendarVersion | undefined;
}) {
  const [open, setOpen] = useState(false);
  const dependencies = useQuery({
    queryKey: ["ip", "deadline-dependencies", deadline.id],
    queryFn: () => fetchIpDeadlineDependencies(deadline.id),
    enabled: open,
  });
  const ruleSource = verifiedHttpSource(rule?.source_reference);
  const calendarSource = verifiedHttpSource(calendar?.source_reference);

  return (
    <div className="mt-2 min-w-0 text-xs">
      <div className="flex min-w-0 flex-col gap-1 text-[var(--color-mute)] sm:flex-row sm:flex-wrap">
        <span className="break-words">Governing rule: {deadline.rule_citation}</span>
        {ruleSource ? (
          <a
            className="inline-flex min-w-0 items-center gap-1 break-all font-medium text-[var(--color-accent)] underline-offset-2 hover:underline"
            href={ruleSource}
            target="_blank"
            rel="noreferrer"
          >
            Open verified rule source
            <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
          </a>
        ) : (
          <span className="break-words">Source reference: {rule?.source_reference ?? "Unavailable"}</span>
        )}
        {calendarSource ? (
          <a
            className="inline-flex min-w-0 items-center gap-1 break-all font-medium text-[var(--color-accent)] underline-offset-2 hover:underline"
            href={calendarSource}
            target="_blank"
            rel="noreferrer"
          >
            Open verified calendar source
            <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
          </a>
        ) : null}
      </div>
      <Button
        className="mt-2 w-full sm:w-auto"
        type="button"
        size="sm"
        variant="secondary"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? <ChevronUp className="h-4 w-4" aria-hidden /> : <ChevronDown className="h-4 w-4" aria-hidden />}
        {open ? "Hide calculation provenance" : "View calculation provenance"}
      </Button>
      {open ? (
        <div
          className="mt-2 min-w-0 border-l-2 border-[var(--color-line)] pl-3"
          data-testid={`ip-deadline-provenance-${deadline.id}`}
        >
          {dependencies.isPending ? <p>Loading stored calculation evidence…</p> : null}
          {dependencies.isError ? (
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
              <p className="min-w-0 flex-1 break-words text-red-700">
                {apiErrorMessage(dependencies.error, "Calculation provenance could not be loaded.")}
              </p>
              <Button size="sm" type="button" onClick={() => dependencies.refetch()}>
                Retry provenance
              </Button>
            </div>
          ) : null}
          {dependencies.data ? (
            <>
              <p className="break-words text-[var(--color-mute)]">
                Stored by {dependencies.data.engine_version} from source version {dependencies.data.source_version}.
              </p>
              <ul className="mt-2 flex min-w-0 flex-col gap-2" aria-label="Deadline calculation inputs">
                {dependencies.data.nodes.map((node, index) => (
                  <li key={`${node.kind}-${node.reference_id ?? index}`} className="min-w-0">
                    <span className="font-semibold">{node.label}</span>
                    {node.detail ? <span className="break-words"> · {node.detail}</span> : null}
                    {!node.available ? <span className="font-semibold text-red-700"> · unavailable</span> : null}
                  </li>
                ))}
              </ul>
              {!dependencies.data.nodes.some((node) => node.kind === "extension") ? (
                <p className="mt-2 break-words text-[var(--color-mute)]">
                  No approved extension is included in this calculation. An extension application alone does not move the legal date.
                </p>
              ) : null}
              {dependencies.data.unavailable_inputs.length ? (
                <p className="mt-2 break-words font-semibold text-red-700">
                  Incomplete provenance: {dependencies.data.unavailable_inputs.join(", ")}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function DeadlineWorkspaceCard({
  docket,
  enabled,
  currentMembershipId,
  onChanged,
}: {
  docket: IpDocket;
  enabled: boolean;
  currentMembershipId: string | null;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["ip", "deadline-workspace", docket.id],
    queryFn: () => fetchIpDeadlineWorkspace(docket.id),
  });
  const [title, setTitle] = useState("Respond to official IP event");
  const [baseDate, setBaseDate] = useState(TODAY);
  const [certainty, setCertainty] = useState<
    "certain" | "uncertain" | "conflicting" | "unknown"
  >("certain");
  const [critical, setCritical] = useState(true);
  const [ruleVersionId, setRuleVersionId] = useState("");
  const [calendarVersionId, setCalendarVersionId] = useState("");
  const [primaryId, setPrimaryId] = useState(currentMembershipId ?? "");
  const [backupId, setBackupId] = useState("");
  const [internalTargetOn, setInternalTargetOn] = useState("");
  const [actionDate, setActionDate] = useState("");
  const [actionReason, setActionReason] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [attestation, setAttestation] = useState("");

  const activeRules = workspace.data?.rules.filter((row) => row.status === "active") ?? [];
  const activeCalendars =
    workspace.data?.calendars.filter((row) => row.status === "active") ?? [];
  const selectedRuleId = ruleVersionId || activeRules[0]?.id || "";
  const selectedCalendarId = calendarVersionId || activeCalendars[0]?.id || "";

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["ip", "deadline-workspace", docket.id],
    });
    await onChanged();
  };
  const mutationOptions = {
    onSuccess: async () => {
      toast.success("Legal deadline workspace updated");
      await refresh();
    },
    onError: (error: unknown) =>
      toast.error(apiErrorMessage(error, "The legal deadline change was rejected.")),
  };
  const proposal = useMutation({
    mutationFn: () =>
      proposeIpLegalDeadline({
        docketId: docket.id,
        title,
        ruleVersionId: selectedRuleId,
        calendarVersionId: selectedCalendarId,
        baseDate: baseDate || null,
        baseDateCertainty: certainty,
        critical,
      }),
    ...mutationOptions,
  });

  const responsibilities = (deadline: IpLegalDeadline): IpResponsibilityAssignmentInput[] => {
    const existing = deadline.responsibilities.map((row) => ({
      membership_id: row.membership_id,
      role: row.role,
      accepted: row.accepted,
      replacement_source: "retained_assignment",
      escalation_policy: {},
    }));
    if (existing.length) return existing;
    const values: IpResponsibilityAssignmentInput[] = [];
    if (primaryId.trim()) {
      values.push({
        membership_id: primaryId.trim(),
        role: "primary",
        accepted: true,
        replacement_source: "direct_assignment",
        escalation_policy: { escalate_after_hours: 24 },
      });
    }
    if (backupId.trim()) {
      values.push({
        membership_id: backupId.trim(),
        role: "backup",
        accepted: true,
        replacement_source: "direct_assignment",
        escalation_policy: { escalate_after_hours: 24 },
      });
    }
    return values;
  };

  const confirm = useMutation({
    mutationFn: async (deadline: IpLegalDeadline) => {
      const requiresSourcedCorrection =
        deadline.result_on === null || deadline.certainty === "conflicting";
      let impactToken: string | null = null;
      if (deadline.supersedes_deadline_id) {
        impactToken = (
          await fetchIpDeadlineImpact(deadline.supersedes_deadline_id)
        ).impact_token;
      }
      return confirmIpLegalDeadline({
        deadlineId: deadline.id,
        expectedVersion: deadline.version,
        responsibilities: responsibilities(deadline),
        internalTargetOn: internalTargetOn || null,
        reminderOffsetsDays: [30, 14, 7, 1, 0],
        correctedResultOn:
          requiresSourcedCorrection && actionDate ? actionDate : null,
        correctionReason:
          requiresSourcedCorrection ? actionReason || null : null,
        correctionEvidenceReference:
          requiresSourcedCorrection ? evidenceReference || null : null,
        impactToken,
      });
    },
    ...mutationOptions,
  });
  const recalculate = useMutation({
    mutationFn: (deadline: IpLegalDeadline) =>
      recalculateIpLegalDeadline({
        deadlineId: deadline.id,
        expectedVersion: deadline.version,
        baseDate: baseDate || null,
        certainty,
        reason: actionReason,
        evidenceReference,
      }),
    ...mutationOptions,
  });
  const override = useMutation({
    mutationFn: async (deadline: IpLegalDeadline) => {
      const impact = await fetchIpDeadlineImpact(deadline.id);
      return overrideIpLegalDeadline({
        deadlineId: deadline.id,
        expectedVersion: deadline.version,
        newResultOn: actionDate,
        reason: actionReason,
        evidenceReference,
        impactToken: impact.impact_token,
        responsibilities: responsibilities(deadline),
      });
    },
    ...mutationOptions,
  });
  const complete = useMutation({
    mutationFn: (deadline: IpLegalDeadline) =>
      completeIpLegalDeadline({
        deadlineId: deadline.id,
        expectedVersion: deadline.version,
        evidenceReference,
        attestation,
      }),
    ...mutationOptions,
  });
  const deadlineActionPending =
    confirm.isPending || recalculate.isPending || override.isPending || complete.isPending;

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-deadline-workspace">
      <CardHeader>
        <CardTitle as="h3">Legal deadline control</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
          Calculations are proposals. A legal deadline changes operational work only after an
          authorized user explicitly confirms it.
        </div>
        {workspace.isPending ? <p className="text-sm">Loading deadline evidenceâ€¦</p> : null}
        {workspace.isError ? (
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
            <p className="min-w-0 flex-1 break-words text-sm text-red-700">
              {apiErrorMessage(workspace.error, "Deadline evidence could not be loaded.")}
            </p>
            <Button className="w-full sm:w-auto" onClick={() => workspace.refetch()}>
              Retry deadline workspace
            </Button>
          </div>
        ) : null}
        {workspace.data?.exceptions.length ? (
          <div className="flex min-w-0 flex-col gap-2" data-testid="ip-deadline-exceptions">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">
              Exception queue
            </div>
            {workspace.data.exceptions.map((item) => (
              <div
                key={item.deadline_id}
                className="min-w-0 rounded-lg border border-amber-300 p-3 text-sm"
              >
                <strong className="break-words">{item.exception_kinds.join(" Â· ")}</strong>
                <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
                  {item.result_on ?? "No reliable legal date"} Â· deadline {item.deadline_id}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {enabled ? (
          <form
            className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4"
            onSubmit={(event) => {
              event.preventDefault();
              proposal.mutate();
            }}
          >
            <Field label="Deadline title">
              <Input value={title} onChange={(event) => setTitle(event.target.value)} />
            </Field>
            <Field label="Trigger / base date">
              <Input
                type="date"
                value={baseDate}
                onChange={(event) => setBaseDate(event.target.value)}
              />
            </Field>
            <Field label="Date certainty">
              <select
                className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={certainty}
                onChange={(event) =>
                  setCertainty(event.target.value as typeof certainty)
                }
              >
                <option value="certain">Certain</option>
                <option value="uncertain">Uncertain</option>
                <option value="conflicting">Conflicting</option>
                <option value="unknown">Unknown</option>
              </select>
            </Field>
            <Field label="Active rule version">
              <select
                className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={selectedRuleId}
                onChange={(event) => setRuleVersionId(event.target.value)}
              >
                {activeRules.map((row) => (
                  <option key={row.id} value={row.id}>{row.key} v{row.version}</option>
                ))}
              </select>
            </Field>
            <Field label="Active working calendar">
              <select
                className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={selectedCalendarId}
                onChange={(event) => setCalendarVersionId(event.target.value)}
              >
                {activeCalendars.map((row) => (
                  <option key={row.id} value={row.id}>{row.name} v{row.version}</option>
                ))}
              </select>
            </Field>
            <label className="flex min-w-0 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={critical}
                onChange={(event) => setCritical(event.target.checked)}
              />
              Critical legal deadline
            </label>
            <div className="flex min-w-0 items-end sm:col-span-2">
              <Button
                className="w-full sm:w-auto"
                type="submit"
                disabled={
                  !title.trim() ||
                  !selectedRuleId ||
                  !selectedCalendarId ||
                  proposal.isPending ||
                  deadlineActionPending
                }
              >
                Calculate deadline proposal
              </Button>
            </div>
          </form>
        ) : null}

        {enabled && workspace.data?.deadlines.length ? (
          <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Field label="Responsible lawyer" htmlFor="deadline-primary-owner">
              <PersonPicker id="deadline-primary-owner" value={primaryId} onChange={setPrimaryId} />
            </Field>
            <Field label="Backup" htmlFor="deadline-backup-owner">
              <PersonPicker
                id="deadline-backup-owner"
                value={backupId}
                onChange={setBackupId}
                excludeMembershipIds={[primaryId]}
                placeholder="No backup"
              />
            </Field>
            <Field label="Internal target">
              <Input
                type="date"
                value={internalTargetOn}
                onChange={(event) => setInternalTargetOn(event.target.value)}
              />
            </Field>
            <Field label="Corrected / override date">
              <Input
                type="date"
                value={actionDate}
                onChange={(event) => setActionDate(event.target.value)}
              />
            </Field>
            <Field label="Action reason">
              <Input
                value={actionReason}
                onChange={(event) => setActionReason(event.target.value)}
                placeholder="Verified source changed the dateâ€¦"
              />
            </Field>
            <Field label="Evidence reference">
              <Input
                value={evidenceReference}
                onChange={(event) => setEvidenceReference(event.target.value)}
                placeholder="attachment:official-source"
              />
            </Field>
            <Field label="Completion attestation">
              <Input
                value={attestation}
                onChange={(event) => setAttestation(event.target.value)}
                placeholder="Verified official filing receiptâ€¦"
              />
            </Field>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-col gap-3">
          {workspace.data?.deadlines.map((deadline) => {
            const governingRule = workspace.data.rules.find(
              (row) => row.id === deadline.rule_version_id,
            );
            const governingCalendar = workspace.data.calendars.find(
              (row) => row.id === deadline.calendar_version_id,
            );
            return (
              <div
                key={deadline.id}
                className="min-w-0 rounded-lg border border-[var(--color-line)] p-3"
                data-testid={`ip-legal-deadline-${deadline.id}`}
              >
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="break-words font-semibold">{deadline.title}</div>
                  <div className="mt-1 break-words text-sm">
                    {deadline.result_on ?? "Provisional â€” source date unresolved"} Â· {deadline.state} Â· v{deadline.version}
                  </div>
                  <div className="mt-2 break-words text-xs text-[var(--color-mute)]">
                    {deadline.explanation}
                  </div>
                  <DeadlineProvenance
                    deadline={deadline}
                    rule={governingRule}
                    calendar={governingCalendar}
                  />
                  {deadline.certainty === "conflicting" ? (
                    <div
                      className="mt-2 min-w-0 border-l-2 border-amber-400 pl-3 text-xs"
                      data-testid={`ip-deadline-rule-conflict-${deadline.id}`}
                    >
                      <p className="font-semibold text-amber-900">
                        Conflicting source evidence blocks confirmation until a sourced correction is recorded.
                      </p>
                      <ul className="mt-1 flex min-w-0 flex-col gap-1">
                        {workspace.data.rules.map((row) => (
                          <li key={row.id} className="break-words">
                            {row.key} v{row.version} · {row.status} · {row.source_reference}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
                {deadline.is_critical ? (
                  <span className="rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-800">
                    Critical
                  </span>
                ) : null}
              </div>
              {enabled ? (
                <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
                  {deadline.state === "candidate" || deadline.state === "provisional" ? (
                    <Button
                      className="w-full sm:w-auto"
                      size="sm"
                      disabled={
                        !primaryId.trim() ||
                        (deadline.is_critical && !backupId.trim()) ||
                        ((deadline.result_on === null || deadline.certainty === "conflicting") &&
                          (!actionDate || !actionReason.trim() || !evidenceReference.trim())) ||
                        deadlineActionPending
                      }
                      onClick={() => confirm.mutate(deadline)}
                    >
                      Confirm legal deadline
                    </Button>
                  ) : null}
                  {deadline.state === "confirmed" || deadline.state === "overdue" ? (
                    <>
                      <Button
                        className="w-full sm:w-auto"
                        size="sm"
                        variant="secondary"
                        disabled={
                          !baseDate || !actionReason.trim() || !evidenceReference.trim() || deadlineActionPending
                        }
                        onClick={() => recalculate.mutate(deadline)}
                      >
                        Propose recalculation
                      </Button>
                      <Button
                        className="w-full sm:w-auto"
                        size="sm"
                        variant="secondary"
                        disabled={
                          !actionDate ||
                          !actionReason.trim() ||
                          !evidenceReference.trim() ||
                          deadlineActionPending
                        }
                        onClick={() => override.mutate(deadline)}
                      >
                        Preview impact and override
                      </Button>
                      <Button
                        className="w-full sm:w-auto"
                        size="sm"
                        disabled={
                          !evidenceReference.trim() || !attestation.trim() || deadlineActionPending
                        }
                        onClick={() => complete.mutate(deadline)}
                      >
                        Complete with legal evidence
                      </Button>
                    </>
                  ) : null}
                </div>
              ) : null}
              </div>
            );
          })}
          {workspace.data && workspace.data.deadlines.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">No legal deadline proposals yet.</p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function DeadlineGovernanceCard({
  docket,
  canPropose,
  canActivate,
  currentMembershipId,
}: {
  docket: IpDocket;
  canPropose: boolean;
  canActivate: boolean;
  currentMembershipId: string | null;
}) {
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["ip", "deadline-workspace", docket.id],
    queryFn: () => fetchIpDeadlineWorkspace(docket.id),
  });
  const [calendarKey, setCalendarKey] = useState("ip-india-working-calendar");
  const [calendarName, setCalendarName] = useState("IP India working calendar");
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [office, setOffice] = useState("IP India");
  const [holidays, setHolidays] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [sourceHash, setSourceHash] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(TODAY);
  const [governanceReason, setGovernanceReason] = useState("");
  const [ruleKey, setRuleKey] = useState("in-tm-response-deadline");
  const [triggerKind, setTriggerKind] = useState("examination_report_received");
  const [durationValue, setDurationValue] = useState("30");
  const [ruleCitation, setRuleCitation] = useState("");
  const [fixtureBaseDate, setFixtureBaseDate] = useState(TODAY);
  const [fixtureExpectedDate, setFixtureExpectedDate] = useState("");
  const [reviewerId, setReviewerId] = useState("");

  const activeCalendar = workspace.data?.calendars.find((row) => row.status === "active");
  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["ip", "deadline-workspace", docket.id],
    });
  };
  const result = {
    onSuccess: async () => {
      toast.success("Deadline governance record updated");
      await refresh();
    },
    onError: (error: unknown) =>
      toast.error(apiErrorMessage(error, "Deadline governance rejected the change.")),
  };
  const proposeCalendar = useMutation({
    mutationFn: () =>
      proposeIpWorkingCalendar({
        key: calendarKey,
        name: calendarName,
        jurisdiction,
        office,
        timezone: "Asia/Kolkata",
        holidays: holidays
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        sourceReference,
        sourceHash,
        effectiveFrom,
      }),
    ...result,
  });
  const activateCalendar = useMutation({
    mutationFn: (id: string) =>
      activateIpWorkingCalendar({
        calendarVersionId: id,
        reason: governanceReason,
        conflictReviewed: true,
      }),
    ...result,
  });
  const proposeRule = useMutation({
    mutationFn: () => {
      if (!activeCalendar) throw new Error("Activate a working calendar first.");
      const calculation = {
        deadline_kind: "legal_deadline",
        trigger_kind: triggerKind,
        base_date: fixtureBaseDate,
        base_date_certainty: "certain",
        duration_value: Number(durationValue),
        duration_unit: "days",
        calendar_method: "business_days",
        direction: "after",
        include_base_date: false,
        next_working_day: true,
        extension_days: 0,
        rule_version_id: "governance-fixture-rule",
        rule_citation: ruleCitation,
        source_version: "governance-fixture-source",
        engine_version: "caseops-ip-deadline-v1",
        calendar: {
          calendar_version_id: activeCalendar.id,
          timezone: activeCalendar.timezone,
          weekend_days: activeCalendar.weekend_days,
          holidays: activeCalendar.holidays,
          exceptional_working_days: activeCalendar.exceptional_working_days,
          source_reference: activeCalendar.source_reference,
          source_hash: activeCalendar.source_hash,
        },
      };
      return proposeIpDeadlineRule({
        key: ruleKey,
        jurisdiction,
        office,
        rightKind: "trademark",
        stage: "examination",
        sourceRecordId: `verified-source-${effectiveFrom}`,
        sourceReference,
        sourceHash,
        effectiveFrom,
        triggerKind,
        durationValue: Number(durationValue),
        calendarMethod: "business_days",
        ruleCitation,
        fixtureCalculation: calculation,
        fixtureExpectedState: "candidate",
        fixtureExpectedResultOn: fixtureExpectedDate || null,
      });
    },
    ...result,
  });
  const activateRule = useMutation({
    mutationFn: (id: string) =>
      activateIpDeadlineRule({
        ruleVersionId: id,
        reviewerMembershipId: reviewerId,
        impactAcknowledged: true,
        impactReason: governanceReason,
      }),
    ...result,
  });
  const disableRule = useMutation({
    mutationFn: async (id: string) => {
      const impact = await fetchIpDeadlineRuleImpact(id);
      return transitionIpDeadlineRule({
        ruleVersionId: id,
        impactToken: impact.impact_token,
        reason: governanceReason,
        emergencyDisable: true,
      });
    },
    ...result,
  });

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-deadline-governance">
      <CardHeader><CardTitle as="h3">Rule and calendar governance</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <p className="text-sm text-[var(--color-mute)]">
          Versioned sources require independent approval and server-evaluated fixtures. The
          proposer cannot approve the same calendar, and rule proposal, fixture review, and
          legal activation must use separate memberships.
        </p>
        {canPropose ? (
          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            <form
              className="grid min-w-0 gap-3 sm:grid-cols-2"
              onSubmit={(event) => { event.preventDefault(); proposeCalendar.mutate(); }}
            >
              <div className="sm:col-span-2 text-sm font-semibold">Propose working calendar</div>
              <Field label="Calendar key"><Input value={calendarKey} onChange={(e) => setCalendarKey(e.target.value)} /></Field>
              <Field label="Calendar name"><Input value={calendarName} onChange={(e) => setCalendarName(e.target.value)} /></Field>
              <Field label="Jurisdiction"><Input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} /></Field>
              <Field label="Office"><Input value={office} onChange={(e) => setOffice(e.target.value)} /></Field>
              <Field label="Holiday dates (comma separated)"><Input value={holidays} onChange={(e) => setHolidays(e.target.value)} placeholder="2026-01-26, 2026-08-15" /></Field>
              <Field label="Effective from"><Input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} /></Field>
              <Field label="Official source reference"><Input value={sourceReference} onChange={(e) => setSourceReference(e.target.value)} /></Field>
              <Field label="Source SHA-256"><Input value={sourceHash} onChange={(e) => setSourceHash(e.target.value)} /></Field>
              <div className="sm:col-span-2"><Button className="w-full sm:w-auto" type="submit" disabled={!sourceReference || sourceHash.length !== 64 || proposeCalendar.isPending}>Propose calendar version</Button></div>
            </form>
            <form
              className="grid min-w-0 gap-3 sm:grid-cols-2"
              onSubmit={(event) => { event.preventDefault(); proposeRule.mutate(); }}
            >
              <div className="sm:col-span-2 text-sm font-semibold">Propose tested deadline rule</div>
              <Field label="Rule key"><Input value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} /></Field>
              <Field label="Trigger kind"><Input value={triggerKind} onChange={(e) => setTriggerKind(e.target.value)} /></Field>
              <Field label="Business-day duration"><Input type="number" min={0} value={durationValue} onChange={(e) => setDurationValue(e.target.value)} /></Field>
              <Field label="Rule citation"><Input value={ruleCitation} onChange={(e) => setRuleCitation(e.target.value)} /></Field>
              <Field label="Fixture base date"><Input type="date" value={fixtureBaseDate} onChange={(e) => setFixtureBaseDate(e.target.value)} /></Field>
              <Field label="Expected fixture date"><Input type="date" value={fixtureExpectedDate} onChange={(e) => setFixtureExpectedDate(e.target.value)} /></Field>
              <div className="sm:col-span-2"><Button className="w-full sm:w-auto" type="submit" disabled={!activeCalendar || !ruleCitation || !fixtureExpectedDate || !sourceReference || sourceHash.length !== 64 || proposeRule.isPending}>Propose rule and fixture</Button></div>
            </form>
          </div>
        ) : null}

        {canPropose || canActivate ? (
          <div className="grid min-w-0 gap-3 sm:grid-cols-3">
            <Field label="Independent fixture reviewer" htmlFor="rule-fixture-reviewer">
              <PersonPicker id="rule-fixture-reviewer" value={reviewerId} onChange={setReviewerId} />
            </Field>
            <Field label="Governance / impact reason">
              <Input value={governanceReason} onChange={(event) => setGovernanceReason(event.target.value)} />
            </Field>
            <div className="flex items-end text-xs text-[var(--color-mute)]">
              Current actor: {currentMembershipId ?? "unavailable"}
            </div>
          </div>
        ) : null}

        <div className="grid min-w-0 gap-3 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Calendar versions</div>
            {workspace.data?.calendars.map((row) => (
              <div key={row.id} className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm">
                <div className="break-words font-semibold">{row.name} v{row.version}</div>
                <div className="mt-1 break-words text-xs text-[var(--color-mute)]">{row.status} Â· {row.source_reference}</div>
                {canActivate && row.status === "candidate" ? (
                  <Button className="mt-3 w-full sm:w-auto" size="sm" disabled={governanceReason.trim().length < 5 || activateCalendar.isPending} onClick={() => activateCalendar.mutate(row.id)}>Independently activate calendar</Button>
                ) : null}
              </div>
            ))}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Rule versions</div>
            {workspace.data?.rules.map((row) => (
              <div key={row.id} className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm">
                <div className="break-words font-semibold">{row.key} v{row.version}</div>
                <div className="mt-1 break-words text-xs text-[var(--color-mute)]">{row.status} Â· {row.source_reference}</div>
                {canActivate ? (
                  <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
                    {row.status === "candidate" ? (
                      <Button className="w-full sm:w-auto" size="sm" disabled={!reviewerId || activateRule.isPending} onClick={() => activateRule.mutate(row.id)}>Run fixtures and activate rule</Button>
                    ) : null}
                    {row.status === "active" ? (
                      <Button className="w-full sm:w-auto" size="sm" variant="secondary" disabled={governanceReason.trim().length < 5 || disableRule.isPending} onClick={() => disableRule.mutate(row.id)}>Preview impact and emergency-disable</Button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

const EVENT_KINDS = [
  "filing",
  "formalities",
  "examination_report",
  "response",
  "show_cause_hearing",
  "acceptance",
  "publication",
  "registration",
  "renewal",
  "refusal",
  "abandonment",
  "restoration",
] as const;

function localDateTimeValue() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function ProsecutionCard({
  docket,
  enabled,
  currentMembershipId,
  onChanged,
}: {
  docket: IpDocket;
  enabled: boolean;
  currentMembershipId: string | null;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const prosecution = useQuery({
    queryKey: ["ip", "prosecution", docket.id],
    queryFn: () => fetchIpProsecutionWorkspace(docket.id),
  });
  const core = useQuery({
    queryKey: ["ip", "core-records", docket.id],
    queryFn: () => fetchIpCoreRecords(docket.id),
  });
  const [applicationId, setApplicationId] = useState("");
  const applications = core.data?.applications ?? [];
  const application =
    applications.find((candidate) => candidate.id === applicationId) ??
    applications[0] ??
    null;
  useEffect(() => {
    if (!applicationId && applications[0]) setApplicationId(applications[0].id);
  }, [applicationId, applications]);
  const [eventKind, setEventKind] = useState<(typeof EVENT_KINDS)[number]>("formalities");
  const [effectiveAt, setEffectiveAt] = useState(localDateTimeValue);
  const [reason, setReason] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [documentRef, setDocumentRef] = useState("");
  const [supersedesEventId, setSupersedesEventId] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [reconcilesEventId, setReconcilesEventId] = useState("");
  const [reconciliationDecision, setReconciliationDecision] = useState<
    "" | "same_fact" | "keep_separate" | "reject_candidate"
  >("");
  const [eventSource, setEventSource] = useState<"manual" | "registry">("manual");
  const [sourceReference, setSourceReference] = useState("");
  const [backdatedAcknowledged, setBackdatedAcknowledged] = useState(false);
  const [correspondenceDirection, setCorrespondenceDirection] = useState<
    "none" | "inward" | "outward"
  >("none");
  const [receivedAt, setReceivedAt] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [preparedAt, setPreparedAt] = useState("");
  const [approvedAt, setApprovedAt] = useState("");
  const [filedAt, setFiledAt] = useState("");
  const [acceptedAt, setAcceptedAt] = useState("");
  const correspondence = correspondenceDirection === "none"
    ? null
    : {
        direction: correspondenceDirection,
        received_at: receivedAt ? new Date(receivedAt).toISOString() : null,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
        prepared_at: preparedAt ? new Date(preparedAt).toISOString() : null,
        approved_at: approvedAt ? new Date(approvedAt).toISOString() : null,
        filed_at: filedAt ? new Date(filedAt).toISOString() : null,
        accepted_at: acceptedAt ? new Date(acceptedAt).toISOString() : null,
      };
  const eventInput: IpDocketEventInput | null = currentMembershipId && effectiveAt
    ? {
        lifecycleVersion: docket.lifecycle_version,
        applicationId: application?.id ?? null,
        applicationVersion: application?.version ?? null,
        eventKind,
        effectiveAt: new Date(effectiveAt).toISOString(),
        responsibleMembershipId: currentMembershipId,
        reason,
        evidenceRefs: evidenceRef.trim() ? [evidenceRef.trim()] : [],
        documentRefs: documentRef.trim() ? [documentRef.trim()] : [],
        source: eventSource,
        sourceReference: sourceReference.trim() || null,
        candidateStatus: reconcilesEventId ? "reconciled" : "confirmed",
        supersedesEventId: supersedesEventId || null,
        correctionReason: correctionReason.trim() || null,
        reconcilesEventId: reconcilesEventId || null,
        reconciliationDecision: reconciliationDecision || null,
        acknowledgedExceptionCodes: backdatedAcknowledged
          ? ["backdated_recalculation_review_required"]
          : [],
        correspondence,
      }
    : null;
  const inputSignature = JSON.stringify(
    eventInput
      ? { ...eventInput, acknowledgedExceptionCodes: [] }
      : null,
  );
  const [previewedSignature, setPreviewedSignature] = useState<string | null>(null);
  const preview = useMutation({
    mutationFn: () => previewIpDocketEvent(docket.id, eventInput!),
    onSuccess: () => setPreviewedSignature(inputSignature),
    onError: (error) => toast.error(apiErrorMessage(error, "Could not preview the prosecution event.")),
  });
  const commit = useMutation({
    mutationFn: () => appendIpDocketEvent(docket.id, eventInput!),
    onSuccess: async () => {
      toast.success("Prosecution event recorded in the immutable timeline.");
      setPreviewedSignature(null);
      preview.reset();
      setReason("");
      setEvidenceRef("");
      setDocumentRef("");
      setSupersedesEventId("");
      setCorrectionReason("");
      setReconcilesEventId("");
      setReconciliationDecision("");
      setEventSource("manual");
      setSourceReference("");
      setBackdatedAcknowledged(false);
      setCorrespondenceDirection("none");
      setReceivedAt("");
      setDueAt("");
      setPreparedAt("");
      setApprovedAt("");
      setFiledAt("");
      setAcceptedAt("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip", "prosecution", docket.id] }),
        queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] }),
        onChanged(),
      ]);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the prosecution event.")),
  });
  const valid = Boolean(
    eventInput &&
    effectiveAt &&
    (eventSource === "registry" || reason.trim().length >= 5) &&
    (eventSource !== "registry" || sourceReference.trim()) &&
    (!supersedesEventId || correctionReason.trim().length >= 5) &&
    (!reconcilesEventId || reconciliationDecision) &&
    (correspondenceDirection === "none" ||
      receivedAt || dueAt || preparedAt || approvedAt || filedAt || acceptedAt),
  );
  const previewCurrent = previewedSignature === inputSignature ? preview.data : undefined;
  const commitBlocked = Boolean(
    !previewCurrent ||
    (previewCurrent.backdated && !backdatedAcknowledged) ||
    (previewCurrent.duplicate_candidate_ids.length > 0 && !reconcilesEventId),
  );

  return (
    <Card className="min-w-0" data-testid="ip-prosecution-workspace">
      <CardHeader><CardTitle as="h3">Prosecution events</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {prosecution.isPending ? <p className="text-sm">Loading prosecution timeline…</p> : null}
        {prosecution.isError ? <p className="text-sm text-red-700">Prosecution data is unavailable; event entry remains fail-closed.</p> : null}
        {prosecution.data ? (
          <>
            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
              <Metric label="Current phase" value={prosecution.data.current_phase.replaceAll("_", " ")} icon={Scale} />
              <Metric label="Registry freshness" value={prosecution.data.registry_freshness.replaceAll("_", " ")} icon={FileCheck2} />
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-2 text-xs">
              <div>Operational completion: <strong>{prosecution.data.operational_completion_count}</strong></div>
              <div>Filing evidence: <strong>{prosecution.data.filing_evidence_count}</strong></div>
              <div>Registry acceptance: <strong>{prosecution.data.registry_acceptance_count}</strong></div>
              <div>Final disposition: <strong>{prosecution.data.final_disposition_count}</strong></div>
            </div>
            {prosecution.data.data_quality_gaps.length || prosecution.data.unconfirmed_deadline_refs.length ? (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                Review required: {[...prosecution.data.data_quality_gaps, ...prosecution.data.unconfirmed_deadline_refs].join(", ")}
              </div>
            ) : null}
          </>
        ) : null}

        {enabled ? (
          <form className="grid min-w-0 gap-3" onSubmit={(event) => { event.preventDefault(); preview.mutate(); }}>
            {applications.length ? (
              <Field label="Application">
                <select
                  className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={application?.id ?? ""}
                  onChange={(event) => setApplicationId(event.target.value)}
                >
                  {applications.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {[candidate.jurisdiction, candidate.office, candidate.filing_phase]
                        .filter(Boolean)
                        .join(" · ")}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {supersedesEventId ? (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                Correction will supersede event {supersedesEventId}; the original remains in history.
              </div>
            ) : null}
            {reconcilesEventId ? (
              <div className="rounded-md border border-blue-300 bg-blue-50 p-3 text-xs text-blue-950">
                Reconciliation will append a decision for event {reconcilesEventId}.
              </div>
            ) : null}
            <Field label="Event type">
              <select className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={eventKind} onChange={(event) => setEventKind(event.target.value as typeof eventKind)}>
                {EVENT_KINDS.map((kind) => <option key={kind} value={kind}>{kind.replaceAll("_", " ")}</option>)}
              </select>
            </Field>
            <Field label="Effective date and time"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></Field>
            <Field label="Reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            {eventSource === "registry" ? (
              <Field label="Registry source reference">
                <Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} />
              </Field>
            ) : null}
            {supersedesEventId ? (
              <Field label="Correction reason">
                <Textarea value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} />
              </Field>
            ) : null}
            {reconcilesEventId ? (
              <Field label="Reconciliation decision">
                <select
                  className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={reconciliationDecision}
                  onChange={(event) => setReconciliationDecision(event.target.value as typeof reconciliationDecision)}
                >
                  <option value="">Select decision</option>
                  <option value="same_fact">Same legal fact</option>
                  <option value="keep_separate">Keep separate</option>
                  <option value="reject_candidate">Reject candidate</option>
                </select>
              </Field>
            ) : null}
            <Field label="Evidence reference"><Input value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)} placeholder="attachment:…" /></Field>
            <Field label="Document reference"><Input value={documentRef} onChange={(event) => setDocumentRef(event.target.value)} placeholder="attachment:…" /></Field>
            <Field label="Correspondence direction">
              <select
                className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={correspondenceDirection}
                onChange={(event) => setCorrespondenceDirection(event.target.value as typeof correspondenceDirection)}
              >
                <option value="none">Not linked</option>
                <option value="inward">Inward registry communication</option>
                <option value="outward">Outward response</option>
              </select>
            </Field>
            {correspondenceDirection !== "none" ? (
              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <Field label="Received at"><Input type="datetime-local" value={receivedAt} onChange={(event) => setReceivedAt(event.target.value)} /></Field>
                <Field label="Due at"><Input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></Field>
                <Field label="Prepared at"><Input type="datetime-local" value={preparedAt} onChange={(event) => setPreparedAt(event.target.value)} /></Field>
                <Field label="Approved at"><Input type="datetime-local" value={approvedAt} onChange={(event) => setApprovedAt(event.target.value)} /></Field>
                <Field label="Filed at"><Input type="datetime-local" value={filedAt} onChange={(event) => setFiledAt(event.target.value)} /></Field>
                <Field label="Accepted at"><Input type="datetime-local" value={acceptedAt} onChange={(event) => setAcceptedAt(event.target.value)} /></Field>
              </div>
            ) : null}
            <p className="text-xs text-[var(--color-mute)]">A checklist or operational task is not filing evidence and never proves registry acceptance.</p>
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={!valid || preview.isPending}>Preview prosecution event</Button>
              <Button size="sm" className="w-full sm:w-auto" type="button" onClick={() => commit.mutate()} disabled={commitBlocked || commit.isPending}>Record prosecution event</Button>
              {supersedesEventId || reconcilesEventId ? (
                <Button
                  size="sm"
                  className="w-full sm:w-auto"
                  variant="ghost"
                  type="button"
                  onClick={() => {
                    setSupersedesEventId("");
                    setCorrectionReason("");
                    setReconcilesEventId("");
                    setReconciliationDecision("");
                    setEventSource("manual");
                    setSourceReference("");
                    setPreviewedSignature(null);
                    preview.reset();
                  }}
                >
                  Cancel exception flow
                </Button>
              ) : null}
            </div>
          </form>
        ) : <p className="text-xs text-[var(--color-mute)]">IP write permission is required to record an event.</p>}

        {previewCurrent ? (
          <div className="rounded-md border border-[var(--color-line)] p-3 text-xs" data-testid="ip-event-preview">
            <div className="font-semibold">Preview only · {previewCurrent.current_phase} → {previewCurrent.proposed_phase ?? "unchanged"}</div>
            <div className="mt-1">Backdated recalculation: {previewCurrent.recalculation_required ? "required" : "not required"}</div>
            {previewCurrent.backdated ? (
              <label className="mt-2 flex min-h-9 items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-amber-950">
                <input
                  type="checkbox"
                  checked={backdatedAcknowledged}
                  onChange={(event) => setBackdatedAcknowledged(event.target.checked)}
                />
                <span>I reviewed the recalculation preview and later accepted events will remain current.</span>
              </label>
            ) : null}
            {previewCurrent.duplicate_candidate_ids.length && !reconcilesEventId ? (
              <div className="mt-2 grid gap-2 rounded-md border border-blue-300 bg-blue-50 p-2 text-blue-950">
                <strong>Possible duplicate event</strong>
                <select
                  aria-label="Duplicate event"
                  className="h-9 min-w-0 w-full rounded-md border border-blue-300 bg-white px-2"
                  value={reconcilesEventId}
                  onChange={(event) => {
                    setReconcilesEventId(event.target.value);
                    setReconciliationDecision(event.target.value ? "keep_separate" : "");
                  }}
                >
                  <option value="">Select the event to reconcile</option>
                  {previewCurrent.duplicate_candidate_ids.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
              </div>
            ) : null}
            <ul className="mt-2 grid gap-1">
              {previewCurrent.checklist.map((item) => <li key={item.key}>{item.satisfied ? "✓" : "○"} {item.label}</li>)}
            </ul>
            {previewCurrent.unresolved_exception_codes.length ? (
              <div className="mt-2 break-words text-amber-800">
                Exceptions: {previewCurrent.unresolved_exception_codes.join(", ")}
              </div>
            ) : null}
          </div>
        ) : null}

        {prosecution.data?.events.length ? (
          <ol className="grid min-w-0 gap-2" aria-label="Prosecution event timeline">
            {prosecution.data.events.map((event) => {
              const eventCorrespondence = event.payload_json.correspondence as
                | { direction?: string; received_at?: string | null; filed_at?: string | null }
                | undefined;
              return (
                <li key={event.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-xs">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <strong>#{event.sequence} {event.event_kind.replaceAll("_", " ")}</strong>
                    <Badge tone={event.candidate_status === "candidate" ? "warning" : undefined}>
                      {event.candidate_status}
                    </Badge>
                  </div>
                  <div className="mt-1 break-words">{event.source} · {new Date(event.effective_at).toLocaleString()} · {event.before_phase ?? "—"} → {event.after_phase ?? "—"}</div>
                  {event.reason ? <div className="mt-1 break-words">{event.reason}</div> : null}
                  {event.supersedes_event_id ? <div className="mt-1 break-words text-amber-800">Supersedes {event.supersedes_event_id}</div> : null}
                  {event.reconciles_event_id ? <div className="mt-1 break-words text-blue-800">{event.reconciliation_decision?.replaceAll("_", " ")} · reconciles {event.reconciles_event_id}</div> : null}
                  {eventCorrespondence?.direction ? (
                    <div className="mt-1 break-words text-[var(--color-mute)]">
                      {eventCorrespondence.direction} correspondence
                      {eventCorrespondence.received_at ? ` · received ${new Date(eventCorrespondence.received_at).toLocaleString()}` : ""}
                      {eventCorrespondence.filed_at ? ` · filed ${new Date(eventCorrespondence.filed_at).toLocaleString()}` : ""}
                    </div>
                  ) : null}
                  {event.document_refs_json.length || event.resulting_deadline_refs_json.length ? (
                    <div className="mt-1 break-words text-[var(--color-mute)]">
                      {[...event.document_refs_json, ...event.resulting_deadline_refs_json].join(" · ")}
                    </div>
                  ) : null}
                  {enabled ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {EVENT_KINDS.includes(event.event_kind as typeof eventKind) ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          type="button"
                          onClick={() => {
                            if (event.application_id) setApplicationId(event.application_id);
                            setEventKind(event.event_kind as typeof eventKind);
                            setEffectiveAt(localDateTimeValue());
                            setEventSource("manual");
                            setSupersedesEventId(event.id);
                            setCorrectionReason("");
                            setReconcilesEventId("");
                            setReconciliationDecision("");
                            setReason(`Correct event ${event.sequence}.`);
                            setBackdatedAcknowledged(false);
                            setPreviewedSignature(null);
                            preview.reset();
                          }}
                        >
                          Correct event
                        </Button>
                      ) : null}
                      {event.candidate_status === "candidate" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          type="button"
                          onClick={() => {
                            if (event.application_id) setApplicationId(event.application_id);
                            setEventKind(event.event_kind as typeof eventKind);
                            setEffectiveAt(localDateTimeValue());
                            setEventSource("registry");
                            setSourceReference(event.source_reference ?? "");
                            setReconcilesEventId(event.id);
                            setReconciliationDecision("same_fact");
                            setSupersedesEventId("");
                            setCorrectionReason("");
                            setReason("");
                            setBackdatedAcknowledged(false);
                            setPreviewedSignature(null);
                            preview.reset();
                          }}
                        >
                          Reconcile candidate
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : <p className="text-xs text-[var(--color-mute)]">No prosecution events have been recorded.</p>}
      </CardContent>
    </Card>
  );
}

function LifecycleCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [toStatus, setToStatus] = useState<"abandoned" | "transferred" | "retired" | "closed">("closed");
  const [effectiveAt, setEffectiveAt] = useState(localDateTimeValue);
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [successorDocketId, setSuccessorDocketId] = useState("");
  const [secondApproverMembershipId, setSecondApproverMembershipId] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const lifecycleInput = {
    lifecycleVersion: docket.lifecycle_version,
    toStatus,
    effectiveAt: effectiveAt ? new Date(effectiveAt).toISOString() : "",
    reason,
    outcome,
    evidenceRef,
    successorDocketId: successorDocketId || null,
    secondApproverMembershipId: secondApproverMembershipId || null,
    linkedMatterHandling: docket.matter_id ? "reviewed" as const : "not_linked" as const,
  };
  const inputSignature = JSON.stringify(lifecycleInput);
  const [previewedSignature, setPreviewedSignature] = useState<string | null>(null);
  const preview = useMutation({
    mutationFn: () => previewIpDocketLifecycle(docket.id, lifecycleInput),
    onSuccess: () => { setPreviewedSignature(inputSignature); setAcknowledged(false); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not preview lifecycle impact.")),
  });
  const previewCurrent = previewedSignature === inputSignature ? preview.data : undefined;
  const transition = useMutation({
    mutationFn: () => transitionIpDocketLifecycle(docket.id, {
      ...lifecycleInput,
      acknowledgedExceptionCodes: acknowledged ? previewCurrent?.blocker_codes ?? [] : [],
    }),
    onSuccess: async () => { toast.success("Docket lifecycle transition recorded."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not apply lifecycle transition.")),
  });
  const valid = reason.trim().length >= 5 && outcome.trim().length >= 2 && evidenceRef.trim().length >= 2 && (toStatus !== "transferred" || Boolean(successorDocketId));
  const blockersAcknowledged = !previewCurrent?.requires_exception_acknowledgement || acknowledged;

  return (
    <Card className="min-w-0" data-testid="ip-lifecycle-workflow">
      <CardHeader><CardTitle as="h3">Close, transfer, or retire</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <p className="text-xs text-[var(--color-mute)]">The dedicated transition locks the parent, records immutable evidence, and prevents generic updates or child work from reopening a terminal docket.</p>
        {enabled ? (
          <form className="grid min-w-0 gap-3" onSubmit={(event) => { event.preventDefault(); preview.mutate(); }}>
            <Field label="Transition">
              <select className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={toStatus} onChange={(event) => setToStatus(event.target.value as typeof toStatus)}>
                <option value="closed">Close</option><option value="abandoned">Abandon</option><option value="retired">Retire</option><option value="transferred">Transfer</option>
              </select>
            </Field>
            <Field label="Effective date and time"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></Field>
            <Field label="Reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            <Field label="Outcome"><Input value={outcome} onChange={(event) => setOutcome(event.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)} /></Field>
            {toStatus === "transferred" ? <Field label="Successor docket ID"><Input value={successorDocketId} onChange={(event) => setSuccessorDocketId(event.target.value)} /></Field> : null}
            <Field label="Second approver (optional)" htmlFor="lifecycle-second-approver"><PersonPicker id="lifecycle-second-approver" value={secondApproverMembershipId} onChange={setSecondApproverMembershipId} placeholder="No second approver" /></Field>
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={!valid || preview.isPending}>Preview lifecycle impact</Button>
              <Button size="sm" className="w-full sm:w-auto" type="button" onClick={() => transition.mutate()} disabled={!previewCurrent || !blockersAcknowledged || transition.isPending}>Apply lifecycle transition</Button>
            </div>
          </form>
        ) : <p className="text-xs text-[var(--color-mute)]">IP review permission is required for lifecycle transitions.</p>}
        {previewCurrent ? (
          <div className="rounded-md border border-[var(--color-line)] p-3 text-xs" data-testid="ip-lifecycle-preview">
            <div className="font-semibold">Impact preview · {previewCurrent.from_status} → {previewCurrent.to_status}</div>
            <ul className="mt-2 grid gap-1">
              {previewCurrent.impacts.map((impact) => <li key={`${impact.impact_kind}-${impact.record_id}`} className="break-words">{impact.impact_kind}: {impact.current_state} → {impact.proposed_outcome}{impact.blocking ? " · acknowledgement required" : ""}</li>)}
            </ul>
            {previewCurrent.requires_exception_acknowledgement ? (
              <label className="mt-3 flex min-w-0 items-start gap-2">
                <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
                <span>I reviewed and acknowledge every listed lifecycle blocker.</span>
              </label>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
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
    onSuccess: async (result) => { toast.success(result.pending_count ? `${result.pending_count} deadline coverage assignment(s) offered. Responsibility moves once the replacement accepts.` : `${result.reassigned_count} deadline coverage assignment(s) transferred.`); setReason(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not transfer deadline coverage.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Deadline continuity</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.deadline_coverages.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <div className="min-w-0 font-semibold">
              Responsible: <PersonName membershipId={row.responsible_membership_id} />
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">{row.coverage_status} · calendar {row.calendar_projection_status} · v{row.reassignment_version}</div>
          </div>
        ))}
        {enabled && docket.deadline_coverages.length ? (
          <form className="grid min-w-0 gap-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
            <Field label="Currently responsible" htmlFor="coverage-from"><PersonPicker id="coverage-from" value={fromMembershipId} onChange={setFromMembershipId} /></Field>
            <Field label="Offer the work to" htmlFor="coverage-to"><PersonPicker id="coverage-to" value={toMembershipId} onChange={setToMembershipId} excludeMembershipIds={[fromMembershipId]} /></Field>
            <Field label="Transfer reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={!fromMembershipId || !toMembershipId || reason.length < 5 || mutation.isPending}>Offer covered deadlines</Button>
          </form>
        ) : <p className="text-xs text-[var(--color-mute)]">No covered deadlines are attached to this docket.</p>}
      </CardContent>
    </Card>
  );
}

type IncidentPanel = "actions" | "impact" | "notifications" | "resolution";

function IncidentCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [selectedId, setSelectedId] = useState("");
  const [showCreateIncident, setShowCreateIncident] = useState(false);
  const [panel, setPanel] = useState<IncidentPanel>("actions");
  const [severity, setSeverity] = useState<IpDeadlineIncident["severity"]>("high");
  const [scope, setScope] = useState<IpDeadlineIncident["defect_scope"]>("record_specific");
  const [summary, setSummary] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [killFeatures, setKillFeatures] = useState<string[]>([]);
  const [killEvidence, setKillEvidence] = useState("");
  const [actionType, setActionType] = useState<"containment" | "corrective_task" | "filing" | "external_advice" | "prevention">("containment");
  const [actionStatus, setActionStatus] = useState<"planned" | "completed" | "not_available">("completed");
  const [actionReference, setActionReference] = useState("");
  const [actionDetails, setActionDetails] = useState("");
  const [actionEvidence, setActionEvidence] = useState("");
  const [recordType, setRecordType] = useState("trademark_application");
  const [recordReference, setRecordReference] = useState("");
  const [relationship, setRelationship] = useState("");
  const [assessment, setAssessment] = useState<"affected" | "not_affected" | "pending">("pending");
  const [scanMethod, setScanMethod] = useState("");
  const [scanEvidence, setScanEvidence] = useState("");
  const [scanComplete, setScanComplete] = useState(false);
  const [recipientType, setRecipientType] = useState<"client" | "insurer" | "regulator" | "court" | "external_counsel">("client");
  const [recipientReference, setRecipientReference] = useState("");
  const [decision, setDecision] = useState<"pending" | "notify" | "do_not_notify" | "not_applicable">("pending");
  const [rationale, setRationale] = useState("");
  const [approvalEvidence, setApprovalEvidence] = useState("");
  const [communicationReference, setCommunicationReference] = useState("");
  const [outcome, setOutcome] = useState<"verified" | "disproved">("verified");
  const [correctiveAction, setCorrectiveAction] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [preventiveAction, setPreventiveAction] = useState("");
  const [resolutionEvidence, setResolutionEvidence] = useState("");
  const [releaseReason, setReleaseReason] = useState("");
  const [releaseEvidence, setReleaseEvidence] = useState("");
  const selected = showCreateIncident ? null : (
    docket.deadline_incidents.find((row) => row.id === selectedId)
      ?? docket.deadline_incidents.find((row) => !["verified", "disproved"].includes(row.status))
      ?? docket.deadline_incidents[0]
      ?? null
  );
  const terminal = selected ? ["verified", "disproved"].includes(selected.status) : false;
  const refresh = async () => { await onChanged(); };

  const create = useMutation({
    mutationFn: () => createIpDeadlineIncident({
      docketId: docket.id,
      severity,
      summary,
      defectScope: scope,
      defectFingerprint: fingerprint,
      sourceReference,
      killSwitchFeatures: scope === "platform_wide" ? killFeatures : [],
      killSwitchEvidenceReference: scope === "platform_wide" ? killEvidence : null,
    }),
    onSuccess: async (updated) => {
      const created = updated.deadline_incidents[0];
      setSelectedId(created?.id ?? "");
      setShowCreateIncident(false);
      setSummary(""); setFingerprint(""); setSourceReference(""); setKillEvidence("");
      toast.success("Deadline incident opened with preserved evidence.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not open deadline incident.")),
  });
  const action = useMutation({
    mutationFn: () => recordIpDeadlineIncidentAction({
      docketId: docket.id, incidentId: selected!.id, actionType, actionStatus,
      actionReference, details: actionDetails, evidenceReference: actionEvidence,
    }),
    onSuccess: async () => { setActionReference(""); setActionDetails(""); setActionEvidence(""); toast.success("Incident action recorded."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record incident action.")),
  });
  const scan = useMutation({
    mutationFn: () => recordIpDeadlineIncidentImpact({
      docketId: docket.id, incidentId: selected!.id, recordType, recordReference,
      relationship, assessment, scanMethod, evidenceReference: scanEvidence, complete: scanComplete,
    }),
    onSuccess: async () => { setRecordReference(""); setRelationship(""); setScanMethod(""); setScanEvidence(""); toast.success("Impact evidence recorded."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record impact scan.")),
  });
  const notify = useMutation({
    mutationFn: () => decideIpDeadlineIncidentNotification({
      docketId: docket.id, incidentId: selected!.id, recipientType, recipientReference,
      decision, rationale, approvalEvidenceReference: approvalEvidence,
      communicationReference: communicationReference || null,
    }),
    onSuccess: async () => { setRecipientReference(""); setRationale(""); setApprovalEvidence(""); setCommunicationReference(""); toast.success("Recipient decision recorded."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record recipient decision.")),
  });
  const resolve = useMutation({
    mutationFn: () => resolveIpDeadlineIncident({
      docketId: docket.id, incidentId: selected!.id, outcome, correctiveAction,
      rootCause, preventiveAction, resolutionEvidenceReference: resolutionEvidence,
    }),
    onSuccess: async () => { toast.success(`Incident ${outcome}.`); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not resolve incident.")),
  });
  const release = useMutation({
    mutationFn: (row: IpDeadlineIncident["kill_switches"][number]) => releaseIpIncidentKillSwitch({
      docketId: docket.id, incidentId: selected!.id, featureId: row.feature_id,
      expectedVersion: row.version, releaseReason, releaseEvidenceReference: releaseEvidence,
    }),
    onSuccess: async () => { setReleaseReason(""); setReleaseEvidence(""); toast.success("Automation stop released."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not release automation stop.")),
  });

  const selectClass = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";
  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-incident-workspace">
      <CardHeader><CardTitle as="h3">Deadline incident review</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {docket.deadline_incidents.length ? (
          <Field label="Incident" htmlFor="incident-select">
            <select id="incident-select" className={selectClass} value={selected?.id ?? ""} onChange={(event) => { setShowCreateIncident(false); setSelectedId(event.target.value); }}>
              {docket.deadline_incidents.map((row) => <option key={row.id} value={row.id}>{row.severity.toUpperCase()} · {row.status.replaceAll("_", " ")} · {row.summary}</option>)}
            </select>
          </Field>
        ) : null}

        {selected ? (
          <div className="grid min-w-0 gap-3 border-y border-[var(--color-line)] py-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Status" value={selected.status.replaceAll("_", " ")} icon={AlertTriangle} />
            <Metric label="Affected records" value={String(selected.impacts.length)} icon={FileCheck2} />
            <Metric label="Recipient decisions" value={String(selected.notification_decisions.length)} icon={FileCheck2} />
            <Metric label="Automation stops" value={String(selected.kill_switches.filter((row) => row.status === "active").length)} icon={AlertTriangle} />
          </div>
        ) : null}

        {enabled && !selected ? (
          <form className="grid min-w-0 gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
            <Field label="Severity"><select className={selectClass} value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></Field>
            <Field label="Defect scope"><select className={selectClass} value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}><option value="record_specific">Record specific</option><option value="shared_rule">Shared rule</option><option value="shared_source">Shared source</option><option value="platform_wide">Platform wide</option></select></Field>
            <Field label="Incident summary"><Textarea value={summary} onChange={(event) => setSummary(event.target.value)} /></Field>
            <Field label="Defect fingerprint"><Input value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} /></Field>
            <Field label="Source evidence reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} /></Field>
            {scope === "platform_wide" ? <div className="grid min-w-0 gap-2"><Label>Automation stops</Label>{["registry_sync", "deadline_automation", "notification_automation", "watch_operations"].map((feature) => <label key={feature} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={killFeatures.includes(feature)} onChange={(event) => setKillFeatures((current) => event.target.checked ? [...current, feature] : current.filter((row) => row !== feature))} />{feature.replaceAll("_", " ")}</label>)}<Input aria-label="Automation stop evidence" value={killEvidence} onChange={(event) => setKillEvidence(event.target.value)} /></div> : null}
            <div className="md:col-span-2"><Button type="submit" disabled={summary.length < 5 || fingerprint.length < 3 || sourceReference.length < 3 || (scope === "platform_wide" && (!killFeatures.length || killEvidence.length < 3)) || create.isPending}>Open incident</Button></div>
          </form>
        ) : null}

        {enabled && selected && !terminal ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="tablist" aria-label="Incident review stages">
              {(["actions", "impact", "notifications", "resolution"] as IncidentPanel[]).map((item) => <Button key={item} type="button" size="sm" variant={panel === item ? "primary" : "secondary"} onClick={() => setPanel(item)}>{item === "notifications" ? "Recipients" : item[0].toUpperCase() + item.slice(1)}</Button>)}
            </div>
            {panel === "actions" ? <form className="grid min-w-0 gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); action.mutate(); }}>
              <Field label="Action"><select className={selectClass} value={actionType} onChange={(event) => setActionType(event.target.value as typeof actionType)}><option value="containment">Containment</option><option value="corrective_task">Corrective task</option><option value="filing">Filing</option><option value="external_advice">External advice</option><option value="prevention">Prevention</option></select></Field>
              <Field label="Action status"><select className={selectClass} value={actionStatus} onChange={(event) => setActionStatus(event.target.value as typeof actionStatus)}><option value="planned">Planned</option><option value="completed">Completed</option><option value="not_available">Not available</option></select></Field>
              <Field label="Action reference"><Input value={actionReference} onChange={(event) => setActionReference(event.target.value)} /></Field><Field label="Evidence reference"><Input value={actionEvidence} onChange={(event) => setActionEvidence(event.target.value)} /></Field>
              <Field label="Action details"><Textarea value={actionDetails} onChange={(event) => setActionDetails(event.target.value)} /></Field><div className="flex items-end"><Button type="submit" disabled={actionReference.length < 3 || actionDetails.length < 5 || actionEvidence.length < 3 || action.isPending}>Record action</Button></div>
            </form> : null}
            {panel === "impact" ? <form className="grid min-w-0 gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); scan.mutate(); }}>
              <Field label="Record type"><Input value={recordType} onChange={(event) => setRecordType(event.target.value)} /></Field><Field label="Record reference"><Input value={recordReference} onChange={(event) => setRecordReference(event.target.value)} /></Field>
              <Field label="Relationship"><Input value={relationship} onChange={(event) => setRelationship(event.target.value)} /></Field><Field label="Assessment"><select className={selectClass} value={assessment} onChange={(event) => setAssessment(event.target.value as typeof assessment)}><option value="pending">Pending</option><option value="affected">Affected</option><option value="not_affected">Not affected</option></select></Field>
              <Field label="Scan method"><Input value={scanMethod} onChange={(event) => setScanMethod(event.target.value)} /></Field><Field label="Scan evidence"><Input value={scanEvidence} onChange={(event) => setScanEvidence(event.target.value)} /></Field>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={scanComplete} onChange={(event) => setScanComplete(event.target.checked)} />Complete impact scan</label><div className="flex items-end"><Button type="submit" disabled={recordReference.length < 1 || relationship.length < 2 || scanMethod.length < 2 || scanEvidence.length < 3 || (scanComplete && assessment === "pending") || scan.isPending}>Record impact</Button></div>
            </form> : null}
            {panel === "notifications" ? <form className="grid min-w-0 gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); notify.mutate(); }}>
              <Field label="Recipient"><select className={selectClass} value={recipientType} onChange={(event) => setRecipientType(event.target.value as typeof recipientType)}><option value="client">Client</option><option value="insurer">Insurer</option><option value="regulator">Regulator</option><option value="court">Court</option><option value="external_counsel">External counsel</option></select></Field><Field label="Private recipient reference"><Input value={recipientReference} onChange={(event) => setRecipientReference(event.target.value)} /></Field>
              <Field label="Decision"><select className={selectClass} value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}><option value="pending">Pending</option><option value="notify">Notify</option><option value="do_not_notify">Do not notify</option><option value="not_applicable">Not applicable</option></select></Field><Field label="Approval evidence"><Input value={approvalEvidence} onChange={(event) => setApprovalEvidence(event.target.value)} /></Field>
              <Field label="Decision rationale"><Textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></Field><Field label="Communication reference"><Input value={communicationReference} onChange={(event) => setCommunicationReference(event.target.value)} /></Field>
              <div className="md:col-span-2"><Button type="submit" disabled={recipientReference.length < 1 || rationale.length < 5 || approvalEvidence.length < 3 || (decision === "notify" && communicationReference.length < 3) || notify.isPending}>Record recipient decision</Button></div>
            </form> : null}
            {panel === "resolution" ? <form className="grid min-w-0 gap-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); resolve.mutate(); }}>
              <Field label="Outcome"><select className={selectClass} value={outcome} onChange={(event) => setOutcome(event.target.value as typeof outcome)}><option value="verified">Verified defect</option><option value="disproved">Disproved suspicion</option></select></Field><Field label="Resolution evidence"><Input value={resolutionEvidence} onChange={(event) => setResolutionEvidence(event.target.value)} /></Field>
              <Field label="Corrective action"><Textarea value={correctiveAction} onChange={(event) => setCorrectiveAction(event.target.value)} /></Field><Field label="Root cause"><Textarea value={rootCause} onChange={(event) => setRootCause(event.target.value)} /></Field>
              <Field label="Preventive action"><Textarea value={preventiveAction} onChange={(event) => setPreventiveAction(event.target.value)} /></Field><div className="flex items-end"><Button type="submit" disabled={correctiveAction.length < 5 || rootCause.length < 5 || preventiveAction.length < 5 || resolutionEvidence.length < 3 || resolve.isPending}>Resolve incident</Button></div>
            </form> : null}
          </>
        ) : null}

        {enabled && selected?.kill_switches.some((row) => row.status === "active") ? <div className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-3 md:grid-cols-2"><Field label="Release reason"><Textarea value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} /></Field><Field label="Release evidence"><Input value={releaseEvidence} onChange={(event) => setReleaseEvidence(event.target.value)} /></Field>{selected.kill_switches.filter((row) => row.status === "active").map((row) => <Button key={row.id} size="sm" variant="secondary" disabled={!terminal || releaseReason.length < 5 || releaseEvidence.length < 3 || release.isPending} onClick={() => release.mutate(row)}>Release {row.feature_id.replaceAll("_", " ")}</Button>)}</div> : null}

        {enabled && selected ? <Button size="sm" variant="secondary" onClick={() => setShowCreateIncident(true)}>Open another incident</Button> : null}
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
            <Field label="Owner" htmlFor="obligation-owner"><PersonPicker id="obligation-owner" value={ownerMembershipId} onChange={setOwnerMembershipId} /></Field>
            <Field label="Due date (optional)"><Input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} /></Field>
            <Field label="Obligation evidence"><Input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></Field>
            <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={title.length < 3 || !ownerMembershipId || evidence.length < 3 || create.isPending}>Add recordal obligation</Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

const COST_STATUS_LABEL: Record<string, string> = {
  matched: "Matched to billing",
  mismatch: "Differs from billing",
  missing: "Billing record not found",
  unlinked: "Awaiting a billing link",
  estimate: "Estimate — not an expense",
  nonbillable: "Nonbillable",
};

function CostAmount({ row }: { row: IpDocket["cost_items"][number] }) {
  // A withheld rate must read as withheld. Rendering 0.00 would be a lie the
  // reader has no way to detect.
  if (row.amount_withheld) {
    return (
      <span className="text-[var(--color-mute)]">
        Amount withheld — requires fee-management access
      </span>
    );
  }
  const original = `${row.currency} ${((row.amount_minor ?? 0) / 100).toFixed(2)}`;
  if (row.base_amount_minor === null || row.base_currency === null) {
    return <span className="tabular-nums">{original}</span>;
  }
  return (
    <span className="tabular-nums">
      {original}
      <span className="text-[var(--color-mute)]">
        {" "}
        → {row.base_currency} {(row.base_amount_minor / 100).toFixed(2)}
        {row.fx_rate ? ` at ${row.fx_rate}` : null}
        {row.fx_rate_source ? ` (${row.fx_rate_source})` : null}
      </span>
    </span>
  );
}

function CostCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [billingLinkType, setBillingLinkType] = useState<"" | "invoice" | "invoice_line_item" | "time_entry">("");
  const [billingLinkId, setBillingLinkId] = useState("");
  const [costNature, setCostNature] = useState<"actual" | "estimate">("actual");
  const [rateConfidential, setRateConfidential] = useState(false);
  const [converted, setConverted] = useState(false);
  const [currency, setCurrency] = useState("INR");
  const [fxRate, setFxRate] = useState("");
  const [fxRateSource, setFxRateSource] = useState("");
  const [fxConvertedAt, setFxConvertedAt] = useState("");
  const [baseAmount, setBaseAmount] = useState("");
  const [baseCurrency, setBaseCurrency] = useState("INR");

  // UJ-52-EXC-01: with no billing Matter the cost is still recorded, but only
  // as nonbillable evidence. The billing decision is deferred, not the fee.
  const hasBillingOwner = Boolean(docket.matter_id);
  // An estimate and a nonbillable cost have nothing in the ledger to point at.
  const canLinkBilling = hasBillingOwner && costNature === "actual";

  const resetForm = () => {
    setDescription(""); setAmount(""); setEvidence(""); setBillingLinkId("");
    setFxRate(""); setFxRateSource(""); setFxConvertedAt(""); setBaseAmount("");
    setConverted(false); setCurrency("INR"); setRateConfidential(false);
  };

  const mutation = useMutation({
    mutationFn: () => addIpCostItem(docket.id, {
      category: "official_fee",
      description,
      amountMinor: Math.round(Number(amount) * 100),
      currency,
      evidenceReference: evidence,
      billingLinkType: canLinkBilling ? billingLinkType || null : null,
      billingLinkId: canLinkBilling ? billingLinkId || null : null,
      billable: hasBillingOwner,
      costNature,
      rateConfidential,
      fxRate: converted ? fxRate : null,
      fxRateSource: converted ? fxRateSource : null,
      fxConvertedAt: converted && fxConvertedAt ? new Date(fxConvertedAt).toISOString() : null,
      baseAmountMinor: converted ? Math.round(Number(baseAmount) * 100) : null,
      baseCurrency: converted ? baseCurrency : null,
    }),
    onSuccess: async () => {
      toast.success("Immutable cost evidence added.");
      resetForm();
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

  const conversionIncomplete = converted && (!fxRate || !fxRateSource || !fxConvertedAt || !baseAmount || baseCurrency === currency);

  return (
    <Card className="min-w-0" data-testid="ip-cost-workspace">
      <CardHeader><CardTitle as="h3">IP cost evidence</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.cost_items.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <strong className="break-words">{row.description}</strong>{" "}
            <CostAmount row={row} />
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {COST_STATUS_LABEL[row.reconciliation_status] ?? row.reconciliation_status}
              {row.cost_nature === "estimate" ? " · Provider estimate" : null}
              {row.rate_confidential ? " · Confidential rate" : null}
            </div>
          </div>
        ))}
        {enabled ? (
          <form className="grid min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
            {!hasBillingOwner ? (
              <p className="text-xs text-[var(--color-mute)]">
                This record has no Matter billing owner, so the cost is captured as
                nonbillable evidence. Link the record to a Matter to bill it; Matter
                billing remains the only accounting owner either way.
              </p>
            ) : null}
            <Field label="Description"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            <Field label={`Amount (${currency})`}><Input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
            <Field label="Cost nature">
              <select className="h-10 min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={costNature} onChange={(event) => setCostNature(event.target.value as typeof costNature)}>
                <option value="actual">Actual expense incurred</option>
                <option value="estimate">Provider estimate or quote</option>
              </select>
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={rateConfidential} onChange={(event) => setRateConfidential(event.target.checked)} />
              Confidential rate — hide the amount from members without fee-management access
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={converted} onChange={(event) => setConverted(event.target.checked)} />
              This cost was incurred in another currency
            </label>
            {converted ? (
              <div className="grid min-w-0 gap-2 rounded-md border border-[var(--color-line)] p-3">
                <p className="text-xs text-[var(--color-mute)]">
                  The amount above stays as originally incurred. Record what it was
                  converted to, at which rate, from which source, and when.
                </p>
                <Field label="Original currency"><Input value={currency} maxLength={3} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></Field>
                <Field label="Converted amount"><Input type="number" min="0" step="0.01" value={baseAmount} onChange={(event) => setBaseAmount(event.target.value)} /></Field>
                <Field label="Converted currency"><Input value={baseCurrency} maxLength={3} onChange={(event) => setBaseCurrency(event.target.value.toUpperCase())} /></Field>
                <Field label="Exchange rate"><Input value={fxRate} onChange={(event) => setFxRate(event.target.value)} /></Field>
                <Field label="Rate source"><Input value={fxRateSource} onChange={(event) => setFxRateSource(event.target.value)} /></Field>
                <Field label="Conversion date"><Input type="date" value={fxConvertedAt} onChange={(event) => setFxConvertedAt(event.target.value)} /></Field>
                {baseCurrency === currency ? (
                  <p className="text-xs text-[var(--color-mute)]">Choose a converted currency different from the original.</p>
                ) : null}
              </div>
            ) : null}
            {canLinkBilling ? (
              <Field label="Matter billing link type">
                <select className="h-10 min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={billingLinkType} onChange={(event) => setBillingLinkType(event.target.value as typeof billingLinkType)}>
                  <option value="">No billing link</option>
                  <option value="invoice">Invoice</option>
                  <option value="invoice_line_item">Invoice line item</option>
                  <option value="time_entry">Time entry</option>
                </select>
              </Field>
            ) : (
              <p className="text-xs text-[var(--color-mute)]">
                {costNature === "estimate"
                  ? "An estimate is not an expense, so it is not linked to a billing record."
                  : "A nonbillable cost is not linked to a billing record."}
              </p>
            )}
            {canLinkBilling && billingLinkType ? <Field label="Matter billing record ID"><Input value={billingLinkId} onChange={(event) => setBillingLinkId(event.target.value)} /></Field> : null}
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={description.length < 3 || !amount || evidence.length < 3 || (canLinkBilling && Boolean(billingLinkType) !== Boolean(billingLinkId)) || conversionIncomplete || mutation.isPending}>
                {hasBillingOwner ? "Add cost evidence" : "Add nonbillable cost evidence"}
              </Button>
              <Button size="sm" className="w-full sm:w-auto" type="button" variant="secondary" onClick={() => reconcile.mutate()} disabled={reconcile.isPending}>Reconcile with Matter billing</Button>
            </div>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
  htmlFor,
}: {
  label: string;
  children: React.ReactNode;
  // When the control is a composite (a picker with its own filter box), the
  // label must point at the real control by id rather than wrap the group,
  // otherwise it binds to whichever input happens to come first.
  htmlFor?: string;
}) {
  if (htmlFor) {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <Label htmlFor={htmlFor}>{label}</Label>
        {children}
      </div>
    );
  }
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
