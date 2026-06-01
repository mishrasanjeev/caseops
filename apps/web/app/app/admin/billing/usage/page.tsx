"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

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
  downloadApiFile,
  fetchBillingSpendReport,
  fetchBillingUsage,
} from "@/lib/api/endpoints";
import type { BillingUsageBreakdownRow } from "@/lib/api/schemas";
import { formatBytes, formatLimit, ratioPercent } from "@/lib/billing-format";

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
  const report = spendQuery.data ?? usageQuery.data;

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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Tenant usage"
        title="Usage and spend report"
        description="This tenant-facing report shows quantities, credits, and storage usage only."
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

      {usageQuery.isPending || spendQuery.isPending ? (
        <Card>
          <CardContent className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading usage...
          </CardContent>
        </Card>
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
