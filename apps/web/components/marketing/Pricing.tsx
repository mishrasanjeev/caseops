import { Check } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/cn";
import { siteConfig } from "@/lib/site";

const tiers = [
  {
    name: "Solo",
    priceLabel: "Early access",
    priceNote: "per lawyer / month",
    description: "For solo practitioners who want one tool that actually runs the practice.",
    features: [
      "Matter, hearing, and drafting workspace",
      "Case diary and cause-list sync",
      "Pine Labs payment collection",
      "E-mail + knowledge base support",
    ],
    cta: { label: "Join waitlist", href: "#cta" },
    highlighted: false,
  },
  {
    name: "Firm",
    priceLabel: "Pilot pricing",
    priceNote: "per seat / month",
    description: "For mid-sized and litigation-heavy Indian law firms.",
    features: [
      "Everything in Solo, for the whole firm",
      "Recommendations, authorities, and playbooks",
      "Matter-level ethical walls and audit",
      "Priority support with a named owner",
    ],
    cta: { label: "Book a demo", href: "#cta" },
    highlighted: true,
  },
  {
    name: "Enterprise",
    priceLabel: "Custom",
    priceNote: "annual contract",
    description: "For corporate legal teams and firms that need dedicated posture.",
    features: [
      "Private VPC or on-prem inference",
      "OIDC / SAML SSO and SCIM",
      "Dedicated adapters and connectors",
      "Quarterly evaluation and tuning",
    ],
    cta: { label: "Talk to sales", href: "#cta" },
    highlighted: false,
  },
] as const;

export function Pricing() {
  return (
    <section id="pricing" className="bg-[var(--color-bg-2)] py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Pricing"
          title="Transparent tiers, honest about the stage."
          description="CaseOps is in early access. Pricing firms up after we learn how teams get the most value — lock in pilot terms now."
        />

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {tiers.map((tier) => (
            <article
              key={tier.name}
              className={cn(
                "relative flex flex-col rounded-2xl border p-7 shadow-[var(--shadow-soft)]",
                tier.highlighted
                  ? "border-[var(--color-ink)] bg-[var(--color-ink)] text-white"
                  : "border-[var(--color-line)] bg-white",
              )}
            >
              {tier.highlighted ? (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[var(--color-brand-700)] px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-white">
                  Most popular
                </span>
              ) : null}

              <div className="text-sm font-semibold tracking-tight">
                {tier.name}
              </div>

              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-3xl font-semibold tracking-tight">{tier.priceLabel}</span>
              </div>
              <div
                className={cn(
                  "text-xs",
                  tier.highlighted ? "text-white/70" : "text-[var(--color-mute-2)]",
                )}
              >
                {tier.priceNote}
              </div>

              <p
                className={cn(
                  "mt-4 text-sm leading-relaxed",
                  tier.highlighted ? "text-white/80" : "text-[var(--color-mute)]",
                )}
              >
                {tier.description}
              </p>

              <ul className="mt-6 flex-1 space-y-3 text-sm">
                {tier.features.map((f) => (
                  <li key={f} className="flex gap-2.5">
                    <Check
                      className={cn(
                        "mt-0.5 h-4 w-4 shrink-0",
                        tier.highlighted ? "text-white" : "text-[var(--color-brand-600)]",
                      )}
                      aria-hidden
                    />
                    <span className={tier.highlighted ? "text-white/90" : "text-[var(--color-ink-2)]"}>
                      {f}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="mt-8">
                <Button
                  href={tier.cta.href}
                  variant={tier.highlighted ? "secondary" : "outline"}
                  className="w-full"
                >
                  {tier.cta.label}
                </Button>
              </div>
            </article>
          ))}
        </div>
      </Container>
    </section>
  );
}
