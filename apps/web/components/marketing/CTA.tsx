import { DemoRequestForm } from "@/components/marketing/DemoRequestForm";
import { Container } from "@/components/ui/Container";

export function CTA() {
  return <section id="cta" className="border-t border-[var(--color-line)] py-16">
    <Container><div className="grid gap-10 md:grid-cols-2">
      <div>
        <h2 className="text-3xl font-semibold text-[var(--color-ink)]">Discuss CaseOps for your practice.</h2>
        <p className="mt-4 max-w-lg text-base leading-relaxed text-[var(--color-mute)]">
          Request a walkthrough using non-confidential examples. We can discuss supported workflows,
          court and provider coverage, plan limits and a possible pilot. A request does not activate a plan
          or guarantee a response time, pilot duration or price.
        </p>
      </div>
      <DemoRequestForm source="homepage" />
    </div></Container>
  </section>;
}
