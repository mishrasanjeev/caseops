"use client";

import { Check, Loader2, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DemoRequestForm } from "@/components/marketing/DemoRequestForm";

import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import {
  fetchBillingPlans,
} from "@/lib/api/endpoints";
import type { BillingPlanRecord, BillingPlansResponse } from "@/lib/api/schemas";
import { formatBytes, formatLimit, formatMoneyMinor } from "@/lib/billing-format";
import { apiErrorMessage } from "@/lib/api/config";

type Segment = "solo" | "firm" | "gc";

const TRIAL_HREF = "/sign-in?tab=new";

const SEGMENTS: Array<{ key: Segment; label: string; description: string }> = [
  {
    key: "solo",
    label: "Solo",
    description: "Monthly or annual, GST included. Staff seats included.",
  },
  {
    key: "firm",
    label: "Law firms",
    description: "Team plans priced per workspace, shown before GST.",
  },
  {
    key: "gc",
    label: "General Counsel",
    description: "Annual plans for corporate legal teams, shown before GST.",
  },
];

// Modules every plan includes; none is gated by plan tier in the product.
const INCLUDED_IN_EVERY_PLAN = [
  "Matter workspace: matters, hearings, tasks and documents",
  "Court case tracking with scheduled refresh of status and next hearing dates",
  "Legal research across Indian judgments and statutes, with citations",
  "Drafting and review from matter documents, with citations",
  "Hearing packs assembled from the matter file",
  "Matter invoices and payment records",
  "Audit log of sensitive actions, exportable by workspace admins",
];

