"use client";

import { Check, Loader2, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import {
  createBillingDemoRequest,
  fetchBillingPlans,
} from "@/lib/api/endpoints";
import type { BillingPlanRecord, BillingPlansResponse } from "@/lib/api/schemas";
import { formatBytes, formatLimit, formatMoneyMinor } from "@/lib/billing-format";
import { apiErrorMessage } from "@/lib/api/config";

type Segment = "solo" | "firm" | "gc";

const SEGMENTS: Array<{ key: Segment; label: string; description: string }> = [
  {
    key: "solo",
    label: "Solo",
    description: "GST-inclusive monthly and annual plans for solo advocates.",
  },
  {
    key: "firm",
    label: "Law firms",
    description: "Team plans with users, tracked cases, storage, and audit exports.",
  },
  {
    key: "gc",
    label: "General Counsel",
    description: "Annual GC plans with procurement-friendly billing and reporting.",
  },
];

function priceFor(plan: BillingPlanRecord, interval: "month" | "year") {
  return plan.prices.find((price) => price.interval === interval) ?? null;
}

function segmentFor(plan: BillingPlanRecord): Segment {
  if (plan.plan_code.startsWith("gc_")) return "gc";
  if (plan.plan_code.startsWith("firm_")) return "firm";
  return "solo";
}

function heroPlan(plan: BillingPlanRecord): boolean {
  return ["solo_pro", "firm_growth", "gc_professional"].includes(plan.plan_code);
}

function compactEntitlements(plan: BillingPlanRecord): string[] {
  const e = plan.entitlements;
  return [
    `${formatLimit(e.users_internal_limit)} internal users`,
    `${formatLimit(e.matters_active_limit)} active matters`,
    `${formatLimit(e.tracked_cases_limit)} tracked cases`,
    `${formatLimit(e.ai_credits_monthly)} AI credits/mo`,
    `${formatBytes(typeof e.storage_bytes_limit === "number" ? e.storage_bytes_limit : null)} storage`,
    `Refresh: ${formatLimit(e.case_refresh_cadence)}`,
  ];
}

export function PricingPageClient() {
  const [catalog, setCatalog] = useState<BillingPlansResponse | null>(null);
  const [activeSegment, setActiveSegment] = useState<Segment>("solo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<string>("solo_pro");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [notes, setNotes] = useState("");
  const [requestState, setRequestState] = useState<"idle" | "saving" | "sent">("idle");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchBillingPlans()
      .then((data) => {
        if (!cancelled) {
          setCatalog(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(apiErrorMessage(err, "Could not load plan catalog."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visiblePlans = useMemo(() => {
    const plans = catalog?.plans ?? [];
    return plans.filter((plan) => segmentFor(plan) === activeSegment);
  }, [activeSegment, catalog]);

  async function submitDemoRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !email.includes("@")) {
      setError("Name and email are required.");
      return;
    }
    setRequestState("saving");
    try {
      await createBillingDemoRequest({
        contactName: name.trim(),
        contactEmail: email.trim().toLowerCase(),
        companyName: companyName.trim() || null,
        segment: activeSegment,
        selectedPlan,
        notes: notes.trim() || null,
        source: "pricing_page",
      });
      setRequestState("sent");
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "Could not send pricing request."));
      setRequestState("idle");
    }
  }

  return (
    <main className="min-h-screen bg-[var(--color-bg)]">
      <header className="border-b border-[var(--color-line)] bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <Logo />
          <div className="flex items-center gap-2">
            <Link
              href="/sign-in"
              className="rounded-md px-3 py-2 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Sign in
            </Link>
            <Button href="#pricing-request" size="sm">
              <Mail className="h-4 w-4" aria-hidden />
              Talk to sales
            </Button>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-8 px-5 py-10 lg:grid-cols-[0.8fr_1.2fr] lg:items-end">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-brand-700)]">
            <ShieldCheck className="h-4 w-4" aria-hidden />
            Version {catalog?.version ?? "2026.05.v1"}
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--color-ink)] md:text-5xl">
            Pricing for legal teams that need usage control.
          </h1>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-[var(--color-mute)]">
            Plans include AI credits, tracked-case limits, storage quotas, and
            billing controls. GST display follows the buyer segment.
          </p>
        </div>
        <div className="grid gap-3 rounded-2xl border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)] sm:grid-cols-3">
          {SEGMENTS.map((segment) => (
            <button
              key={segment.key}
              type="button"
              onClick={() => setActiveSegment(segment.key)}
              className={
                activeSegment === segment.key
                  ? "rounded-md bg-[var(--color-ink)] px-4 py-3 text-left text-white"
                  : "rounded-md px-4 py-3 text-left text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              }
            >
              <span className="block text-sm font-semibold">{segment.label}</span>
              <span className="mt-1 block text-xs opacity-80">{segment.description}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 pb-12">
        {loading ? (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-line)] bg-white p-5 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading plans...
          </div>
        ) : error && !catalog ? (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-800">
            {error}
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-3">
            {visiblePlans.map((plan) => {
              const monthly = priceFor(plan, "month");
              const annual = priceFor(plan, "year");
              const primary = activeSegment === "gc" ? annual : monthly;
              const highlighted = heroPlan(plan);
              return (
                <article
                  key={plan.plan_code}
                  className={
                    highlighted
                      ? "flex flex-col rounded-2xl border border-[var(--color-ink)] bg-[var(--color-ink)] p-6 text-white shadow-[var(--shadow-soft)]"
                      : "flex flex-col rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)]"
                  }
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold">{plan.display_name}</h2>
                      <p className={highlighted ? "mt-1 text-sm text-white/75" : "mt-1 text-sm text-[var(--color-mute)]"}>
                        {plan.description ?? "CaseOps plan"}
                      </p>
                    </div>
                    {highlighted ? (
                      <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs font-semibold">
                        Recommended
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-5">
                    <div className="text-3xl font-semibold tracking-tight">
                      {formatMoneyMinor(primary?.amount_minor, primary?.currency ?? "INR")}
                    </div>
                    <div className={highlighted ? "text-sm text-white/70" : "text-sm text-[var(--color-mute)]"}>
                      {primary?.amount_minor === null || !primary
                        ? "Custom quote"
                        : activeSegment === "gc"
                          ? "per year + GST"
                          : primary.tax_behavior === "inclusive"
                            ? "per month, GST inclusive"
                            : "per month + GST"}
                    </div>
                    <div className={highlighted ? "mt-2 text-sm text-white/80" : "mt-2 text-sm text-[var(--color-ink-2)]"}>
                      Annual: {formatMoneyMinor(annual?.amount_minor, annual?.currency ?? "INR")}
                    </div>
                  </div>
                  <ul className="mt-5 flex-1 space-y-2 text-sm">
                    {compactEntitlements(plan).map((item) => (
                      <li key={item} className="flex gap-2">
                        <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-6 flex gap-2">
                    <Button
                      type="button"
                      variant={highlighted ? "secondary" : "outline"}
                      className="flex-1"
                      onClick={() => {
                        setSelectedPlan(plan.plan_code);
                        document.getElementById("pricing-request")?.scrollIntoView({
                          behavior: "smooth",
                          block: "start",
                        });
                      }}
                    >
                      Request plan
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section id="pricing-request" className="border-t border-[var(--color-line)] bg-white">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-10 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
              Start with a trial or assisted plan.
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-[var(--color-mute)]">
              Plan activation is assisted while production payment collection
              remains disabled until UAT evidence and founder go/no-go are complete.
              Approved GC and enterprise plans can use manual invoices.
            </p>
          </div>
          <form className="grid gap-4" onSubmit={submitDemoRequest}>
            {requestState === "sent" ? (
              <div role="status" className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800">
                Request received. CaseOps will follow up on the selected plan.
              </div>
            ) : null}
            {error ? (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                {error}
              </div>
            ) : null}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pricing-name">Name</Label>
                <Input id="pricing-name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pricing-email">Email</Label>
                <Input id="pricing-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pricing-company">Company</Label>
                <Input id="pricing-company" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pricing-plan">Plan</Label>
                <select
                  id="pricing-plan"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={selectedPlan}
                  onChange={(e) => setSelectedPlan(e.target.value)}
                >
                  {(catalog?.plans ?? []).map((plan) => (
                    <option key={plan.plan_code} value={plan.plan_code}>
                      {plan.display_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pricing-notes">Notes</Label>
              <textarea
                id="pricing-notes"
                className="min-h-24 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={requestState === "saving"}>
              {requestState === "saving" ? "Sending..." : "Request pricing"}
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}
