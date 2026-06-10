"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileCheck2,
  KeyRound,
  Loader2,
  ReceiptText,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchMarginReadiness,
  fetchPasswordResetReadiness,
  fetchPineLabsUatReadiness,
  fetchPlatformFinanceReport,
  fetchPlatformSupportMatrix,
  fetchProductionBillingSignoff,
  recordPineLabsActivationDecision,
  recordPineLabsUatEvidence,
  recordProductionBillingSignoffEvidence,
} from "@/lib/api/endpoints";
import type {
  CaseTrackingSupportMatrixAdminResponse,
  MarginReadinessResponse,
  PasswordResetReadinessResponse,
  PineLabsUatReadinessResponse,
  ProductionBillingSignoffResponse,
} from "@/lib/api/schemas";
import { formatMoneyMinor } from "@/lib/billing-format";
import { useCapability } from "@/lib/capabilities";

function toneForStatus(status: string | boolean): "neutral" | "brand" | "success" | "warning" {
  if (status === true || ["pass", "complete", "ready", "go"].includes(String(status))) {
    return "success";
  }
  if (["fail", "blocked", "no_go"].includes(String(status))) return "warning";
  if (["pending", "not_recorded"].includes(String(status))) return "neutral";
  return "brand";
}

function label(value: string): string {
  return value.replaceAll("_", " ");
}

function valueToString(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function ReadinessSummary({
  pine,
  signoff,
  margin,
}: {
  pine: PineLabsUatReadinessResponse | undefined;
  signoff: ProductionBillingSignoffResponse | undefined;
  margin: MarginReadinessResponse | undefined;
}) {
  const blocked = Boolean(
    pine?.production_activation_blocked || !signoff?.complete || margin?.blocked,
  );
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-[var(--color-mute)]">Pine Labs UAT</div>
          <Badge tone={toneForStatus(Boolean(pine?.complete))}>
            {pine?.complete ? "complete" : "blocked"}
          </Badge>
        </div>
        <div className="mt-2 text-2xl font-semibold text-[var(--color-ink)]">
          {pine?.missing_required_scenarios.length ?? 0} missing
        </div>
      </div>
      <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-[var(--color-mute)]">Billing signoff</div>
          <Badge tone={toneForStatus(Boolean(signoff?.complete))}>
            {signoff?.complete ? "complete" : "blocked"}
          </Badge>
        </div>
        <div className="mt-2 text-2xl font-semibold text-[var(--color-ink)]">
          {signoff?.missing_required_checks.length ?? 0} missing
        </div>
      </div>
      <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-[var(--color-mute)]">Activation gate</div>
          <Badge tone={blocked ? "warning" : "success"}>{blocked ? "blocked" : "ready"}</Badge>
        </div>
        <div className="mt-2 text-2xl font-semibold text-[var(--color-ink)]">
          {margin?.minimum_gross_margin_bps
            ? `${(margin.minimum_gross_margin_bps / 100).toFixed(0)}% floor`
            : "70% floor"}
        </div>
      </div>
    </div>
  );
}

