import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";

const flows = [
  {
    persona: "Litigation partner",
    headline: "From cause list to cited order in an afternoon.",
    bullets: [
      "Auto-ingest the morning cause list and flag matters at risk.",
      "One-click hearing pack with chronology, last order, and oral points.",
      "Post-hearing notes flow into tasks, drafts, and client updates.",
    ],
  },
  {
    persona: "General Counsel",
    headline: "Control the portfolio, not the paperwork.",
    bullets: [
      "Structured intake for every business request with SLAs.",
      "Contract repository with clause extraction and obligation tracking.",
      "Outside-counsel spend, aging, and realization in one dashboard.",
    ],
  },
  {
    persona: "Solo advocate",
    headline: "Operate like a 20-lawyer practice.",
    bullets: [
      "One app for matters, drafts, hearings, billing, and payment collection.",
      "Pine Labs payment links issued with every invoice.",
      "Case diary that survives the day you forgot your diary.",
    ],
  },
] as const;

export function Workflows() {
  return (
    <section id="workflows" className="bg-[var(--color-bg-2)] py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Workflows"
          title="Designed for how legal teams actually work."
          description="Pick the shape that fits your practice. The same matter graph powers all of them."
        />

        <div className="mt-16 grid gap-6 lg:grid-cols-3">
          {flows.map((flow, idx) => (
            <article
              key={flow.persona}
              className="relative flex flex-col rounded-2xl border border-[var(--color-line)] bg-white p-7 shadow-[var(--shadow-soft)]"
            >
              <div className="flex items-center gap-3">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--color-ink)] text-xs font-semibold text-white">
                  {idx + 1}
                </span>
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-mute-2)]">
                  {flow.persona}
                </span>
              </div>
              <h3 className="mt-4 text-xl font-semibold tracking-tight text-[var(--color-ink)]">
                {flow.headline}
              </h3>
              <ul className="mt-5 space-y-3 text-sm text-[var(--color-ink-2)]">
                {flow.bullets.map((b) => (
                  <li key={b} className="flex gap-3">
                    <span
                      aria-hidden
                      className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
                    />
                    <span className="leading-relaxed">{b}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </Container>
    </section>
  );
}
