"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BadgeIndianRupee,
  FileCheck2,
  Plus,
  Scale,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { IpAccessWorkspace } from "@/components/ip/IpAccessWorkspace";
import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { PersonName, PersonPicker } from "@/components/ui/PersonPicker";
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
  createIpDocket,
  createIpSharedHearing,
  decideIpCoverageTransfer,
  discoverIpEvidence,
  enableIpWorkspace,
  fetchIpCoreRecords,
  fetchIpCoverageTransfersAwaitingMe,
  fetchIpDeadlineImpact,
  fetchIpDeadlineRuleImpact,
  fetchIpDeadlineWorkspace,
  fetchIpDockets,
  fetchIpSharedHearings,
  fetchIpProsecutionWorkspace,
  fetchIpWorkspaceReadiness,
  listCalendarConnections,
  previewIpDocketEvent,
  previewIpDocketLifecycle,
  proposeIpDeadlineRule,
  proposeIpLegalDeadline,
  proposeIpWorkingCalendar,
  recalculateIpLegalDeadline,
  reconcileIpCosts,
  reviewIpEvidenceCandidate,
  runIpWorkspaceTest,
  saveIpWorkspaceConfiguration,
  syncHearingToGoogleCalendar,
  syncHearingToOutlook,
  transitionIpDocketLifecycle,
  transitionIpDeadlineRule,
  overrideIpLegalDeadline,
  type IpDocket,
  type IpLegalDeadline,
  type IpSharedHearing,
  type IpResponsibilityAssignmentInput,
  type IpDocketEventInput,
  type IpEvidenceCandidate,
  type IpFeatureReadiness,
  type IpWorkspaceConfigurationStatus,
  type IpWorkspaceTestResult,
  updateIpSharedHearing,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const TODAY = new Date().toISOString().slice(0, 10);

