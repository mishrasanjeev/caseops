import type { Metadata } from "next";
import { headers } from "next/headers";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

const path = "/resources/legal-matter-management-india";
const title = "Legal matter management in India: a practical software checklist";
const description =
  "A practical checklist for Indian law firms comparing matter management software: case identity, hearings, documents, access, review, and billing.";

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
  author: {
    "@type": "Organization",
    name: siteConfig.ownership.legalOwner,
  },
  publisher: {
    "@type": "Organization",
    name: siteConfig.ownership.legalOwner,
    url: siteConfig.url,
  },
};

const criteria = [
  {
    title: "Matter identity and lifecycle",
    question: "Can the system distinguish a CNR from a case number, filing number, and internal matter code?",
    proof: "Create a sample matter, add its identifiers in stages, dispose it, and confirm an ordinary edit cannot silently reopen it.",
  },
  {
    title: "Hearings and source provenance",
    question: "Does each next-hearing date show where it came from and who changed it?",
    proof: "Change a date manually, then inspect the previous value, source, actor, and any provider suggestion after reload.",
  },
  {
    title: "Documents and review",
    question: "Can lawyers open the actual file, find its version, and review a draft against its cited sources?",
    proof: "Upload a non-confidential order, open it, create a draft, and verify the citations before approval.",
  },
  {
    title: "Deadlines and notices",
    question: "Are reply dates and court directions linked to the source rather than guessed from ambiguous text?",
    proof: "Record a received notice and an ambiguous direction. Check that the owner and source are visible and ambiguity requires review.",
  },
  {
    title: "Access and audit",
    question: "Can matter-level restrictions override broad team access?",
    proof: "Try the same sample matter as a permitted and a non-permitted user; inspect the audit trail after changing access.",
  },
  {
    title: "Matter billing",
    question: "Do time, expenses, advances, tax fields, invoices, and payment state stay tied to the matter?",
    proof: "Build a sample invoice and verify the amounts and approval state without assuming subscription billing is the same workflow.",
  },
  {
    title: "Provider boundaries",
    question: "What happens when a court source is unsupported, unavailable, rate-limited, or lacks a reliable case identity?",
    proof: "Ask for the eligibility and blocked-state screens. A credible system should show the limitation, not invent a hearing date.",
  },
] as const;

