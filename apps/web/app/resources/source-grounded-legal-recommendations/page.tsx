import type { Metadata } from "next";
import { headers } from "next/headers";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

const path = "/resources/source-grounded-legal-recommendations";
const title = "Source-grounded recommendations for law firms";
const description =
  "How law firms can review AI-assisted recommendations in CaseOps: matter context, supporting citations, missing facts, lawyer decisions and controlled access.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: path },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}${path}`,
    title,
    description,
  },
};

const articleJsonLd = {
  "@context": "https://schema.org",
  "@type": "Article",
  headline: title,
  description,
  mainEntityOfPage: `${siteConfig.url}${path}`,
  inLanguage: "en-IN",
  articleSection: "Law firm workflows",
  author: { "@type": "Organization", name: siteConfig.ownership.legalOwner },
  publisher: {
    "@type": "Organization",
    name: siteConfig.ownership.legalOwner,
    url: siteConfig.url,
  },
};

const sections = [
  { id: "reviewable-record", label: "The reviewable record" },
  { id: "workflow", label: "The workflow" },
  { id: "source-checks", label: "Citation checks" },
  { id: "controlled-access", label: "Controlled access" },
  { id: "team-checklist", label: "Team checklist" },
  { id: "next-read", label: "Further reading" },
] as const;

