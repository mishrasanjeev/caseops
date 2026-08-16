"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CreditCard,
  Download,
  RefreshCw,
  RotateCcw,
  ShoppingCart,
  XCircle,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  cancelBillingSubscription,
  createBillingAddOnCheckout,
  createBillingCheckout,
  downloadApiFile,
  fetchBillingAddOns,
  fetchBillingCheckout,
  fetchBillingCreditLedger,
  fetchBillingInvoices,
  fetchBillingPlans,
  fetchCurrentBilling,
  reactivateBillingSubscription,
  syncBillingCheckout,
} from "@/lib/api/endpoints";
import type {
  BillingCheckoutResponse,
  BillingPlanRecord,
  BillingUsageSnapshot,
} from "@/lib/api/schemas";
import { formatBytes, formatLimit, formatMoneyMinor, ratioPercent } from "@/lib/billing-format";
import { useCapability } from "@/lib/capabilities";

function statusTone(status: string): "neutral" | "brand" | "success" | "warning" {
  if (["active", "paid", "manual_active", "completed", "succeeded"].includes(status)) {
    return "success";
  }
  if (["trialing", "pending", "requires_provider_action"].includes(status)) return "warning";
  if (["cancelled", "failed", "provider_disabled", "suspended"].includes(status)) return "neutral";
  return "brand";
}

function Metric({
  label,
  used,
  limit,
  formatter,
}: {
  label: string;
  used: number;
  limit: number | null | undefined;
  formatter?: (value: number | null | undefined) => string;
}) {
  const pct = ratioPercent(used, limit);
  const render = formatter ?? ((value) => formatLimit(value));
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-[var(--color-ink)]">{label}</span>
        <span className="text-[var(--color-mute)]">
          {render(used)} / {limit === null || limit === undefined ? "Unlimited" : render(limit)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--color-line)]">
        <div
          className="h-full rounded-full bg-[var(--color-brand-700)]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function usageMetrics(usage: BillingUsageSnapshot) {
  return [
    {
      label: "AI credits",
      used: usage.ai_credits_used,
      limit: usage.ai_credits_included ?? null,
    },
    {
      label: "Tracked cases",
      used: usage.tracked_cases_used,
      limit: usage.tracked_cases_limit ?? null,
    },
    {
      label: "Manual refreshes today",
      used: usage.manual_refreshes_used_today,
      limit: usage.manual_refreshes_limit_daily ?? null,
    },
    {
      label: "Storage",
      used: usage.storage_used_bytes,
      limit: usage.storage_limit_bytes ?? null,
      formatter: formatBytes,
    },
    {
      label: "Internal users",
      used: usage.users_internal_used,
      limit: usage.users_internal_limit ?? null,
    },
    {
      label: "Active matters",
      used: usage.matters_active_used,
      limit: usage.matters_active_limit ?? null,
    },
  ];
}

function planPrice(plan: BillingPlanRecord, interval: "month" | "year") {
  return plan.prices.find((price) => price.interval === interval) ?? null;
}

function checkoutMessage(checkout: BillingCheckoutResponse) {
  if (checkout.status === "paid" || checkout.status === "completed") {
    return "Payment verified by backend. Subscription or credits are active.";
  }
  if (checkout.provider_disabled) {
    return "Provider-disabled mode created a safe checkout record. No payment has been marked successful.";
  }
  if (checkout.status === "failed" || checkout.status === "cancelled") {
    return "Checkout ended without verified payment.";
  }
  return "Waiting for Pine Labs verification, webhook, or backend status sync.";
}