function PineEvidenceTable({
  readiness,
  busy,
  onRecordPass,
  onDecision,
}: {
  readiness: PineLabsUatReadinessResponse | undefined;
  busy: boolean;
  onRecordPass: (scenarioCode: string) => void;
  onDecision: (decision: "go" | "no_go") => void;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle as="h2">Pine Labs UAT evidence</CardTitle>
          <CardDescription>
            Production payment activation remains blocked until required scenarios pass.
          </CardDescription>
        </div>
        <ShieldAlert className="h-5 w-5 text-amber-700" aria-hidden />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={readiness?.production_activation_blocked ? "warning" : "success"}>
            {readiness?.production_activation_blocked ? "activation blocked" : "evidence complete"}
          </Badge>
          <Badge tone="neutral">mode {readiness?.provider_mode ?? "unknown"}</Badge>
          <Badge tone="neutral">env {readiness?.environment ?? "unknown"}</Badge>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Scenario</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Order</th>
                <th className="py-2 pr-4">Webhook</th>
                <th className="py-2 pr-4">Observed</th>
                <th className="py-2 pr-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {(readiness?.scenarios ?? []).map((scenario) => (
                <tr key={scenario.scenario_code} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium">{scenario.label}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={toneForStatus(scenario.result_status)}>
                      {scenario.result_status}
                    </Badge>
                  </td>
                  <td className="py-3 pr-4">{scenario.provider_order_id ?? "-"}</td>
                  <td className="py-3 pr-4">{scenario.webhook_id ?? "-"}</td>
                  <td className="py-3 pr-4">{scenario.observed_at ?? "-"}</td>
                  <td className="py-3 pr-4">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy || scenario.result_status === "pass"}
                      onClick={() => onRecordPass(scenario.scenario_code)}
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                      Pass
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => onDecision("no_go")}>
            Record no-go
          </Button>
          <Button
            type="button"
            disabled={busy || readiness?.production_activation_blocked}
            onClick={() => onDecision("go")}
          >
            Record go
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function BillingSignoffTable({
  signoff,
  busy,
  onRecordPass,
}: {
  signoff: ProductionBillingSignoffResponse | undefined;
  busy: boolean;
  onRecordPass: (checkCode: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Production billing signoff</CardTitle>
        <CardDescription>
          Founder evidence for platform admin, tenant exports, disabled checkout, and no-leak checks.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Check</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Evidence</th>
                <th className="py-2 pr-4">Recorded</th>
                <th className="py-2 pr-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {(signoff?.checks ?? []).map((check) => (
                <tr key={check.check_code} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium">{check.label}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={toneForStatus(check.result_status)}>
                      {check.result_status}
                    </Badge>
                  </td>
                  <td className="py-3 pr-4">{check.evidence_ref ?? "-"}</td>
                  <td className="py-3 pr-4">{check.recorded_at ?? "-"}</td>
                  <td className="py-3 pr-4">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy || check.result_status === "pass"}
                      onClick={() => onRecordPass(check.check_code)}
                    >
                      <FileCheck2 className="h-4 w-4" aria-hidden />
                      Pass
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function PasswordResetReadiness({
  readiness,
}: {
  readiness: PasswordResetReadinessResponse | undefined;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle as="h2">Password reset readiness</CardTitle>
          <CardDescription>
            Reset domain and SendGrid template metadata are visible without token or secret values.
          </CardDescription>
        </div>
        <KeyRound className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-[var(--color-mute)]">Reset domain</dt>
            <dd className="font-medium text-[var(--color-ink)]">
              {readiness?.reset_link_domain ?? "-"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-mute)]">Reset path</dt>
            <dd className="font-medium text-[var(--color-ink)]">
              {readiness?.reset_path ?? "-"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-mute)]">Provider</dt>
            <dd>
              <Badge tone={readiness?.provider_configured ? "success" : "warning"}>
                {readiness?.email_provider ?? "sendgrid"}{" "}
                {readiness?.provider_configured ? "configured" : "blocked"}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-mute)]">Template</dt>
            <dd className="font-medium text-[var(--color-ink)]">
              {readiness?.template_kind ?? "-"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-mute)]">Token TTL</dt>
            <dd className="font-medium text-[var(--color-ink)]">
              {readiness?.token_ttl_minutes ?? 60} minutes
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-mute)]">Secrets exposed</dt>
            <dd>
              <Badge tone={readiness?.secrets_exposed ? "warning" : "success"}>
                {readiness?.secrets_exposed ? "yes" : "no"}
              </Badge>
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function MarginReadiness({ readiness }: { readiness: MarginReadinessResponse | undefined }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle as="h2">Margin readiness</CardTitle>
          <CardDescription>
            Public plan activation is blocked by missing, low-margin, or unapproved estimated scenarios.
          </CardDescription>
        </div>
        <AlertTriangle className="h-5 w-5 text-amber-700" aria-hidden />
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Scenario</th>
                <th className="py-2 pr-4">Margin</th>
                <th className="py-2 pr-4">Estimated costs</th>
                <th className="py-2 pr-4">Gate</th>
              </tr>
            </thead>
            <tbody>
              {(readiness?.required_scenarios ?? []).map((scenario) => (
                <tr key={scenario.scenario_code} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium">{label(scenario.scenario_code)}</td>
                  <td className="py-3 pr-4">
                    {scenario.latest_gross_margin_bps === null
                      ? "-"
                      : `${(scenario.latest_gross_margin_bps / 100).toFixed(1)}%`}
                  </td>
                  <td className="py-3 pr-4">
                    <Badge tone={scenario.uses_unapproved_estimated_costs ? "warning" : "success"}>
                      {scenario.uses_unapproved_estimated_costs ? "review" : "approved actuals"}
                    </Badge>
                  </td>
                  <td className="py-3 pr-4">
                    <Badge tone={scenario.readiness_blocked ? "warning" : "success"}>
                      {scenario.missing
                        ? "missing"
                        : scenario.readiness_blocked
                          ? "blocked"
                          : "ready"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function FinanceExceptions({ rows }: { rows: Record<string, unknown>[] }) {
  const visibleRows = rows.slice(0, 8);
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle as="h2">Reconciliation exceptions</CardTitle>
          <CardDescription>
            Settlement, refund, credit note, chargeback, provider fee, GST, and TDS rows are exportable.
          </CardDescription>
        </div>
        <ReceiptText className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Severity</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Reference</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, index) => (
                <tr key={`${valueToString(row.id)}-${index}`} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium">
                    {valueToString(row.exception_type ?? row.kind)}
                  </td>
                  <td className="py-3 pr-4">{valueToString(row.severity)}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={toneForStatus(valueToString(row.status))}>
                      {valueToString(row.status)}
                    </Badge>
                  </td>
                  <td className="py-3 pr-4">
                    {valueToString(row.provider_order_id ?? row.provider_reference ?? row.id)}
                  </td>
                </tr>
              ))}
              {visibleRows.length === 0 ? (
                <tr>
                  <td className="py-4 text-[var(--color-mute)]" colSpan={4}>
                    No open reconciliation exceptions.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function SupportMatrix({ matrix }: { matrix: CaseTrackingSupportMatrixAdminResponse | undefined }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Case tracking support matrix</CardTitle>
        <CardDescription>
          Internal refresh costs and evidence are visible only to platform admin.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Court</th>
                <th className="py-2 pr-4">Provider</th>
                <th className="py-2 pr-4">Refresh</th>
                <th className="py-2 pr-4">Bulk</th>
                <th className="py-2 pr-4">Status</th>
              </tr>
            </thead>
            <tbody>
              {(matrix?.rows ?? []).map((row) => (
                <tr key={row.id} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium">{row.court}</td>
                  <td className="py-3 pr-4">{row.provider}</td>
                  <td className="py-3 pr-4">{formatMoneyMinor(row.refresh_cost_minor)}</td>
                  <td className="py-3 pr-4">{formatMoneyMinor(row.bulk_refresh_cost_minor)}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={row.enabled ? "success" : "warning"}>
                      {row.enabled ? "enabled" : "disabled"}
                    </Badge>
                  </td>
                </tr>
              ))}
              {(matrix?.rows ?? []).length === 0 ? (
                <tr>
                  <td className="py-4 text-[var(--color-mute)]" colSpan={5}>
                    No support matrix rows yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function PaidProductionReadinessPage() {
  const canPlatform = useCapability("platform:admin");
  const queryClient = useQueryClient();
  const pineQuery = useQuery({
    queryKey: ["platform-admin", "pine-labs", "uat-readiness"],
    queryFn: fetchPineLabsUatReadiness,
    enabled: canPlatform,
  });
  const signoffQuery = useQuery({
    queryKey: ["platform-admin", "billing-signoff"],
    queryFn: fetchProductionBillingSignoff,
    enabled: canPlatform,
  });
  const marginQuery = useQuery({
    queryKey: ["platform-admin", "margin-readiness"],
    queryFn: fetchMarginReadiness,
    enabled: canPlatform,
  });
  const resetQuery = useQuery({
    queryKey: ["platform-admin", "password-reset-readiness"],
    queryFn: fetchPasswordResetReadiness,
    enabled: canPlatform,
  });
  const exceptionsQuery = useQuery({
    queryKey: ["platform-admin", "finance", "reconciliation-exceptions"],
    queryFn: () => fetchPlatformFinanceReport("reconciliation-exceptions"),
    enabled: canPlatform,
  });
  const supportQuery = useQuery({
    queryKey: ["platform-admin", "case-tracking", "support-matrix"],
    queryFn: fetchPlatformSupportMatrix,
    enabled: canPlatform,
  });

  const pineEvidenceMutation = useMutation({
    mutationFn: recordPineLabsUatEvidence,
    onSuccess: async () => {
      toast.success("UAT evidence recorded.");
      await queryClient.invalidateQueries({
        queryKey: ["platform-admin", "pine-labs", "uat-readiness"],
      });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record UAT evidence.")),
  });
  const activationMutation = useMutation({
    mutationFn: recordPineLabsActivationDecision,
    onSuccess: async () => {
      toast.success("Activation decision recorded.");
      await queryClient.invalidateQueries({
        queryKey: ["platform-admin", "pine-labs", "uat-readiness"],
      });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record decision.")),
  });
  const signoffMutation = useMutation({
    mutationFn: recordProductionBillingSignoffEvidence,
    onSuccess: async () => {
      toast.success("Billing signoff evidence recorded.");
      await queryClient.invalidateQueries({
        queryKey: ["platform-admin", "billing-signoff"],
      });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record signoff evidence.")),
  });

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Paid-production readiness is restricted to the configured founder super-admin."
        />
      </div>
    );
  }

  const loading =
    pineQuery.isPending ||
    signoffQuery.isPending ||
    marginQuery.isPending ||
    resetQuery.isPending ||
    exceptionsQuery.isPending ||
    supportQuery.isPending;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Paid-production readiness"
        description="Pine Labs UAT evidence, production billing signoff, margin gates, finance reconciliation, and case tracking cost readiness."
        actions={
          <div className="flex gap-2">
            <Button href="/app/platform-admin/costs" variant="outline">
              Costs
            </Button>
            <Button href="/app/platform-admin/provider-events" variant="outline">
              Provider events
            </Button>
          </div>
        }
      />

      {loading ? (
        <Card>
          <CardContent className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading readiness evidence...
          </CardContent>
        </Card>
      ) : null}

      <ReadinessSummary
        pine={pineQuery.data}
        signoff={signoffQuery.data}
        margin={marginQuery.data}
      />

      <PineEvidenceTable
        readiness={pineQuery.data}
        busy={pineEvidenceMutation.isPending || activationMutation.isPending}
        onRecordPass={(scenarioCode) =>
          pineEvidenceMutation.mutate({
            runId: pineQuery.data?.run_id ?? null,
            scenarioCode,
            resultStatus: "pass",
            operatorNotes: "Founder console evidence update.",
          })
        }
        onDecision={(decision) =>
          activationMutation.mutate({
            runId: pineQuery.data?.run_id ?? null,
            founderGoNoGo: decision,
            notes:
              decision === "go"
                ? "Founder go decision after complete UAT evidence."
                : "Founder no-go decision recorded; live provider remains disabled.",
          })
        }
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <BillingSignoffTable
          signoff={signoffQuery.data}
          busy={signoffMutation.isPending}
          onRecordPass={(checkCode) =>
            signoffMutation.mutate({
              signoffId: signoffQuery.data?.signoff_id ?? null,
              checkCode,
              resultStatus: "pass",
              evidenceRef: "founder-console",
              operatorNotes: "Founder console signoff evidence.",
            })
          }
        />
        <PasswordResetReadiness readiness={resetQuery.data} />
      </div>

      <MarginReadiness readiness={marginQuery.data} />

      <div className="grid gap-6 xl:grid-cols-2">
        <FinanceExceptions rows={exceptionsQuery.data?.rows ?? []} />
        <SupportMatrix matrix={supportQuery.data} />
      </div>
    </div>
  );
}
