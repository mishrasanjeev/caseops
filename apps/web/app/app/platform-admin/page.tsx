"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Building2,
  CreditCard,
  Loader2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

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
import {
  fetchPlatformEnrollments,
  fetchPlatformMarginAlerts,
  fetchPlatformOverview,
} from "@/lib/api/endpoints";
import { formatLimit, formatMoneyMinor } from "@/lib/billing-format";
import { useCapability } from "@/lib/capabilities";

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-[var(--color-mute)]">{label}</div>
        <Icon className="h-4 w-4 text-[var(--color-brand-700)]" aria-hidden />
      </div>
      <div className="mt-2 text-2xl font-semibold text-[var(--color-ink)]">{value}</div>
    </div>
  );
}

export default function PlatformAdminPage() {
  const canPlatform = useCapability("platform:admin");
  const overviewQuery = useQuery({
    queryKey: ["platform-admin", "overview"],
    queryFn: fetchPlatformOverview,
    enabled: canPlatform,
  });
  const enrollmentsQuery = useQuery({
    queryKey: ["platform-admin", "enrollments"],
    queryFn: fetchPlatformEnrollments,
    enabled: canPlatform,
  });
  const alertsQuery = useQuery({
    queryKey: ["platform-admin", "margin-alerts"],
    queryFn: fetchPlatformMarginAlerts,
    enabled: canPlatform,
  });

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Platform administration is restricted to the configured founder super-admin."
        />
        <Card>
          <CardHeader>
            <CardTitle as="h2">Founder-only console</CardTitle>
            <CardDescription>
              Workspace owner and tenant admin roles do not grant this access.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const overview = overviewQuery.data;
  const alerts = alertsQuery.data?.alerts ?? overview?.margin_alerts ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Platform admin"
        description="Cross-tenant billing, revenue, costs, margins, enrollment, and provider reconciliation."
        actions={
          <div className="flex gap-2">
            <Button href="/app/platform-admin/integrations" variant="outline">
              Integrations
            </Button>
            <Button href="/app/platform-admin/costs" variant="outline">
              Costs
            </Button>
            <Button href="/app/platform-admin/profit" variant="outline">
              Profit dashboard
            </Button>
            <Button href="/app/platform-admin/provider-events" variant="outline">
              Provider events
            </Button>
          </div>
        }
      />

      {overviewQuery.isPending ? (
        <Card>
          <CardContent className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading platform overview...
          </CardContent>
        </Card>
      ) : null}

      {overview ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Monthly recurring revenue"
            value={formatMoneyMinor(overview.mrr_minor)}
            icon={CreditCard}
          />
          <MetricCard
            label="Annual recurring revenue"
            value={formatMoneyMinor(overview.arr_minor)}
            icon={BarChart3}
          />
          <MetricCard
            label="Gross profit"
            value={formatMoneyMinor(overview.gross_profit_minor)}
            icon={ShieldCheck}
          />
          <MetricCard
            label="Gross margin"
            value={
              overview.gross_margin_bps === null
                ? "n/a"
                : `${(overview.gross_margin_bps / 100).toFixed(1)}%`
            }
            icon={Building2}
          />
        </div>
      ) : null}

      {overview ? (
        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <Card>
            <CardHeader>
              <CardTitle as="h2">Operating counters</CardTitle>
              <CardDescription>Founder-only platform metrics.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Active subscriptions</span>
                <span className="font-medium">{formatLimit(overview.active_subscriptions)}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Trials</span>
                <span className="font-medium">{formatLimit(overview.trial_count)}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Failed payments</span>
                <span className="font-medium">{formatLimit(overview.failed_payments)}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Variable costs</span>
                <span className="font-medium">
                  {formatMoneyMinor(overview.total_variable_cost_minor)}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle as="h2">Margin and loss-risk alerts</CardTitle>
                <CardDescription>
                  Internal cost and profit visibility is restricted to platform admin.
                </CardDescription>
              </div>
              <AlertTriangle className="h-5 w-5 text-amber-700" aria-hidden />
            </CardHeader>
            <CardContent className="space-y-3">
              {alerts.map((alert, index) => (
                <div
                  key={String(alert.company_id ?? alert.plan_code ?? index)}
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
                >
                  <div className="font-semibold">
                    {String(alert.company_name ?? alert.plan_code ?? "Margin alert")}
                  </div>
                  <div className="mt-1">
                    {String(alert.message ?? alert.reason ?? "Review contribution margin.")}
                  </div>
                </div>
              ))}
              {alerts.length === 0 ? (
                <div className="text-sm text-[var(--color-mute)]">
                  No active margin alerts.
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle as="h2">Recent enrollments</CardTitle>
          <CardDescription>Trial starts and demo requests from the pricing flow.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                <tr>
                  <th className="py-2 pr-4">Company</th>
                  <th className="py-2 pr-4">Contact</th>
                  <th className="py-2 pr-4">Segment</th>
                  <th className="py-2 pr-4">Plan</th>
                  <th className="py-2 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {(enrollmentsQuery.data?.enrollments ?? []).map((row) => (
                  <tr key={row.id} className="border-b border-[var(--color-line-2)]">
                    <td className="py-3 pr-4">{row.company_name ?? row.company_id ?? "-"}</td>
                    <td className="py-3 pr-4">
                      <div className="font-medium">{row.contact_name}</div>
                      <div className="text-xs text-[var(--color-mute)]">{row.contact_email}</div>
                    </td>
                    <td className="py-3 pr-4">{row.segment}</td>
                    <td className="py-3 pr-4">{row.selected_plan ?? "-"}</td>
                    <td className="py-3 pr-4">
                      <Badge tone="brand">{row.status}</Badge>
                    </td>
                  </tr>
                ))}
                {(enrollmentsQuery.data?.enrollments ?? []).length === 0 ? (
                  <tr>
                    <td className="py-4 text-[var(--color-mute)]" colSpan={5}>
                      No enrollment activity yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="mt-4">
            <Link
              href="/app/platform-admin/profit"
              className="text-sm font-medium text-[var(--color-brand-700)]"
            >
              Open company profitability table
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
