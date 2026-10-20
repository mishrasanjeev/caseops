"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/Button";
import { formatMoneyMinor } from "@/lib/billing-format";
import { platformApi } from "@/lib/platform/client";
import type { ConsoleReport } from "@/lib/platform/schemas";
import { usePlatformLoad } from "@/lib/platform/use-load";

import { PlatformPagination } from "./PlatformPagination";

const date = (value: string) => new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium" }).format(new Date(value));
const money = (value: number | null) => value === null ? "Not recorded" : formatMoneyMinor(value, "INR", 2);

function ReportRows({ data, kind }: { data: ConsoleReport; kind: string }) {
  if (!data.items.length) return <p className="py-8 text-sm text-[var(--color-mute)]">No recorded results for this page.</p>;
  return <div className="relative min-w-0 overflow-x-auto" tabIndex={0} aria-label="Scrollable report results" role="region">
    <table className="w-full min-w-[46rem] border-collapse text-left text-sm">
      <caption className="sr-only">{data.coverage.replaceAll("_", " ")}</caption>
      <thead className="border-y border-[var(--color-line)]">
        {data.coverage === "recorded_usage" ? <tr>{["Account", "Feature", "Quantity", "Credits", "Estimated internal cost"].map((label) => <th key={label} scope="col" className="p-3 font-bold">{label}</th>)}</tr>
          : data.coverage === "recorded_payments" ? <tr>{["Account", "Payment date", "Reference", "Paid", "Tax"].map((label) => <th key={label} scope="col" className="p-3 font-bold">{label}</th>)}</tr>
          : <tr>{["Account", kind === "company-profitability" ? "Recorded rollups" : "Period (IST)", "Revenue", "Variable cost", "Gross profit", "Margin", kind === "company-profitability" ? "Loss risk" : "Status", "Costs"].map((label) => <th key={label} scope="col" className="p-3 font-bold">{label}</th>)}</tr>}
      </thead>
      <tbody>{data.items.map((row, index) => {
        if ("feature_key" in row) return <tr key={`${row.company_id}:${row.feature_key}:${index}`} className="border-b border-[var(--color-line)] align-top">
          <td className="max-w-56 break-all p-3">{row.company_id}</td><td className="p-3">{row.feature_key}</td><td className="p-3 tabular-nums">{row.quantity}</td><td className="p-3 tabular-nums">{row.credits}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.estimated_internal_cost_minor, "INR", 2)}</td>
        </tr>;
        if ("merchant_reference" in row) return <tr key={`${row.company_id}:${row.merchant_reference}:${index}`} className="border-b border-[var(--color-line)] align-top">
          <td className="max-w-56 break-all p-3">{row.company_id}</td><td className="p-3">{row.paid_at ? date(row.paid_at) : "Not recorded"}</td><td className="max-w-56 break-all p-3">{row.merchant_reference}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.amount_paid_minor, "INR", 2)}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.tax_amount_minor, "INR", 2)}</td>
        </tr>;
        if ("rollup_count" in row) return <tr key={row.company_id} className="border-b border-[var(--color-line)] align-top">
          <td className="max-w-56 break-words p-3">{row.company_name}</td><td className="p-3 tabular-nums">{row.rollup_count}</td><td className="p-3 tabular-nums">{money(row.gross_revenue_minor)}</td><td className="p-3 tabular-nums">{money(row.total_variable_cost_minor)}</td><td className="p-3 tabular-nums">{money(row.gross_profit_minor)}</td><td className="p-3 tabular-nums">{row.gross_margin_bps === null ? "Not recorded" : `${(row.gross_margin_bps / 100).toFixed(1)}%`}</td><td className="p-3">{row.loss_risk === null ? "Not recorded" : row.loss_risk ? "Yes" : "No"}</td>
          <td className="min-w-60 p-3"><details><summary className="cursor-pointer font-medium">Cost breakdown</summary><dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">{Object.entries({ "Recognized revenue": row.recognized_revenue_minor, Tax: row.tax_minor, Discounts: row.discounts_minor, "Provider cost": row.payment_provider_cost_minor, "Gateway cost": row.payment_gateway_cost_minor, "Model cost": row.llm_cost_minor, Embeddings: row.embedding_cost_minor, "Case refresh": row.case_refresh_cost_minor, Documents: row.document_processing_cost_minor, Storage: row.storage_cost_minor, "Manual support": row.manual_support_cost_minor, "Manual research": row.manual_research_cost_minor }).map(([label, value]) => <div className="contents" key={label}><dt>{label}</dt><dd className="tabular-nums">{money(value)}</dd></div>)}</dl></details></td>
        </tr>;
        return <tr key={`${row.company_id}:${row.period_start}:${index}`} className="border-b border-[var(--color-line)] align-top">
          <td className="max-w-56 break-words p-3">{row.company_name ?? row.company_id}</td><td className="p-3">{date(row.period_start)} - {date(row.period_end)}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.gross_revenue_minor, "INR", 2)}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.total_variable_cost_minor, "INR", 2)}</td><td className="p-3 tabular-nums">{formatMoneyMinor(row.gross_profit_minor, "INR", 2)}</td><td className="p-3 tabular-nums">{row.gross_margin_bps === null ? "Not available" : `${(row.gross_margin_bps / 100).toFixed(1)}%`}</td><td className="p-3">{row.status}</td>
          <td className="min-w-60 p-3"><details><summary className="cursor-pointer font-medium">Cost breakdown</summary><dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
            {Object.entries({ "Recognized revenue": row.recognized_revenue_minor, Tax: row.tax_minor, "Tax collected": row.tax_collected_minor, Discounts: row.discounts_minor, "Discount rollup": row.discount_minor, "Provider cost": row.payment_provider_cost_minor, "Gateway cost": row.payment_gateway_cost_minor, "Model cost": row.llm_cost_minor, Embeddings: row.embedding_cost_minor, "Case refresh": row.case_refresh_cost_minor, Documents: row.document_processing_cost_minor, Storage: row.storage_cost_minor, "Manual support": row.manual_support_cost_minor, "Manual research": row.manual_research_cost_minor }).map(([label, value]) => <div className="contents" key={label}><dt>{label}</dt><dd className="tabular-nums">{formatMoneyMinor(value, "INR", 2)}</dd></div>)}
          </dl></details></td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