export default async function LegalMatterManagementIndiaPage() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <>
      <script
        id="matter-management-article-jsonld"
        nonce={nonce}
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] py-14 md:py-20">
          <Container>
            <p className="text-xs font-semibold uppercase text-[var(--color-brand-700)]">
              Practice operations / India
            </p>
            <h1 className="mt-4 max-w-4xl font-display text-4xl font-normal leading-tight text-[var(--color-ink)] md:text-5xl">
              Legal matter management in India
            </h1>
            <p className="mt-5 max-w-3xl text-lg leading-relaxed text-[var(--color-ink-2)]">
              A practical checklist for evaluating software around real legal work: case identity,
              hearing provenance, documents, review, access, and billing. Use it with a
              non-confidential sample matter during a product demo.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button href="#checklist" variant="primary">Use the checklist</Button>
              <Button href="/demo/resource" variant="outline">Request a demo</Button>
            </div>
          </Container>
        </header>

        <Container className="py-12 md:py-16">
          <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_14rem]">
            <article className="min-w-0 max-w-3xl space-y-14 text-[var(--color-ink-2)]">
              <section id="definition" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)] md:text-3xl">
                  What is legal matter management software?
                </h2>
                <p className="mt-4 leading-relaxed">
                  It is a shared system of record for a legal team&apos;s matters, people, dates,
                  documents, work, and costs. For Indian litigation, a useful system also keeps
                  CNR and court identity distinct from internal file numbers, records the source
                  of hearing updates, and lets a lawyer review any AI-assisted work before relying
                  on it. Software organizes the evidence; it does not replace source verification
                  or professional judgment.
                </p>
              </section>

              <section id="checklist" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)] md:text-3xl">
                  Seven checks to run in a demo
                </h2>
                <p className="mt-4 leading-relaxed">
                  Ask the vendor to show a saved record, change it, and reload it. A slide or a
                  successful provider response is not proof that the legal team can use the result.
                </p>
                <ol className="mt-7 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
                  {criteria.map((criterion, index) => (
                    <li key={criterion.title} className="grid gap-3 py-6 sm:grid-cols-[2.5rem_minmax(0,1fr)]">
                      <span className="font-mono text-sm text-[var(--color-brand-700)]">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <div>
                        <h3 className="font-semibold text-[var(--color-ink)]">{criterion.title}</h3>
                        <p className="mt-2 leading-relaxed">{criterion.question}</p>
                        <p className="mt-2 text-sm leading-relaxed">
                          <strong className="text-[var(--color-ink)]">Test it: </strong>
                          {criterion.proof}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>

              <section id="court-data" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)] md:text-3xl">
                  Treat court data as evidence, not a promise
                </h2>
                <p className="mt-4 leading-relaxed">
                  A CNR or exact case-number-plus-court identity can make a tracked-case lookup
                  possible. It does not guarantee that a provider has access to every court,
                  record, or current hearing date. Check the court source, timestamp, and
                  eligibility state. If a record cannot be verified, leave it for human review;
                  do not turn a guess into a calendar entry.
                </p>
                <p className="mt-4 leading-relaxed">
                  The official <a className="font-medium underline underline-offset-4" href="https://services.ecourts.gov.in/ecourtindia_v6/">eCourts Services portal</a> is a useful place to verify a supported case record independently. Source access and terms still govern any automated integration.
                </p>
              </section>

              <section id="caseops" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)] md:text-3xl">
                  Where CaseOps fits
                </h2>
                <p className="mt-4 leading-relaxed">
                  CaseOps links intake, matter workspaces, hearings, notices, documents, review-first
                  drafting, and matter billing for Indian legal teams. Matter access and lifecycle
                  changes are governed and audited. Tracked-case refresh depends on eligible
                  identifiers, a configured provider, and lawful source access; the available
                  statute catalog is not a promise of complete coverage. Production payments and
                  some external connectors remain gated by their own readiness requirements.
                </p>
                <p className="mt-4 leading-relaxed">
                  Explore the <a className="font-medium underline underline-offset-4" href="/guide">product guide</a>,
                  review <a className="font-medium underline underline-offset-4" href="/pricing">current plans</a>,
                  or <a className="font-medium underline underline-offset-4" href="/demo/resource">request a guided walkthrough</a>.
                </p>
              </section>

              <section id="questions" className="scroll-mt-24">
                <h2 className="font-display text-2xl text-[var(--color-ink)] md:text-3xl">
                  Common questions
                </h2>
                <dl className="mt-5 space-y-6">
                  <div>
                    <dt className="font-semibold text-[var(--color-ink)]">Can software guarantee the next hearing date?</dt>
                    <dd className="mt-2 leading-relaxed">No. Keep the source and timestamp visible, verify the court record, and review conflicts before changing a matter date.</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-[var(--color-ink)]">Is a CNR the same as an internal matter number?</dt>
                    <dd className="mt-2 leading-relaxed">No. A CNR is a court case identifier. A firm&apos;s matter code is its own filing reference; software should store both without substitution.</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-[var(--color-ink)]">Should AI-generated legal work go straight to filing?</dt>
                    <dd className="mt-2 leading-relaxed">No. A lawyer should inspect source links, missing facts, assumptions, and the current legal position before approving a draft or deadline.</dd>
                  </div>
                </dl>
              </section>
            </article>

            <nav aria-label="On this page" className="hidden self-start border-l border-[var(--color-line)] pl-5 text-sm lg:sticky lg:top-24 lg:block">
              <p className="font-semibold text-[var(--color-ink)]">On this page</p>
              <ul className="mt-4 space-y-3">
                <li><a href="#definition" className="hover:underline">Definition</a></li>
                <li><a href="#checklist" className="hover:underline">Demo checklist</a></li>
                <li><a href="#court-data" className="hover:underline">Court data</a></li>
                <li><a href="#caseops" className="hover:underline">CaseOps fit</a></li>
                <li><a href="#questions" className="hover:underline">Questions</a></li>
              </ul>
            </nav>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  );
}