const PLAN_TERMS: Array<{ term: string; detail: string }> = [
  {
    term: "AI credits",
    detail:
      "One credit covers about 4,000 tokens of model work, so longer documents use more. Hearing packs and matter Q&A use at least 2. Searching authorities and reading legal updates use none. Included credits renew every month, on annual plans too, and do not roll over.",
  },
  {
    term: "Tracked cases",
    detail:
      "Court cases CaseOps refreshes from court sources on a schedule. Each plan also allows a daily number of manual refreshes. Packs of 500 or 1,000 more tracked cases can be added.",
  },
  {
    term: "Users and viewers",
    detail:
      "Users sign in to do the work. Viewers, on firm and corporate plans, have read-only access. Extra users can be added to any plan.",
  },
  {
    term: "Annual billing",
    detail:
      "Annual Solo and Firm plans cost ten months of the monthly price. Corporate plans are billed annually.",
  },
  {
    term: "Free trial",
    detail:
      "14 days with no card: 2 users, 10 matters, 10 tracked cases and 50 AI credits. After day 14 you can still open your work; adding matters, users, tracked cases, documents or AI work needs a plan.",
  },
  {
    term: "GST",
    detail: "Solo prices include 18% GST. Firm and corporate prices are shown before GST.",
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

function numberEntitlement(plan: BillingPlanRecord, key: string): number | null {
  const value = plan.entitlements[key];
  return typeof value === "number" ? value : null;
}

/** Effective monthly price per included user, in minor units. */
export function perUserMonthlyMinor(plan: BillingPlanRecord): number | null {
  const users = numberEntitlement(plan, "users_internal_limit");
  const monthly = priceFor(plan, "month")?.amount_minor ?? null;
  const annual = priceFor(plan, "year")?.amount_minor ?? null;
  const perMonth = monthly ?? (annual === null ? null : annual / 12);
  if (!users || perMonth === null) return null;
  return Math.round(perMonth / users / 100) * 100;
}

/** What an annual plan saves against twelve monthly payments, in minor units. */
export function annualSavingMinor(plan: BillingPlanRecord): number | null {
  const monthly = priceFor(plan, "month")?.amount_minor ?? null;
  const annual = priceFor(plan, "year")?.amount_minor ?? null;
  if (monthly === null || annual === null) return null;
  const saving = monthly * 12 - annual;
  return saving > 0 ? saving : null;
}

function compactEntitlements(plan: BillingPlanRecord): string[] {
  const e = plan.entitlements;
  const viewers = numberEntitlement(plan, "users_viewer_limit");
  return [
    `${formatLimit(e.users_internal_limit)} users${viewers ? ` + ${formatLimit(viewers)} viewers` : ""}`,
    `${formatLimit(e.matters_active_limit)} active matters`,
    `${formatLimit(e.tracked_cases_limit)} tracked court cases`,
    `${formatLimit(e.ai_credits_monthly)} AI credits per month`,
    `${formatBytes(typeof e.storage_bytes_limit === "number" ? e.storage_bytes_limit : null)} storage`,
  ];
}

export function PricingPageClient() {
  const [catalog, setCatalog] = useState<BillingPlansResponse | null>(null);
  const [activeSegment, setActiveSegment] = useState<Segment>("solo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);

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
    // Cheapest first; custom-quote plans last.
    const sortKey = (plan: BillingPlanRecord) =>
      priceFor(plan, "year")?.amount_minor ?? Number.POSITIVE_INFINITY;
    return plans
      .filter((plan) => segmentFor(plan) === activeSegment)
      .sort((a, b) => sortKey(a) - sortKey(b));
  }, [activeSegment, catalog]);

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
            <Button href="#pricing-request" size="sm" variant="outline">
              <Mail className="h-4 w-4" aria-hidden />
              Talk to sales
            </Button>
            <Button href={TRIAL_HREF} size="sm" className="hidden sm:inline-flex">
              Start 14-day trial
            </Button>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-8 px-5 py-10 lg:grid-cols-[0.8fr_1.2fr] lg:items-end">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-brand-700)]">
            <ShieldCheck className="h-4 w-4" aria-hidden />
            Rate card {catalog?.version ?? "2026.11.v1"}
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--color-ink)] md:text-5xl">
            Published prices for Indian legal practice.
          </h1>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-[var(--color-mute)]">
            Every plan includes research, drafting, matter management and court
            tracking, and the limits shown are the limits the product applies.
            Start with a 14-day trial; no card needed.
          </p>
          <div className="mt-5">
            <Button href={TRIAL_HREF}>Start 14-day trial</Button>
          </div>
        </div>
        <div className="grid gap-3 rounded-2xl border border-[var(--color-line)] bg-white p-4 shadow-[var(--shadow-soft)] sm:grid-cols-3">
          {SEGMENTS.map((segment) => (
            <button
              key={segment.key}
              type="button"
              aria-pressed={activeSegment === segment.key}
              onClick={() => { setActiveSegment(segment.key); setSelectedPlan(null); }}
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
              const primary = activeSegment === "gc" ? annual : monthly ?? annual;
              const highlighted = heroPlan(plan);
              const perUser = perUserMonthlyMinor(plan);
              const saving = annualSavingMinor(plan);
              const inclusive = primary?.tax_behavior === "inclusive";
              const subtle = highlighted ? "text-white/75" : "text-[var(--color-mute)]";
              return (
                <article
                  key={plan.plan_code}
                  data-testid={`plan-${plan.plan_code}`}
                  className={
                    highlighted
                      ? "flex flex-col rounded-2xl border border-[var(--color-ink)] bg-[var(--color-ink)] p-6 text-white shadow-[var(--shadow-soft)]"
                      : "flex flex-col rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)]"
                  }
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold">{plan.display_name}</h2>
                      <p className={`mt-1 text-sm ${subtle}`}>
                        {plan.description ?? "CaseOps plan"}
                      </p>
                    </div>
                    {highlighted ? (
                      <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs font-semibold">
                        Recommended
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-5 tabular-nums">
                    <div className="text-3xl font-semibold tracking-tight">
                      {formatMoneyMinor(primary?.amount_minor, primary?.currency ?? "INR")}
                    </div>
                    <div className={`text-sm ${subtle}`}>
                      {primary?.amount_minor === null || !primary
                        ? "Custom quote"
                        : primary.interval === "year"
                          ? "per year + GST"
                          : inclusive
                            ? "per month, GST included"
                            : "per month + GST"}
                    </div>
                    {perUser !== null ? (
                      <div className={`mt-2 text-sm ${highlighted ? "text-white/85" : "text-[var(--color-ink-2)]"}`}>
                        {formatMoneyMinor(perUser)} per user per month
                        {inclusive ? "" : " + GST"}
                      </div>
                    ) : null}
                    {monthly && annual ? (
                      <div className={`mt-1 text-sm ${highlighted ? "text-white/85" : "text-[var(--color-ink-2)]"}`}>
                        Annual {formatMoneyMinor(annual.amount_minor, annual.currency)}
                        {saving !== null ? `, saves ${formatMoneyMinor(saving)}` : ""}
                      </div>
                    ) : null}
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

      <section className="border-t border-[var(--color-line)] bg-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-10 lg:grid-cols-2">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-[var(--color-ink)]">
              Included in every plan
            </h2>
            <ul className="mt-4 space-y-2 text-sm text-[var(--color-ink-2)]">
              {INCLUDED_IN_EVERY_PLAN.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-brand-600)]" aria-hidden />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-[var(--color-ink)]">
              How plan limits work
            </h2>
            <dl className="mt-4 divide-y divide-[var(--color-line)] text-sm">
              {PLAN_TERMS.map(({ term, detail }) => (
                <div key={term} className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr] sm:gap-4">
                  <dt className="font-semibold text-[var(--color-ink)]">{term}</dt>
                  <dd className="max-w-[70ch] leading-relaxed text-[var(--color-mute)]">{detail}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section id="pricing-request" className="border-t border-[var(--color-line)] bg-white">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-10 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
              Start a trial or request a plan.
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-[var(--color-mute)]">
              Plans are activated by the CaseOps team: tell us the plan you
              want and we confirm your limits and raise the invoice. Online
              payment is not open yet. Corporate and enterprise plans can be
              billed by manual invoice.
            </p>
            <div className="mt-5">
              <Button href={TRIAL_HREF} variant="outline">
                Start 14-day trial
              </Button>
            </div>
          </div>
          <DemoRequestForm source="pricing_page" segment={activeSegment} intent="pricing" selectedPlan={selectedPlan} />
        </div>
      </section>
    </main>
  );
}
