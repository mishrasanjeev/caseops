"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgeIndianRupee, FileCheck2, Plus, Scale } from "lucide-react";
import Link from "next/link";
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
  enableIpWorkspace,
  fetchIpDockets,
  fetchIpWorkspaceReadiness,
  reconcileIpCosts,
  reviewIpEvidenceCandidate,
  runIpWorkspaceTest,
  saveIpWorkspaceConfiguration,
  type IpDocket,
  type IpEvidenceCandidate,
  type IpFeatureReadiness,
  type IpWorkspaceConfigurationStatus,
  type IpWorkspaceTestResult,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const TODAY = new Date().toISOString().slice(0, 10);

export default function IpDocketPage() {
  const queryClient = useQueryClient();
  const canView = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canReview = useCapability("ip:approve");
  const canFinance = useCapability("ip:fees_manage");
  const canConfigure = useCapability("ip:taxonomy_admin");
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
  workspace_not_configured: "Tenant setup has not been saved",
  tenant_disabled: "Tenant enablement has not passed",
  readiness_test_failed: "The latest required readiness test has not passed",
};

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