export default function IpDocketPage() {
  const queryClient = useQueryClient();
  const canView = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canUploadDocuments = useCapability("documents:upload");
  const canManageDocuments = useCapability("documents:manage");
  const canReview = useCapability("ip:approve");
  const canProposeRules = useCapability("ip:rules_propose");
  const canActivateRules = useCapability("ip:rules_activate");
  const canFinance = useCapability("ip:fees_manage");
  const canConfigure = useCapability("ip:taxonomy_admin");
  const canManageAccess = useCapability("matter_access:manage");
  const session = useSession();
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

      <IpDocumentWorkspace
        dockets={dockets}
        canUpload={canWrite && canUploadDocuments}
        canManage={canWrite && canManageDocuments}
        canReview={canReview}
        canConfigure={canConfigure}
      />

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
        <div className="flex min-w-0 flex-col gap-5">
        <CoverageDecisionsCard onChanged={refresh} />
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
              canWrite={canWrite}
              canReview={canReview}
              canFinance={canFinance}
              canProposeRules={canProposeRules}
              canActivateRules={canActivateRules}
              canManageAccess={canManageAccess}
              currentMembershipId={session.context?.membership.id ?? null}
              onChanged={refresh}
            />
          ) : null}
        </div>
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
  workspace_not_configured: "Tenant setup has not been saved",
  tenant_disabled: "Tenant enablement has not passed",
  readiness_test_failed: "The latest required readiness test has not passed",
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

  if (!transfers.length) return null;

  return (
    <Card className="min-w-0" data-testid="ip-coverage-decisions">
      <CardHeader>
        <CardTitle as="h2">Coverage awaiting your decision</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {transfers.map((row) => {
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
            <Input value={providerKey} onChange={(event) => setProviderKey(event.target.value)} />
          </Field>
        </div>

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
  canWrite,
  canReview,
  canFinance,
  canProposeRules,
  canActivateRules,
  canManageAccess,
  currentMembershipId,
  onChanged,
}: {
  docket: IpDocket;
  canWrite: boolean;
  canReview: boolean;
  canFinance: boolean;
  canProposeRules: boolean;
  canActivateRules: boolean;
  canManageAccess: boolean;
  currentMembershipId: string | null;
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
        {canManageAccess ? (
          <IpAccessWorkspace docket={docket} onChanged={onChanged} />
        ) : null}
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
        <ProsecutionCard
          docket={docket}
          enabled={canWrite}
          currentMembershipId={currentMembershipId}
          onChanged={onChanged}
        />
        <LifecycleCard docket={docket} enabled={canReview} onChanged={onChanged} />
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
  const hearings = useQuery({
    queryKey: ["ip", "hearings", docket.id],
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
    queryClient.invalidateQueries({ queryKey: ["ip", "hearings", docket.id] });
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
    onSuccess: async () => {
      setPreviewing(false);
      toast.success("Hearing and idempotent reminders scheduled.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not schedule hearing.")),
  });
  const update = useMutation({
    mutationFn: (input: {
      hearingId: string;
      hearingOn?: string;
      status?: "scheduled" | "completed" | "adjourned" | "cancelled";
    }) => updateIpSharedHearing({ docketId: docket.id, ...input }),
    onSuccess: async () => {
      toast.success("Hearing updated; dependent reminders were superseded.");
      await refresh();
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
            const activeReminders = hearing.reminders.filter((row) => row.status !== "cancelled");
            return (
              <article key={hearing.id} className="min-w-0 rounded-lg border border-[var(--color-line)] p-3">
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h4 className="break-words font-semibold">{hearing.purpose}</h4>
                    <p className="break-words text-xs text-[var(--color-mute)]">{hearing.hearing_on} · {hearing.time_status === "exact" ? hearing.hearing_time : hearing.session_label ?? "Time not published"} · {hearing.timezone} · {hearing.forum_name} · {hearing.hearing_mode}</p>
                  </div>
                  <span className="text-sm font-semibold">{hearing.status}</span>
                </div>
                <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label={`Reminder delivery for ${hearing.purpose}`}>
                  {activeReminders.map((reminder) => (
                    <div key={reminder.id} className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-2 text-xs">
                      <strong>{reminder.channel}</strong> · {reminder.status}
                      <div className="break-words text-[var(--color-mute)]">{new Date(reminder.scheduled_for).toLocaleString()} · attempts {reminder.attempts}{reminder.last_error ? ` · ${reminder.last_error}` : ""}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
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
          deadline.result_on === null && actionDate ? actionDate : null,
        correctionReason:
          deadline.result_on === null ? actionReason || null : null,
        correctionEvidenceReference:
          deadline.result_on === null ? evidenceReference || null : null,
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
                  proposal.isPending
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
          {workspace.data?.deadlines.map((deadline) => (
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
                  <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
                    Governing source: {deadline.rule_citation}
                  </div>
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
                        (deadline.result_on === null &&
                          (!actionDate || !actionReason.trim() || !evidenceReference.trim())) ||
                        confirm.isPending
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
                          !baseDate || !actionReason.trim() || !evidenceReference.trim() || recalculate.isPending
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
                          override.isPending
                        }
                        onClick={() => override.mutate(deadline)}
                      >
                        Preview impact and override
                      </Button>
                      <Button
                        className="w-full sm:w-auto"
                        size="sm"
                        disabled={
                          !evidenceReference.trim() || !attestation.trim() || complete.isPending
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
          ))}
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
  const application = core.data?.applications[0] ?? null;
  const [eventKind, setEventKind] = useState<(typeof EVENT_KINDS)[number]>("formalities");
  const [effectiveAt, setEffectiveAt] = useState(localDateTimeValue);
  const [reason, setReason] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [documentRef, setDocumentRef] = useState("");
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
      }
    : null;
  const inputSignature = JSON.stringify(eventInput);
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip", "prosecution", docket.id] }),
        queryClient.invalidateQueries({ queryKey: ["ip", "core-records", docket.id] }),
        onChanged(),
      ]);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the prosecution event.")),
  });
  const valid = Boolean(eventInput && reason.trim().length >= 5 && effectiveAt);
  const previewCurrent = previewedSignature === inputSignature ? preview.data : undefined;

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
            <Field label="Event type">
              <select className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={eventKind} onChange={(event) => setEventKind(event.target.value as typeof eventKind)}>
                {EVENT_KINDS.map((kind) => <option key={kind} value={kind}>{kind.replaceAll("_", " ")}</option>)}
              </select>
            </Field>
            <Field label="Effective date and time"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></Field>
            <Field label="Reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)} placeholder="attachment:…" /></Field>
            <Field label="Document reference"><Input value={documentRef} onChange={(event) => setDocumentRef(event.target.value)} placeholder="attachment:…" /></Field>
            <p className="text-xs text-[var(--color-mute)]">A checklist or operational task is not filing evidence and never proves registry acceptance.</p>
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button size="sm" className="w-full sm:w-auto" type="submit" disabled={!valid || preview.isPending}>Preview prosecution event</Button>
              <Button size="sm" className="w-full sm:w-auto" type="button" onClick={() => commit.mutate()} disabled={!previewCurrent || commit.isPending}>Record prosecution event</Button>
            </div>
          </form>
        ) : <p className="text-xs text-[var(--color-mute)]">IP write permission is required to record an event.</p>}

        {previewCurrent ? (
          <div className="rounded-md border border-[var(--color-line)] p-3 text-xs" data-testid="ip-event-preview">
            <div className="font-semibold">Preview only · {previewCurrent.current_phase} → {previewCurrent.proposed_phase ?? "unchanged"}</div>
            <div className="mt-1">Backdated recalculation: {previewCurrent.recalculation_required ? "required" : "not required"}</div>
            <ul className="mt-2 grid gap-1">
              {previewCurrent.checklist.map((item) => <li key={item.key}>{item.satisfied ? "✓" : "○"} {item.label}</li>)}
            </ul>
          </div>
        ) : null}

        {prosecution.data?.events.length ? (
          <ol className="grid min-w-0 gap-2" aria-label="Prosecution event timeline">
            {prosecution.data.events.map((event) => (
              <li key={event.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-xs">
                <strong>#{event.sequence} {event.event_kind.replaceAll("_", " ")}</strong>
                <div className="mt-1 break-words">{event.source} · {new Date(event.effective_at).toLocaleString()} · {event.before_phase ?? "—"} → {event.after_phase ?? "—"}</div>
              </li>
            ))}
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
