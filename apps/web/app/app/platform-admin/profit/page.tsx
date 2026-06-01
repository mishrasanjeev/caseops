"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Loader2, ShieldCheck } from "lucide-react";
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
  fetchPlatformCompanyProfitability,
  fetchPlatformProfitReport,
} from "@/lib/api/endpoints";
import type { PlatformProfitRow } from "@/lib/api/schemas";
import { formatMoneyMinor } from "@/lib/billing-format";
import { useCapability } from "@/lib/capabilities";

function marginLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${(value / 100).toFixed(1)}%`;
}

function ProfitTable({ rows }: { rows: PlatformProfitRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
          <tr>
            <th className="py-2 pr-4">Company</th>
            <th className="py-2 pr-4">Earnings</th>
            <th className="py-2 pr-4">Net revenue</th>
            <th className="py-2 pr-4">Taxes</th>
            <th className="py-2 pr-4">Provider cost</th>
            <th className="py-2 pr-4">LLM cost</th>
            <th className="py-2 pr-4">Refresh cost</th>
            <th className="py-2 pr-4">Gross profit</th>
            <th className="py-2 pr-4">Margin</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={`${row.company_id ?? row.company_name ?? "row"}-${index}`}
              className="border-b border-[var(--color-line-2)]"
            >
              <td className="py-3 pr-4 font-medium">
                {row.company_name ?? row.company_id ?? "Unknown"}
              </td>
              <td className="py-3 pr-4">{formatMoneyMinor(row.gross_revenue_minor)}</td>
              <td className="py-3 pr-4">
                {formatMoneyMinor(row.recognized_revenue_minor)}
              </td>
              <td className="py-3 pr-4">{formatMoneyMinor(row.tax_minor)}</td>
              <td className="py-3 pr-4">
                {formatMoneyMinor(row.payment_provider_cost_minor)}
              </td>
              <td className="py-3 pr-4">{formatMoneyMinor(row.llm_cost_minor)}</td>
              <td className="py-3 pr-4">
                {formatMoneyMinor(row.case_refresh_cost_minor)}
              </td>
              <td className="py-3 pr-4">{formatMoneyMinor(row.gross_profit_minor)}</td>
              <td className="py-3 pr-4">{marginLabel(row.gross_margin_bps)}</td>
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td className="py-4 text-[var(--color-mute)]" colSpan={9}>
                No profit rollups yet.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export default function PlatformProfitPage() {
  const canPlatform = useCapability("platform:admin");
  const [downloading, setDownloading] = useState<string | null>(null);
  const profitQuery = useQuery({
    queryKey: ["platform-admin", "profit-report"],
    queryFn: fetchPlatformProfitReport,
    enabled: canPlatform,
  });
  const companyQuery = useQuery({
    queryKey: ["platform-admin", "company-profitability"],
    queryFn: fetchPlatformCompanyProfitability,
    enabled: canPlatform,
  });

  async function runDownload(path: string, fallback: string) {
    setDownloading(path);
    try {
      await downloadApiFile(path, fallback);
      toast.success("Export started.");
    } catch (err) {
      toast.error(apiErrorMessage(err, "Export failed."));
    } finally {
      setDownloading(null);
    }
  }

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Profit reports are restricted to the configured founder super-admin."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Profit dashboard"
        description="Internal revenue, provider costs, estimated COGS, gross profit, and margin."
        actions={
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={downloading === "/api/platform-admin/revenue/export"}
              onClick={() =>
                runDownload(
                  "/api/platform-admin/revenue/export",
                  "caseops-platform-revenue.csv",
                )
              }
            >
              <Download className="h-4 w-4" aria-hidden />
              Revenue export
            </Button>
            <Button
              type="button"
              disabled={downloading === "/api/platform-admin/profit/export"}
              onClick={() =>
                runDownload(
                  "/api/platform-admin/profit/export",
                  "caseops-platform-profit.csv",
                )
              }
            >
              <Download className="h-4 w-4" aria-hidden />
              Profit export
            </Button>
          </div>
        }
      />

      {profitQuery.isPending || companyQuery.isPending ? (
        <Card>
          <CardContent className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading profit reports...
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">Company profitability</CardTitle>
            <CardDescription>
              Company-level profitability with internal costs visible only here.
            </CardDescription>
          </div>
          <ShieldCheck className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
        </CardHeader>
        <CardContent>
          <ProfitTable rows={companyQuery.data?.companies ?? []} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Profit rollups</CardTitle>
          <CardDescription>Monthly platform profit rollups.</CardDescription>
        </CardHeader>
        <CardContent>
          <ProfitTable rows={profitQuery.data?.rows ?? []} />
        </CardContent>
      </Card>
    </div>
  );
}