export default function TenantBillingPage() {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const checkoutId = searchParams.get("checkout_session") ?? searchParams.get("session_id");
  const [lastCheckout, setLastCheckout] = useState<BillingCheckoutResponse | null>(null);
  const [selectedPlan, setSelectedPlan] = useState("solo_pro");
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [selectedAddOn, setSelectedAddOn] = useState("addon_ai_250");
  const [addOnQuantity, setAddOnQuantity] = useState("1");
  const [downloading, setDownloading] = useState<string | null>(null);

  const currentQuery = useQuery({
    queryKey: ["billing", "current"],
    queryFn: fetchCurrentBilling,
  });
  const plansQuery = useQuery({
    queryKey: ["billing", "plans"],
    queryFn: fetchBillingPlans,
  });
  const addOnsQuery = useQuery({
    queryKey: ["billing", "add-ons"],
    queryFn: fetchBillingAddOns,
  });
  const invoicesQuery = useQuery({
    queryKey: ["billing", "invoices"],
    queryFn: fetchBillingInvoices,
  });
  const ledgerQuery = useQuery({
    queryKey: ["billing", "credit-ledger"],
    queryFn: fetchBillingCreditLedger,
  });
  const checkoutQuery = useQuery({
    queryKey: ["billing", "checkout", checkoutId],
    queryFn: () => fetchBillingCheckout(checkoutId as string),
    enabled: Boolean(checkoutId),
  });

  useEffect(() => {
    if (checkoutQuery.data) setLastCheckout(checkoutQuery.data);
  }, [checkoutQuery.data]);

  const visiblePlans = useMemo(
    () => (plansQuery.data?.plans ?? []).filter((plan) => !plan.plan_code.includes("enterprise")),
    [plansQuery.data],
  );
  const addOns = addOnsQuery.data?.add_ons ?? [];
  const current = currentQuery.data;
  const currentPlan = current?.subscription?.plan_code ?? "none";

  const planCheckoutMutation = useMutation({
    mutationFn: () =>
      createBillingCheckout({
        planCode: selectedPlan,
        interval,
        successUrl:
          typeof window === "undefined"
            ? null
            : `${window.location.origin}/app/admin/billing`,
        cancelUrl:
          typeof window === "undefined"
            ? null
            : `${window.location.origin}/app/admin/billing`,
      }),
    onSuccess: (checkout) => {
      setLastCheckout(checkout);
      toast.success("Checkout created.");
      if (checkout.provider_checkout_url) {
        window.location.assign(checkout.provider_checkout_url);
      }
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not start checkout.")),
  });

  const addOnCheckoutMutation = useMutation({
    mutationFn: () =>
      createBillingAddOnCheckout({
        addOnCode: selectedAddOn,
        quantity: Math.max(1, Number.parseInt(addOnQuantity, 10) || 1),
        successUrl:
          typeof window === "undefined"
            ? null
            : `${window.location.origin}/app/admin/billing`,
        cancelUrl:
          typeof window === "undefined"
            ? null
            : `${window.location.origin}/app/admin/billing`,
      }),
    onSuccess: (checkout) => {
      setLastCheckout(checkout);
      toast.success("Add-on checkout created.");
      if (checkout.provider_checkout_url) {
        window.location.assign(checkout.provider_checkout_url);
      }
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not start add-on checkout.")),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => syncBillingCheckout(id),
    onSuccess: (checkout) => {
      setLastCheckout(checkout);
      queryClient.invalidateQueries({ queryKey: ["billing"] });
      toast.success("Checkout status synced.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not sync checkout.")),
  });

  const cancelMutation = useMutation({
    mutationFn: cancelBillingSubscription,
    onSuccess: (data) => {
      queryClient.setQueryData(["billing", "current"], data);
      toast.success("Subscription cancellation scheduled.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not cancel subscription.")),
  });

  const reactivateMutation = useMutation({
    mutationFn: reactivateBillingSubscription,
    onSuccess: (data) => {
      queryClient.setQueryData(["billing", "current"], data);
      toast.success("Subscription reactivated.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not reactivate subscription.")),
  });

  async function runDownload(path: string, fallback: string) {
    setDownloading(path);
    try {
      await downloadApiFile(path, fallback);
      toast.success("Download started.");
    } catch (err) {
      toast.error(apiErrorMessage(err, "Download failed."));
    } finally {
      setDownloading(null);
    }
  }

  const isPending = currentQuery.isPending || plansQuery.isPending;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Workspace billing"
        title="Plan, usage, invoices, and credits"
        description="Payment status changes only after backend verification or a verified Pine Labs webhook."
        actions={
          <div className="flex gap-2">
            <Button href="/app/admin/billing/usage" variant="outline">
              Usage report
            </Button>
            <Button href="/pricing" variant="outline">
              Public pricing
            </Button>
          </div>
        }
      />

      {!canAdmin ? (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Billing access required</CardTitle>
            <CardDescription>
              Ask a workspace owner or admin to manage subscription billing.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {isPending ? (
        <Card>
          <CardContent className="flex flex-col gap-3" aria-busy="true" aria-label="Loading billing state">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </CardContent>
        </Card>
      ) : null}

      {current ? (
        <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle as="h2">Current plan</CardTitle>
                <CardDescription>
                  Tenant-scoped billing account and entitlement state.
                </CardDescription>
              </div>
              <CreditCard className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={statusTone(current.subscription?.status ?? "none")}>
                  {current.subscription?.status ?? "No subscription"}
                </Badge>
                <span className="text-sm font-medium text-[var(--color-ink)]">
                  {current.subscription?.plan_name ?? "No active plan"}
                </span>
                <span className="text-sm text-[var(--color-mute)]">
                  {current.subscription?.billing_interval ?? ""}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
                  <div className="text-xs text-[var(--color-mute)]">Billing email</div>
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    {current.billing_account?.billing_email ?? "Not configured"}
                  </div>
                </div>
                <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
                  <div className="text-xs text-[var(--color-mute)]">Provider state</div>
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    {String(current.payment_provider.mode ?? "disabled")}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {current.subscription?.cancel_at_period_end ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={reactivateMutation.isPending}
                    onClick={() => reactivateMutation.mutate()}
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden />
                    Reactivate
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={cancelMutation.isPending || !current.subscription}
                    onClick={() => cancelMutation.mutate()}
                  >
                    <XCircle className="h-4 w-4" aria-hidden />
                    Cancel at period end
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle as="h2">Usage summary</CardTitle>
              <CardDescription>
                Top-up credits are shown separately from included monthly credits.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2">
                {usageMetrics(current.usage).map((metric) => (
                  <Metric key={metric.label} {...metric} />
                ))}
              </div>
              <div className="mt-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3 text-sm text-[var(--color-ink-2)]">
                Top-up credits available:{" "}
                <span className="font-semibold">{current.usage.topup_credits_available}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {lastCheckout ? (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle as="h2">Checkout status</CardTitle>
              <CardDescription>{checkoutMessage(lastCheckout)}</CardDescription>
            </div>
            {["paid", "completed"].includes(lastCheckout.status) ? (
              <CheckCircle2 className="h-5 w-5 text-green-700" aria-hidden />
            ) : (
              <RefreshCw className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
            )}
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-[var(--color-ink-2)]">
              <span className="font-medium">{lastCheckout.id}</span> -{" "}
              {formatMoneyMinor(lastCheckout.total_amount_minor, lastCheckout.currency)} -{" "}
              {lastCheckout.status}
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate(lastCheckout.id)}
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              Sync backend status
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader>
            <CardTitle as="h2">Change plan</CardTitle>
            <CardDescription>
              Checkout creates a backend order first; redirects are provisional.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              {visiblePlans.map((plan) => {
                const price = planPrice(plan, interval);
                const active = currentPlan === plan.plan_code;
                return (
                  <button
                    key={plan.plan_code}
                    type="button"
                    onClick={() => setSelectedPlan(plan.plan_code)}
                    className={
                      selectedPlan === plan.plan_code
                        ? "rounded-lg border border-[var(--color-ink)] bg-[var(--color-ink)] p-4 text-left text-white"
                        : "rounded-lg border border-[var(--color-line)] bg-white p-4 text-left hover:bg-[var(--color-bg-2)]"
                    }
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold">{plan.display_name}</span>
                      {active ? <Badge tone="success">Current</Badge> : null}
                    </div>
                    <div className="mt-2 text-sm opacity-80">
                      {formatMoneyMinor(price?.amount_minor, price?.currency ?? "INR")} / {interval}
                    </div>
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="billing-interval">Interval</Label>
                <select
                  id="billing-interval"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={interval}
                  onChange={(e) => setInterval(e.target.value as "month" | "year")}
                >
                  <option value="month">Monthly</option>
                  <option value="year">Annual</option>
                </select>
              </div>
              <Button
                type="button"
                disabled={!canAdmin || planCheckoutMutation.isPending}
                onClick={() => planCheckoutMutation.mutate()}
              >
                <ShoppingCart className="h-4 w-4" aria-hidden />
                Start checkout
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle as="h2">Add-ons and credits</CardTitle>
            <CardDescription>
              AI credit packs are one-time top-ups; case, user, storage, and API packs recur.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                addOnCheckoutMutation.mutate();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="billing-addon">Add-on</Label>
                <select
                  id="billing-addon"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={selectedAddOn}
                  onChange={(e) => setSelectedAddOn(e.target.value)}
                >
                  {addOns.map((addOn) => {
                    const price = addOn.prices[0];
                    return (
                      <option key={addOn.plan_code} value={addOn.plan_code}>
                        {addOn.display_name} -{" "}
                        {formatMoneyMinor(price?.amount_minor, price?.currency ?? "INR")}
                      </option>
                    );
                  })}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="billing-addon-quantity">Quantity</Label>
                <Input
                  id="billing-addon-quantity"
                  type="number"
                  min={1}
                  max={1000}
                  value={addOnQuantity}
                  onChange={(e) => setAddOnQuantity(e.target.value)}
                />
              </div>
              <Button type="submit" disabled={!canAdmin || addOnCheckoutMutation.isPending}>
                <ShoppingCart className="h-4 w-4" aria-hidden />
                Buy credits/capacity
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">Invoices and downloads</CardTitle>
            <CardDescription>
              Downloads are tenant-scoped and audited by the API.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={downloading === "/api/billing/statement"}
              onClick={() => runDownload("/api/billing/statement", "caseops-billing-statement.csv")}
            >
              <Download className="h-4 w-4" aria-hidden />
              Statement CSV
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={downloading === "/api/billing/statement?format=pdf"}
              onClick={() =>
                runDownload("/api/billing/statement?format=pdf", "caseops-billing-statement.pdf")
              }
            >
              <Download className="h-4 w-4" aria-hidden />
              Statement PDF
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => runDownload("/api/billing/payments/export", "caseops-payments.csv")}
            >
              <Download className="h-4 w-4" aria-hidden />
              Payment export
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => runDownload("/api/billing/credit-ledger/export", "caseops-credit-ledger.csv")}
            >
              <Download className="h-4 w-4" aria-hidden />
              Credit ledger export
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                <tr>
                  <th className="py-2 pr-4">Invoice</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Total</th>
                  <th className="py-2 pr-4">Issued</th>
                  <th className="py-2 pr-4">Download</th>
                </tr>
              </thead>
              <tbody>
                {(invoicesQuery.data?.invoices ?? []).map((invoice) => (
                  <tr key={invoice.id} className="border-b border-[var(--color-line-2)]">
                    <td className="py-3 pr-4 font-medium">{invoice.invoice_number}</td>
                    <td className="py-3 pr-4">{invoice.status}</td>
                    <td className="py-3 pr-4">
                      {formatMoneyMinor(invoice.total_amount_minor, invoice.currency)}
                    </td>
                    <td className="py-3 pr-4">{invoice.issued_on ?? "-"}</td>
                    <td className="py-3 pr-4">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          runDownload(
                            `/api/billing/invoices/${encodeURIComponent(invoice.id)}/download`,
                            `caseops-invoice-${invoice.id}.pdf`,
                          )
                        }
                      >
                        <Download className="h-4 w-4" aria-hidden />
                        Invoice
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          runDownload(
                            `/api/billing/invoices/${encodeURIComponent(invoice.id)}/download?format=json`,
                            `caseops-invoice-${invoice.id}.json`,
                          )
                        }
                      >
                        <Download className="h-4 w-4" aria-hidden />
                        JSON
                      </Button>
                    </td>
                  </tr>
                ))}
                {(invoicesQuery.data?.invoices ?? []).length === 0 ? (
                  <tr>
                    <td className="py-4 text-[var(--color-mute)]" colSpan={5}>
                      No SaaS invoices yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Recent credit ledger</CardTitle>
          <CardDescription>Tenant-visible credit grants, debits, refunds, and expiry.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                <tr>
                  <th className="py-2 pr-4">Date</th>
                  <th className="py-2 pr-4">Bucket</th>
                  <th className="py-2 pr-4">Event</th>
                  <th className="py-2 pr-4">Delta</th>
                  <th className="py-2 pr-4">Balance</th>
                </tr>
              </thead>
              <tbody>
                {(ledgerQuery.data?.rows ?? []).slice(0, 8).map((row) => (
                  <tr key={row.id} className="border-b border-[var(--color-line-2)]">
                    <td className="py-3 pr-4">{new Date(row.created_at).toLocaleDateString()}</td>
                    <td className="py-3 pr-4">{row.credit_bucket}</td>
                    <td className="py-3 pr-4">{row.event_type}</td>
                    <td className="py-3 pr-4">{row.delta}</td>
                    <td className="py-3 pr-4">{row.balance_after}</td>
                  </tr>
                ))}
                {(ledgerQuery.data?.rows ?? []).length === 0 ? (
                  <tr>
                    <td className="py-4 text-[var(--color-mute)]" colSpan={5}>
                      No credit activity yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
