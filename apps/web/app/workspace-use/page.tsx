import type { Metadata } from "next";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";

import rules from "./approved-rules.json";

const canonical = "https://caseops.ai/workspace-use";

export const metadata: Metadata = {
  title: rules.title,
  description: "Rules for sharing and reporting material in a CaseOps workspace.",
  alternates: { canonical },
};

const linkClass =
  "inline-flex min-h-11 items-center break-all font-medium underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-brand-700)]";

export default function WorkspaceUsePage() {
  return (
    <>
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] py-10 md:py-14">
          <Container>
            <div className="max-w-[70ch] space-y-5">
              <p className="text-sm font-semibold text-[var(--color-mute)]">
                CaseOps policy · <time dateTime={rules.version}>{rules.version}</time>
              </p>
              <h1 className="font-display text-[clamp(2rem,4vw,3rem)] font-normal leading-tight text-[var(--color-ink)]">
                {rules.title}
              </h1>
              <p className="text-lg leading-relaxed text-[var(--color-ink-2)]">{rules.intro}</p>
            </div>
          </Container>
        </header>

        <Container className="py-8 md:py-12">
          <article aria-label={rules.title} className="max-w-[70ch] text-base leading-7 text-[var(--color-ink-2)]">
            {rules.sections.map(({ id, title, text }) => (
              <section key={id} aria-labelledby={id} className="space-y-3 border-b border-[var(--color-line)] py-6 first:pt-0">
                <h2 id={id} className="text-xl font-semibold text-[var(--color-ink)]">{title}</h2>
                <p>{text}</p>
              </section>
            ))}
            <nav aria-label="Related policy and support" className="mt-4 flex flex-wrap gap-x-6">
              <a className={linkClass} href={`mailto:${rules.contactEmail}`}>{rules.contactEmail}</a>
              <a className={linkClass} href="/privacy">Privacy policy</a>
            </nav>
          </article>
        </Container>
      </main>
      <Footer />
    </>
  );
}