export default async function SourceGroundedLegalRecommendationsPage() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <>
      <script
        id="source-grounded-recommendations-article-jsonld"
        nonce={nonce}
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] py-12 md:py-16">
          <Container>
            <p className="text-xs font-semibold uppercase text-[var(--color-brand-700)]">
              CaseOps journal / Law firm workflows
            </p>
            <h1 className="mt-4 max-w-3xl font-display text-3xl font-normal leading-tight text-[var(--color-ink)] md:text-4xl">
              {title}
            </h1>
            <p className="mt-5 max-w-[70ch] text-lg leading-relaxed text-[var(--color-ink-2)]">
              {description}
            </p>
            <p className="mt-5 text-sm text-[var(--color-mute)]">
              By {siteConfig.ownership.legalOwner}
            </p>
          </Container>
        </header>

        <Container className="py-10 md:py-14">
          <div className="mx-auto max-w-[70ch]">
            <nav aria-label="On this page" className="border-b border-[var(--color-line)] pb-6">
              <ul className="flex flex-wrap gap-x-6 gap-y-3 text-sm text-[var(--color-ink-2)]">
                {sections.map((section) => (
                  <li key={section.id}>
                    <a href={`#${section.id}`} className="underline underline-offset-4">
                      {section.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>

            <article className="mt-10 min-w-0 space-y-12 text-[var(--color-ink-2)]">
              <section id="reviewable-record" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  The answer should survive opening the source
                </h2>
                <p className="mt-4 leading-relaxed">
                  An associate has assembled the file. A partner needs to choose a next step.
                  The useful question is not how persuasive a recommendation sounds. It is
                  whether the reasoning can be checked against the record.
                </p>
                <p className="mt-4 leading-relaxed">
                  CaseOps puts matter-based recommendations into a reviewable record: options,
                  rationale, supporting citations, assumptions, missing facts and a confidence
                  label. The aim is to make the basis for a proposed action easier to inspect,
                  rather than ask a lawyer to trust a standalone answer. Forum, authority,
                  remedy and next-step recommendations remain decision support, not legal
                  instructions or predictions of success.
                </p>
              </section>

              <section id="workflow" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  From the matter record to a lawyer&apos;s decision
                </h2>
                <ol className="mt-6 list-decimal space-y-6 pl-6 marker:font-semibold marker:text-[var(--color-brand-700)]">
                  <li className="pl-2">
                    <h3 className="font-semibold text-[var(--color-ink)]">Define the question and the scope</h3>
                    <p className="mt-2 leading-relaxed">
                      Start in the relevant matter and choose the recommendation type and
                      objective. Add the lawyer&apos;s thinking where it helps explain what the
                      team is trying to decide. A precise question is more useful than a
                      request to find the best possible strategy without a factual boundary.
                    </p>
                  </li>
                  <li className="pl-2">
                    <h3 className="font-semibold text-[var(--color-ink)]">Establish what evidence is available</h3>
                    <p className="mt-2 leading-relaxed">
                      Check the matter facts, relevant document versions and available authority
                      context. An upload still being processed, a missing order or an incomplete
                      source collection cannot support the same conclusions as a reviewed
                      record. Where source context is insufficient, generation may be refused
                      or confidence reduced. A refusal does not identify every gap for you.
                    </p>
                  </li>
                  <li className="pl-2">
                    <h3 className="font-semibold text-[var(--color-ink)]">Compare the options, not just the first answer</h3>
                    <p className="mt-2 leading-relaxed">
                      Read each option&apos;s rationale and its own supporting citations. Inspect
                      risk notes, assumptions and missing facts before choosing a course of
                      action. Where retained retrieval context is available, the sources panel
                      also distinguishes authorities used from those considered but not cited.
                      That context is not an exhaustive search of every relevant authority.
                    </p>
                  </li>
                  <li className="pl-2">
                    <h3 className="font-semibold text-[var(--color-ink)]">Check the sources and the reasoning</h3>
                    <p className="mt-2 leading-relaxed">
                      Open the cited authority or document using the available source path.
                      Confirm that the passage supports the proposition, the facts match the
                      matter and the legal position remains applicable. An inaccessible or
                      unresolved source is a reason to pause reliance, not fill the gap with
                      a plausible explanation.
                    </p>
                  </li>
                  <li className="pl-2">
                    <h3 className="font-semibold text-[var(--color-ink)]">Record the review decision</h3>
                    <p className="mt-2 leading-relaxed">
                      An authorized reviewer can accept an option, reject the recommendation
                      or defer it. CaseOps retains recommendation decisions for review and
                      audit. Recording a decision is not a court filing, client communication
                      or permission to bypass the firm&apos;s separate approval process.
                    </p>
                  </li>
                </ol>
              </section>

              <section id="source-checks" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  A citation is the start of review, not its conclusion
                </h2>
                <p className="mt-4 leading-relaxed">
                  Generated output can contain legal or factual errors, including unsupported
                  claims and incorrect citations. Retrieval and bounded citation checks support
                  review; they cannot establish that every proposition is correct or that the
                  available corpus is complete. A confidence label is not a probability of
                  winning a case.
                </p>
                <p className="mt-4 leading-relaxed">
                  The lawyer must verify each authority, quotation and material fact against
                  the source and current law. Check the relevant Act, provision, procedural
                  stage and source version. Read surrounding passages and consider contrary
                  authorities rather than treating a source link as an endorsement of the
                  proposed conclusion. This article describes a workflow, not legal advice.
                </p>
              </section>

              <section id="controlled-access" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  Keep the recommendation inside its authorized context
                </h2>
                <p className="mt-4 leading-relaxed">
                  Review starts with the right to see the record. CaseOps separates
                  tenant-private work from shared public authorities and applies matter-level
                  access restrictions alongside role capabilities. Generating and deciding
                  recommendations are permission-controlled actions. Broad team access is not
                  permission to cross a restricted matter or an ethical wall.
                </p>
                <p className="mt-4 leading-relaxed">
                  Tenant AI policy and available source coverage also affect the workflow.
                  A permission denial, disabled policy or unavailable source should be resolved
                  through the appropriate owner, not by copying another client&apos;s material
                  into a different workspace. Before circulating work, recheck the intended
                  recipients and the firm&apos;s confidentiality requirements.
                </p>
              </section>

              <section id="team-checklist" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  Five questions for the reviewing partner
                </h2>
                <ul className="mt-5 list-disc space-y-3 pl-6 leading-relaxed">
                  <li>Is this the right matter, objective and current document record?</li>
                  <li>Can we inspect the sources supporting the chosen option?</li>
                  <li>Which assumptions, missing facts or contrary authorities need attention?</li>
                  <li>Who is authorized to review, decide and receive this work?</li>
                  <li>Has the lawyer recorded a decision before any separate external action?</li>
                </ul>
                <p className="mt-5 leading-relaxed">
                  A useful handover leaves the next lawyer with the question, the evidence and
                  the reason for the decision. That is the practical value of a source-grounded
                  workflow: a recommendation the firm can examine, challenge and take
                  responsibility for, rather than an answer it must accept on appearance.
                </p>
              </section>

              <section id="next-read" className="scroll-mt-24 border-t border-[var(--color-line)] pt-8">
                <h2 className="font-display text-2xl text-[var(--color-ink)]">
                  Put the workflow in context
                </h2>
                <p className="mt-4 leading-relaxed">
                  Explore the wider matter workspace in the{" "}
                  <a href="/guide" className="font-medium underline underline-offset-4">product guide</a>,
                  or use the{" "}
                  <a href="/resources/legal-matter-management-india" className="font-medium underline underline-offset-4">
                    matter management checklist
                  </a>{" "}
                  to evaluate how your team handles records, review and access. Start with
                  a non-confidential sample and check the actual workflow rather than relying
                  on a claim about legal outcomes.
                </p>
              </section>
            </article>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  );
}
