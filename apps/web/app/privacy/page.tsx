import type { Metadata } from "next";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { privacyPolicy } from "@/lib/privacy-policy";

export const metadata: Metadata = {
  title: privacyPolicy.title,
  description: privacyPolicy.intro,
  alternates: { canonical: privacyPolicy.canonicalUrl },
  robots: { index: true, follow: true, googleBot: { index: true, follow: true } },
  openGraph: {
    type: "website",
    url: privacyPolicy.canonicalUrl,
    title: privacyPolicy.title,
    description: privacyPolicy.intro,
  },
};

const linkClass = "inline-flex min-h-11 items-center py-2 font-medium underline underline-offset-4 hover:text-[var(--color-ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-brand-700)]";

export default function PrivacyPage() {
  return (
    <>
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] py-10 md:py-14">
          <Container>
            <div className="max-w-[75ch] space-y-6">
              <h1 id="privacy-policy-title" className="font-display text-[clamp(2rem,4vw,3rem)] font-normal leading-tight text-[var(--color-ink)]">
                {privacyPolicy.title}
              </h1>
              <p className="text-lg leading-relaxed text-[var(--color-ink-2)]">{privacyPolicy.intro}</p>
              <dl className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-[var(--color-ink-2)]">
                <div><dt className="text-[var(--color-mute)]">Effective date</dt><dd><time dateTime={privacyPolicy.version}>{privacyPolicy.effectiveDate}</time></dd></div>
                <div><dt className="text-[var(--color-mute)]">Version</dt><dd className="tabular">{privacyPolicy.version}</dd></div>
                <div><dt className="text-[var(--color-mute)]">Operator</dt><dd>{privacyPolicy.operator}</dd></div>
              </dl>
              <div aria-label="Privacy contacts and requests" className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-[var(--color-ink-2)]">
                <a className={`${linkClass} break-all`} href={`mailto:${privacyPolicy.contactEmail}`}>{privacyPolicy.contactEmail}</a>
                <a className={linkClass} href="#account-deletion">Account deletion</a>
              </div>
            </div>
          </Container>
        </header>

        <Container className="py-10 md:py-14">
          <div className="grid min-w-0 gap-10 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-14">
            <nav aria-label="Policy contents" className="min-w-0 border-b border-[var(--color-line)] pb-6 lg:border-b-0 lg:pb-0">
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">On this page</h2>
              <ol className="mt-3 grid gap-x-6 gap-y-1 text-sm leading-relaxed text-[var(--color-ink-2)] sm:grid-cols-2 lg:grid-cols-1">
                {privacyPolicy.sections.map((section) => (
                  <li key={section.id}><a className={`${linkClass} w-full`} href={`#${section.id}`}>{section.title}</a></li>
                ))}
              </ol>
            </nav>

            <article aria-label="Full privacy policy" className="min-w-0 max-w-[75ch] text-base leading-7 text-[var(--color-ink-2)] [overflow-wrap:anywhere]">
              <section aria-labelledby="privacy-summary-title" className="space-y-4 border-b border-[var(--color-line)] pb-8">
                <h2 id="privacy-summary-title" className="text-xl font-semibold text-[var(--color-ink)]">At a glance</h2>
                <ul className="list-disc space-y-3 pl-5 marker:text-[var(--color-brand-700)]">
                  {privacyPolicy.summary.map((point) => <li key={point}>{point}</li>)}
                </ul>
              </section>
              {privacyPolicy.sections.map((section) => (
                <section key={section.id} id={section.id} aria-labelledby={`${section.id}-title`} className="scroll-mt-24 space-y-4 border-b border-[var(--color-line)] py-8 last:border-b-0 last:pb-0">
                  <h2 id={`${section.id}-title`} className="text-xl font-semibold leading-snug text-[var(--color-ink)]">{section.title}</h2>
                  {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
                  {section.bullets.length > 0 ? <ul className="list-disc space-y-3 pl-5 marker:text-[var(--color-brand-700)]">{section.bullets.map((point) => <li key={point}>{point}</li>)}</ul> : null}
                  {section.id === "contact" ? <a className={linkClass} href="/demo/privacy">Demo request privacy notice</a> : null}
                </section>
              ))}
            </article>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  );
}