export function PlatformFinancialReport({ kind }: { kind: "usage" | "profit" | "company-profitability" | "revenue" }) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const load = useCallback((signal: AbortSignal) => platformApi.report(kind, cursor, signal), [kind, cursor]);
  const result = usePlatformLoad(load);
  return <section className="min-w-0 space-y-4" aria-label={`${kind} report`} aria-busy={result.pending}>
    {result.pending ? <p role="status" className="py-8 text-sm">Loading report...</p> : null}
    {result.error ? <div className="space-y-3"><p role="alert" className="text-sm">{result.error}</p><Button variant="outline" onClick={result.reload}>Load report again</Button></div> : null}
    {result.data ? <><p className="text-sm text-[var(--color-mute)]">Generated {date(result.data.generated_at)} (IST); {result.data.items.length} rows on this page</p><ReportRows data={result.data} kind={kind} /></> : null}
    <PlatformPagination page={cursors.length - 1} pending={result.pending} hasNext={Boolean(result.data?.next_cursor && result.data.has_more)}
      onPrevious={() => setCursors((old) => old.slice(0, -1))} onNext={() => { const next = result.data?.next_cursor; if (next) setCursors((old) => [...old, next]); }} />
  </section>;
}

export function PlatformOverview() {
  const load = useCallback((signal: AbortSignal) => platformApi.overview(signal), []);
  const result = usePlatformLoad(load);
  if (result.pending) return <p role="status">Loading overview...</p>;
  if (result.error) return <p role="alert">{result.error}</p>;
  const data = result.data;
  if (!data) return null;
  const values = { "Configured monthly run rate": formatMoneyMinor(data.mrr_minor, "INR", 2), "Configured annual run rate": formatMoneyMinor(data.arr_minor, "INR", 2), "Active subscriptions": data.active_subscriptions, Trials: data.trial_count, "Failed payments": data.failed_payments, "Recorded rollups": data.rollup_count, "Gross revenue": money(data.gross_revenue_minor), "Recognized revenue": money(data.recognized_revenue_minor), "Variable cost": money(data.total_variable_cost_minor), "Gross profit": money(data.gross_profit_minor), "Gross margin": data.gross_margin_bps === null ? "Not recorded" : `${(data.gross_margin_bps / 100).toFixed(1)}%`, "Alerts on this page": data.margin_alerts.length };
  return <div className="space-y-5"><p className="text-sm text-[var(--color-mute)]">Generated {date(data.generated_at)} (IST).</p>
    <p className="text-sm text-[var(--color-mute)]">Configured rates include eligible trial/manual subscriptions; paid receipts and recorded rollups are separate.</p>
    <p className="text-sm text-[var(--color-mute)]">Financial totals: recorded rollups only.</p>
    <dl className="grid max-w-3xl grid-cols-[minmax(0,1fr)_auto] gap-x-5">{Object.entries(values).map(([label, value]) => <div key={label} className="contents"><dt className="border-b border-[var(--color-line)] py-3 text-sm">{label}</dt><dd className="border-b border-[var(--color-line)] py-3 text-right text-sm font-bold tabular-nums">{value}</dd></div>)}</dl>
    {data.margin_alerts_has_more ? <p className="text-sm">Additional margin alerts exist beyond this bounded overview.</p> : null}
    {data.margin_alerts.length ? <ul className="space-y-3 text-sm" aria-label="Margin and cost alerts">{data.margin_alerts.map((alert, index) => "type" in alert
      ? <li key={`${alert.type}:${alert.category}:${alert.provider}:${index}`} className="space-y-1 break-words border-b border-[var(--color-line)] pb-3">
        <p className="font-semibold">Cost guardrail warning</p>
        <p>{alert.message}</p>
        <p>{alert.category} / {alert.provider}: {formatMoneyMinor(alert.unit_amount_minor, "INR", 2)} per unit</p>
      </li>
      : <li key={`${alert.company_id}:${index}`} className="break-words border-b border-[var(--color-line)] pb-3">{alert.company_id}: {money(alert.gross_profit_minor)}; margin {alert.gross_margin_bps === null ? "not recorded" : `${(alert.gross_margin_bps / 100).toFixed(1)}%`}</li>)}</ul> : null}
  </div>;
}
