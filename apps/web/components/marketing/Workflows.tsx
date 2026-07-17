import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";

const flows = [
  {
    persona: "Litigation partner",
    headline: "From tracked update to reviewed compliance in an afternoon.",
    bullets: [
      "Tracked/bookmarked cases refresh in the 4-6 PM IST window with blocked/skipped reasons visible to admins.",
      "Court orders create source-backed, review-required compliance items before tasks or deadlines become active.",
      "Received notices create a reply queue and linked deadlines; replies and supporting files stay attached to the matter.",
    ],
  },
  {
    persona: "General Counsel",
    headline: "Control the portfolio, not the paperwork.",
    bullets: [
      "Structured intake can hold pre-engagement work behind conflict clearance, while direct New Matter creation starts Active by default.",
      "Contract repository with clause extraction and obligation tracking.",
      "Matter intelligence review, outside-counsel spend, aging, realization, and audited provider operations in one dashboard.",
    ],
  },
  {
    persona: "Solo advocate",
    headline: "Operate like a 20-lawyer practice.",
    bullets: [
      "One app for matters, notices, drafts, hearings, litigation intelligence, cause lists, billing, and payment adjustments.",
      "India-ready matter invoices with firm/client GST fields, SAC/HSN, GST split, TDS recording, amount paid, and outstanding.",
      "Dispose completed matters without losing audit history or next-hearing provenance.",
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
