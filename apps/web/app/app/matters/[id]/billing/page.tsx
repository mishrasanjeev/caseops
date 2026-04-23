"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote,
  Clock,
  ExternalLink,
  Loader2,
  Receipt,
  RefreshCw,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { NewInvoiceDialog } from "@/components/app/NewInvoiceDialog";
import { NewTimeEntryDialog } from "@/components/app/NewTimeEntryDialog";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createInvoicePaymentLink,
  fetchPaymentConfig,
  syncInvoicePaymentLink,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";
import type { WorkspaceInvoice, WorkspaceTimeEntry } from "@/lib/api/workspace-types";

function formatMoney(minor: number, currency = "INR"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(minor / 100);
}

function canIssuePaymentLink(inv: WorkspaceInvoice): boolean {
  if (inv.status === "void" || inv.status === "paid") return false;
  return inv.balance_due_minor > 0;
}

function hasPaymentAttempt(inv: WorkspaceInvoice): boolean {
  // BUG-016 Codex fix 2026-04-21: Sync is only meaningful after a
  // Pay Link has been issued. Gate the button on the workspace
  // response so users don't click into a 409 precondition error.
  return (inv.payment_attempts?.length ?? 0) > 0;
}

export default function MatterBillingPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const { data } = useMatterWorkspace(matterId);
  const queryClient = useQueryClient();
  const canIssueInvoice = useCapability("invoices:issue");
  const canSendPaymentLink = useCapability("invoices:send_payment_link");
  const canWriteTimeEntry = useCapability("time_entries:write");
  // BUG-015 Codex fix 2026-04-21: gate Pay Link on environment-
  // level gateway readiness. Pay Link only renders when Pine Labs
  // is configured; otherwise the invoice row skips that action
  // so the user isn't invited into a preventable 503.
  const paymentConfigQuery = useQuery({
    queryKey: ["payments", "config"],
    queryFn: () => fetchPaymentConfig(),
    staleTime: 5 * 60 * 1000,
    enabled: canSendPaymentLink,
  });
  const pineLabsConfigured =
    paymentConfigQuery.data?.pine_labs_configured === true;

  const [pendingPaymentInvoiceId, setPendingPaymentInvoiceId] = useState<string | null>(
    null,
  );
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [billableOnly, setBillableOnly] = useState(false);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });

  const paymentLinkMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      createInvoicePaymentLink({ matterId, invoiceId }),
    onMutate: (invoiceId) => setPendingPaymentInvoiceId(invoiceId),
    onSuccess: async (record) => {
      await invalidate();
      if (record?.pine_labs_payment_url) {
        toast.success("Payment link ready — opening in a new tab.");
        window.open(record.pine_labs_payment_url, "_blank", "noopener,noreferrer");
      } else {
        toast.success("Payment link request accepted.");
      }
    },
    onError: (err) => {
      toast.error(
        apiErrorMessage(err, "Could not issue a payment link."),
      );
    },
    onSettled: () => setPendingPaymentInvoiceId(null),
  });

  const syncPaymentMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      syncInvoicePaymentLink({ matterId, invoiceId }),
    onMutate: (invoiceId) => setPendingPaymentInvoiceId(invoiceId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Payment status refreshed.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not sync payment."));
    },
    onSettled: () => setPendingPaymentInvoiceId(null),
  });

  const filteredTimeEntries = useMemo(() => {
    if (!data) return [] as WorkspaceTimeEntry[];
    return data.time_entries.filter((entry) => {
      if (billableOnly && !entry.billable) return false;
      if (fromDate && entry.work_date < fromDate) return false;
      if (toDate && entry.work_date > toDate) return false;
      return true;
    });
  }, [data, fromDate, toDate, billableOnly]);

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
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Invoices</CardTitle>
            <CardDescription>Every invoice on this matter.</CardDescription>
          </div>
          {canIssueInvoice ? <NewInvoiceDialog matterId={matterId} /> : null}
        </CardHeader>
        <CardContent>
          {data.invoices.length === 0 ? (
            <EmptyState
              icon={Receipt}
              title="No invoices yet"
              description={
                canIssueInvoice
                  ? "Issue the first invoice on this matter. Uninvoiced billable time rolls in by default."
                  : "Ask a team member with billing permissions to issue the first invoice."
              }
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
                  {canSendPaymentLink ? (
                    <th className="px-4 py-2.5 text-right font-semibold">Payments</th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {data.invoices.map((inv) => {
                  const isPending = pendingPaymentInvoiceId === inv.id;
                  return (
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
                      {canSendPaymentLink ? (
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex items-center gap-2">
                            {canIssuePaymentLink(inv) && pineLabsConfigured ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={isPending}
                                onClick={() => paymentLinkMutation.mutate(inv.id)}
                                data-testid={`invoice-payment-link-${inv.id}`}
                              >
                                {isPending && paymentLinkMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                ) : (
                                  <ExternalLink className="h-4 w-4" aria-hidden />
                                )}
                                Pay link
                              </Button>
                            ) : null}
                            {inv.balance_due_minor > 0 &&
                            inv.status !== "void" &&
                            hasPaymentAttempt(inv) ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={isPending}
                                onClick={() => syncPaymentMutation.mutate(inv.id)}
                                data-testid={`invoice-payment-sync-${inv.id}`}
                              >
                                {isPending && syncPaymentMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                ) : (
                                  <RefreshCw className="h-4 w-4" aria-hidden />
                                )}
                                Sync
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Time entries</CardTitle>
            <CardDescription>
              {filteredTimeEntries.length === data.time_entries.length
                ? `${data.time_entries.length} total`
                : `${filteredTimeEntries.length} of ${data.time_entries.length} shown`}
            </CardDescription>
          </div>
          {canWriteTimeEntry ? <NewTimeEntryDialog matterId={matterId} /> : null}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <div className="flex flex-col gap-1">
              <Label htmlFor="time-from">From</Label>
              <Input
                id="time-from"
                type="date"
                value={fromDate}
                onChange={(event) => setFromDate(event.target.value)}
                data-testid="time-filter-from"
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="time-to">To</Label>
              <Input
                id="time-to"
                type="date"
                value={toDate}
                onChange={(event) => setToDate(event.target.value)}
                data-testid="time-filter-to"
              />
            </div>
            <label className="flex items-center gap-2 pb-2 text-sm text-[var(--color-ink-2)]">
              <input
                type="checkbox"
                checked={billableOnly}
                onChange={(event) => setBillableOnly(event.target.checked)}
                data-testid="time-filter-billable"
              />
              <span>Billable only</span>
            </label>
          </div>

          {filteredTimeEntries.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No time logged"
              description={
                canWriteTimeEntry
                  ? "Log the first entry. Billable time rolls into the next invoice automatically."
                  : "Ask a team member with time-entry permission to log work here."
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line-2)]">
              {filteredTimeEntries.map((entry) => (
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
