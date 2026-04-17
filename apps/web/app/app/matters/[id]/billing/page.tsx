"use client";

import { Banknote, Clock, Receipt } from "lucide-react";
import { useParams } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function formatMoney(minor: number, currency = "INR"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(minor / 100);
}

export default function MatterBillingPage() {
  const params = useParams<{ id: string }>();
  const { data } = useMatterWorkspace(params.id);
  if (!data) return null;

  const totalBilled = data.invoices.reduce(
    (acc, invoice) => acc + invoice.total_amount_minor,
    0,
  );
  const totalReceived = data.invoices.reduce(
    (acc, invoice) => acc + invoice.amount_received_minor,
    0,
  );
  const balanceDue = data.invoices.reduce(
    (acc, invoice) => acc + invoice.balance_due_minor,
    0,
  );
  const billableMinutes = data.time_entries
    .filter((t) => t.billable)
    .reduce((acc, t) => acc + t.duration_minutes, 0);

  return (
    <div className="flex flex-col gap-5">
      <section className="grid gap-4 md:grid-cols-4">
        <KpiCard icon={Receipt} label="Total billed" value={formatMoney(totalBilled)} />
        <KpiCard icon={Banknote} label="Collected" value={formatMoney(totalReceived)} />
        <KpiCard icon={Banknote} label="Balance due" value={formatMoney(balanceDue)} />
        <KpiCard icon={Clock} label="Billable minutes" value={String(billableMinutes)} />
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Invoices</CardTitle>
          <CardDescription>Every invoice on this matter.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.invoices.length === 0 ? (
            <EmptyState
              icon={Receipt}
              title="No invoices yet"
              description="Issue invoices from the legacy console. Pine Labs collection links are enabled."
            />
          ) : (
            <table className="w-full text-sm tabular">
              <thead>
                <tr className="border-b border-[var(--color-line)] bg-[var(--color-bg)] text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  <th className="px-4 py-2.5 text-left font-semibold">Invoice</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Issued</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Total</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Balance</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.invoices.map((inv) => (
                  <tr
                    key={inv.id}
                    className="border-b border-[var(--color-line-2)] last:border-0"
                  >
                    <td className="px-4 py-3 font-medium text-[var(--color-ink)]">
                      {inv.invoice_number}
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                      {inv.issued_on ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {formatMoney(inv.total_amount_minor, inv.currency)}
                    </td>
                    <td className="px-4 py-3 text-right text-[var(--color-ink-2)]">
                      {formatMoney(inv.balance_due_minor, inv.currency)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={inv.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent time entries</CardTitle>
          <CardDescription>Last 20 entries across the team.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.time_entries.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No time logged"
              description="Log time from the legacy console; a rewritten timekeeper lands with billing workstream (§5.3)."
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line-2)]">
              {data.time_entries.slice(0, 20).map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-start justify-between gap-4 py-3"
                >
                  <div>
                    <div className="text-sm text-[var(--color-ink)]">{entry.description}</div>
                    <div className="text-xs text-[var(--color-mute)]">
                      {entry.work_date} · {entry.author_name ?? "Unknown"}
                    </div>
                  </div>
                  <div className="text-right text-xs text-[var(--color-ink-2)]">
                    <div className="font-semibold">{entry.duration_minutes} min</div>
                    <div className="text-[var(--color-mute)]">
                      {entry.billable ? "Billable" : "Non-billable"}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Banknote;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-5">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-bg)] text-[var(--color-ink-3)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-xl font-semibold tracking-tight text-[var(--color-ink)]">
            {value}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
