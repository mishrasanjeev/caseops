"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
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
  downloadApiFile,
  fetchBillingSpendReport,
  fetchBillingUsage,
} from "@/lib/api/endpoints";
import type {
  BillingProviderSpendRow,
  BillingUsageBreakdownRow,
} from "@/lib/api/schemas";
import {
  formatBytes,
  formatLimit,
  formatMoneyMinor,
  ratioPercent,
} from "@/lib/billing-format";

function quotaLabel(percent: number): string {
  if (percent >= 95) return "95% limit warning";
  if (percent >= 85) return "85% limit warning";
  if (percent >= 70) return "70% limit warning";
  return "Within limit";
}

function BreakdownTable({
  title,
  rows,
}: {
  title: string;
  rows: BillingUsageBreakdownRow[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{title}</CardTitle>
        <CardDescription>Quantities and AI credits only.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Label</th>
                <th className="py-2 pr-4">Quantity</th>
                <th className="py-2 pr-4">Credits</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${title}-${row.key}`} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium text-[var(--color-ink)]">
                    {row.label}
                  </td>
                  <td className="py-3 pr-4">{formatLimit(row.quantity)}</td>
                  <td className="py-3 pr-4">{formatLimit(row.credits)}</td>
                </tr>
              ))}
              {rows.length === 0 ? (
                <tr>
                  <td className="py-4 text-[var(--color-mute)]" colSpan={3}>
                    No usage in this period.
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

function BillingUsageLoading() {
  return (
    <div
      className="flex flex-col gap-6"
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-testid="billing-usage-loading"
    >
      <span className="sr-only">Loading usage and spend report.</span>
      <div className="grid gap-4 md:grid-cols-3" aria-hidden="true">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
      <Card aria-hidden="true">
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-14 w-full" />
        </CardContent>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2" aria-hidden="true">
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-44 w-full" />
      </div>
    </div>
  );
}

function ProviderSpendTable({ rows }: { rows: BillingProviderSpendRow[] }) {
  return (
    <Card data-testid="provider-spend-by-account">
      <CardHeader>
        <CardTitle as="h2">Paid legal-data providers</CardTitle>
        <CardDescription>
          Each provider contribution counts toward one shared ₹1,000 monthly account budget
          unless an explicit provider policy applies. Cached results do not add spend.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="py-2 pr-4">Provider</th>
                <th className="py-2 pr-4">Provider spend</th>
                <th className="py-2 pr-4">Budget scope</th>
                <th className="py-2 pr-4">Budget used</th>
                <th className="py-2 pr-4">Monthly limit</th>
                <th className="py-2">Remaining</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.provider_key} className="border-b border-[var(--color-line-2)]">
                  <td className="py-3 pr-4 font-medium text-[var(--color-ink)]">{row.label}</td>
                  <td className="py-3 pr-4">{formatMoneyMinor(row.spent_minor, row.currency)}</td>
                  <td className="py-3 pr-4">
                    {row.budget_scope === "account" ? "Shared account" : "Provider"}
                  </td>
                  <td className="py-3 pr-4">
                    {formatMoneyMinor(row.budget_spent_minor, row.currency)}
                  </td>
                  <td className="py-3 pr-4">
                    {row.unlimited
                      ? "Unlimited"
                      : formatMoneyMinor(row.monthly_limit_minor, row.currency)}
                  </td>
                  <td className="py-3">
                    {row.unlimited
                      ? "Unlimited"
                      : formatMoneyMinor(row.remaining_minor, row.currency)}
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

export default function TenantBillingUsagePage() {
  const [downloading, setDownloading] = useState(false);
  const usageQuery = useQuery({
    queryKey: ["billing", "usage"],
    queryFn: fetchBillingUsage,
  });
  const spendQuery = useQuery({
    queryKey: ["billing", "spend-report"],
    queryFn: fetchBillingSpendReport,
  });
  // Do not render a faster query's fallback as final state while the other
  // initial request is still unresolved. In particular, an empty usage
  // fallback beside an announced loader tells the user both "loading" and
  // "there is no usage" at once. `isPending` is false during background
  // refetches with retained data, so already-valid reports stay visible.
  const isPending = usageQuery.isPending || spendQuery.isPending;
  const report = isPending ? undefined : spendQuery.data ?? usageQuery.data;

  async function exportSpend() {
    setDownloading(true);
    try {
      await downloadApiFile(
        "/api/billing/reports/spend/export",
        "caseops-spend-report.csv",
      );
      toast.success("Spend report downloaded.");
    } catch (err) {
      toast.error(apiErrorMessage(err, "Could not export spend report."));
    } finally {
      setDownloading(false);
    }
  }

  const snapshot = report?.snapshot;
  const storagePct = snapshot ? ratioPercent(snapshot.storage_used_bytes, snapshot.storage_limit_bytes) : 0;
  const creditPct = snapshot
    ? ratioPercent(snapshot.ai_credits_used, snapshot.ai_credits_included ?? null)
    : 0;
  const trackedPct = snapshot
    ? ratioPercent(snapshot.tracked_cases_used, snapshot.tracked_cases_limit ?? null)
    : 0;
  const manualRefreshPct = snapshot
    ? ratioPercent(
        snapshot.manual_refreshes_used_today,
        snapshot.manual_refreshes_limit_daily ?? null,
      )
    : 0;
  const quotaWarnings = snapshot
    ? [
        { label: "AI credits", percent: creditPct },
        { label: "Tracked cases", percent: trackedPct },
        { label: "Manual refreshes today", percent: manualRefreshPct },
        { label: "Storage", percent: storagePct },
      ].filter((item) => item.percent >= 70)
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Tenant usage"
        title="Usage and spend report"
        description="This tenant-facing report publishes provider spend, quantities, credits, and storage usage for this workspace."
        actions={
          <div className="flex gap-2">
            <Button href="/app/admin/billing" variant="outline">
              Billing
            </Button>
            <Button type="button" onClick={exportSpend} disabled={downloading}>
              <Download className="h-4 w-4" aria-hidden />
              Export spend
            </Button>
          </div>
        }
      />

      {isPending ? (
        <BillingUsageLoading />
      ) : null}

      {snapshot ? (
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
            <div className="text-sm text-[var(--color-mute)]">AI credits used</div>
            <div className="mt-1 text-2xl font-semibold text-[var(--color-ink)]">
              {formatLimit(snapshot.ai_credits_used)}
            </div>
            <div className="mt-3 h-2 rounded-full bg-[var(--color-line)]">
              <div className="h-full rounded-full bg-[var(--color-brand-700)]" style={{ width: `${creditPct}%` }} />
            </div>
          </div>
          <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
            <div className="text-sm text-[var(--color-mute)]">Top-up credits</div>
            <div className="mt-1 text-2xl font-semibold text-[var(--color-ink)]">
              {formatLimit(snapshot.topup_credits_available)}
            </div>
            <Link href="/app/admin/billing" className="mt-3 inline-block text-sm font-medium text-[var(--color-brand-700)]">
              Buy credits
            </Link>
          </div>
          <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)]">
            <div className="text-sm text-[var(--color-mute)]">Storage used</div>
            <div className="mt-1 text-2xl font-semibold text-[var(--color-ink)]">
              {formatBytes(snapshot.storage_used_bytes)}
            </div>
            <div className="mt-3 h-2 rounded-full bg-[var(--color-line)]">
              <div className="h-full rounded-full bg-[var(--color-brand-700)]" style={{ width: `${storagePct}%` }} />
            </div>
          </div>
        </div>
      ) : null}

      {snapshot ? (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle as="h2">Quota warnings</CardTitle>
              <CardDescription>
                Usage warnings appear at 70%, 85%, and 95%; exhausted credits require top-up.
              </CardDescription>
            </div>
            <AlertTriangle className="h-5 w-5 text-amber-700" aria-hidden />
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {quotaWarnings.map((warning) => (
              <div
                key={warning.label}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900"
              >
                <span className="font-medium">{warning.label}</span>
                <span>{quotaLabel(warning.percent)}</span>
              </div>
            ))}
            {snapshot.ai_credits_used >= (snapshot.ai_credits_included ?? 0) ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
                Included credits are exhausted. Buy credits before additional AI actions run.
              </div>
            ) : null}
            {quotaWarnings.length === 0 &&
            snapshot.ai_credits_used < (snapshot.ai_credits_included ?? 0) ? (
              <div className="text-[var(--color-mute)]">No active quota warnings.</div>
            ) : null}
            <Link
              href="/app/admin/billing"
              className="inline-block font-medium text-[var(--color-brand-700)]"
            >
              Buy credits or capacity
            </Link>
          </CardContent>
        </Card>
      ) : null}

      {report ? <ProviderSpendTable rows={report.by_provider} /> : null}

      {report ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <BreakdownTable title="By feature" rows={report.by_feature} />
          <BreakdownTable title="By user" rows={report.by_user} />
          <BreakdownTable title="By matter" rows={report.by_matter} />
          <BreakdownTable title="By tracked case" rows={report.by_tracked_case} />
          <BreakdownTable title="Daily" rows={report.daily} />
          <BreakdownTable title="Blocked events" rows={report.blocked_events} />
        </div>
      ) : null}
    </div>
  );
}
