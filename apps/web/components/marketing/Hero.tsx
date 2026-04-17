import { ArrowRight, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";

const proofPoints = [
  "Citation-grounded AI",
  "Multi-tenant by design",
  "Built for Indian courts",
];

export function Hero() {
  return (
    <section className="relative overflow-hidden pb-20 pt-16 md:pb-32 md:pt-24">
      <div className="absolute inset-0 -z-10 grid-fade" aria-hidden />
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 -z-10 h-[520px] bg-gradient-to-b from-[var(--color-brand-50)] via-white to-transparent"
      />

      <Container className="flex flex-col items-center text-center">
        <Badge tone="brand" className="mb-6">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-brand-500)]" />
          India-first legal OS, now in early access
        </Badge>

        <h1 className="max-w-4xl text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-[var(--color-ink)] md:text-6xl">
          The operating system for <span className="text-[var(--color-brand-600)]">legal work</span>.
        </h1>

        <p className="mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-[var(--color-mute)] md:text-xl">
          Run every matter, drafting pass, hearing, contract, and invoice from a single
          matter-graph workspace. Grounded in statutes, judgments, and your own precedents —
          never guesses.
        </p>

        <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row">
          <Button href="#cta" size="lg">
            Request a demo
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button href="#product" variant="outline" size="lg">
            See the product
          </Button>
        </div>

        <ul className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-[var(--color-mute)]">
          {proofPoints.map((point) => (
            <li key={point} className="inline-flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-[var(--color-brand-500)]" aria-hidden />
              {point}
            </li>
          ))}
        </ul>
      </Container>

      <Container className="mt-16 md:mt-20">
        <HeroPreview />
      </Container>
    </section>
  );
}

function HeroPreview() {
  return (
    <div className="relative mx-auto max-w-5xl">
      <div
        aria-hidden
        className="absolute -inset-x-8 -top-6 -bottom-6 rounded-[32px] bg-gradient-to-b from-[var(--color-brand-100)]/60 via-white to-transparent blur-2xl"
      />
      <div className="relative overflow-hidden rounded-[24px] border border-[var(--color-line)] bg-white shadow-[var(--shadow-lifted)]">
        <div className="flex items-center gap-3 border-b border-[var(--color-line)] px-5 py-3">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
          </div>
          <div className="ml-3 flex-1 rounded-md bg-[var(--color-bg-2)] px-3 py-1 text-left text-xs text-[var(--color-mute-2)]">
            caseops.ai / workspace / matters / arbitral-award-challenge
          </div>
        </div>

        <div className="grid grid-cols-12 gap-0">
          <aside className="hidden border-r border-[var(--color-line)] bg-[var(--color-bg)] p-4 md:col-span-3 md:block">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
              Matters
            </div>
            <ul className="mt-3 space-y-1.5 text-sm">
              {[
                "Arbitral award challenge",
                "Trademark infringement",
                "Shareholder dispute",
                "Commercial suit — Delhi HC",
                "NCLT insolvency petition",
              ].map((m, i) => (
                <li
                  key={m}
                  className={`rounded-md px-2.5 py-2 ${
                    i === 0
                      ? "bg-[var(--color-ink)] text-white"
                      : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
                  }`}
                >
                  {m}
                </li>
              ))}
            </ul>
          </aside>

          <div className="col-span-12 p-5 md:col-span-9 md:p-6">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
              <span className="rounded-full bg-[var(--color-brand-50)] px-2 py-0.5 font-medium text-[var(--color-brand-700)]">
                Arbitration
              </span>
              <span>Delhi High Court • OMP (COMM) 314/2025</span>
              <span className="ml-auto text-[var(--color-ink-2)]">Next hearing — 22 Apr</span>
            </div>

            <h3 className="mt-3 text-lg font-semibold tracking-tight text-[var(--color-ink)]">
              Recommendation — grounds for setting aside under §34
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-[var(--color-mute)]">
              Three arguable grounds surfaced from the award and prior authorities. Review
              required before filing.
            </p>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                {
                  title: "Patent illegality",
                  note: "Ssangyong Engineering v. NHAI (2019) supports",
                  confidence: "High",
                },
                {
                  title: "Violation of natural justice",
                  note: "Procedural record is thin — needs evidence",
                  confidence: "Medium",
                },
                {
                  title: "Public policy conflict",
                  note: "Weak on current precedent; not recommended",
                  confidence: "Low",
                },
              ].map((opt) => (
                <div
                  key={opt.title}
                  className="rounded-lg border border-[var(--color-line)] bg-white p-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {opt.title}
                    </div>
                    <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--color-mute-2)]">
                      {opt.confidence}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-mute)]">
                    {opt.note}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-lg border border-dashed border-[var(--color-line)] bg-[var(--color-bg)] p-3 text-xs text-[var(--color-mute)]">
              <span className="font-semibold text-[var(--color-ink-2)]">Assumptions</span> —
              seat at Delhi; award pronounced 12 Feb 2026; limitation runs to 12 May 2026.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
