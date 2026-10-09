import type { Metadata } from "next";
import {
  BadgeCheck,
  BookOpenText,
  Briefcase,
  Calendar,
  CircleDollarSign,
  FileSignature,
  Gavel,
  IndianRupee,
  Layers,
  Scale,
  Search,
  Smartphone,
  Wallet,
} from "lucide-react";

import { Footer } from "@/components/marketing/Footer";
import {
  MetricCard,
  PersonaSwitch,
  PitchCard,
  PitchNav,
  ReviewRow,
  Slide,
} from "@/components/marketing/pitch/primitives";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "Practice management software for solo lawyers in India",
  description:
    "Manage matters, hearing dates, source-backed drafts, research, and billing in one CaseOps workspace for solo advocates in India.",
  alternates: { canonical: "/solo-lawyers" },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}/solo-lawyers`,
    title: `Practice management software for solo lawyers in India - ${siteConfig.name}`,
    description:
      "Keep matters, hearing dates, review-first drafting, and billing together. Check provider coverage for your courts before relying on automated updates.",
  },
};

const slides = [
  { id: "cover", label: "Cover" },
  { id: "problem", label: "Problem" },
  { id: "ai-angle", label: "AI angle" },
  { id: "diary", label: "Diary" },
  { id: "drafting", label: "Drafting" },
  { id: "appeals", label: "Appeals" },
  { id: "research", label: "Research" },
  { id: "billing", label: "Billing" },
  { id: "pricing", label: "Pricing" },
  { id: "contact", label: "Contact" },
] as const;

export default function SoloLawyersPage() {
  return (
    <>
      <SkipLink />
      <PitchNav persona="Solo lawyers" slides={slides} contactEmail={siteConfig.contact.founder} />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <Slide
          id="cover"
          headingLevel={1}
          index="01"
          tone="ink"
          eyebrow="CaseOps for solo advocates"
          title="Practice management for solo advocates in India."
          description="Keep the matter record, hearing work, review-first drafting, research and billing in one workspace. Ask us about coverage and early-access terms for your practice."
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="grid gap-3 sm:grid-cols-3">
              <MetricCard inverse value="1" label="Workspace" note="Matter, hearing, drafting and billing workflows together." />
              <MetricCard inverse value="Matter-linked" label="Hearing pack" note="Compiled from the available matter record." />
              <MetricCard inverse value="UAT gated" label="Payments" note="Invoice PDFs and payment tracking are live; Pine Labs is disabled until UAT." />
            </div>
            <div className="flex flex-col gap-3 lg:items-end">
              <PersonaSwitch active="solos" />
              <a
                href="/demo/solo-lawyers"
                className="inline-flex items-center rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-[var(--color-ink)] transition-colors hover:bg-white/85"
              >
                Start a pilot
              </a>
            </div>
          </div>
        </Slide>

        <Slide
          id="problem"
          index="02"
          tone="light"
          eyebrow="What a solo is running today"
          title="Bring a scattered practice into one matter record."
          description="A practice may use separate records for dates, documents and fees. Review which workflows CaseOps can support for your courts and working style."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={Search}
              title="Research subscriptions"
              body="One subscription for research; another to download PDFs; citations pasted by hand."
            />
            <PitchCard
              icon={FileSignature}
              title="Word + email"
              body="Drafts live in a Downloads folder named 'bail 3 FINAL v2'."
            />
            <PitchCard
              icon={Calendar}
              title="Case diary"
              body="A diary or shared sheet may need manual reconciliation with the current court source."
            />
            <PitchCard
              icon={CircleDollarSign}
              title="Billing"
              body="Tally, an Excel invoice template, or a WhatsApp 'kindly pay' reminder."
            />
          </div>
          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-6 text-[14px] leading-relaxed text-[var(--color-ink-2)]">
            <span className="font-semibold text-[var(--color-ink)]">Real cost:</span>{" "}
            administrative work can interrupt legal preparation. CaseOps brings supported
            matter workflows together; it does not replace the advocate or guarantee time savings.
          </div>
        </Slide>

        <Slide
          id="ai-angle"
          index="03"
          tone="light"
          eyebrow="The AI angle"
          title="The associate you couldn't afford to hire."
          description="AI can help assemble drafts, chronologies and source candidates from available records. The advocate checks the facts, citations and final legal position before use."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={FileSignature}
              title="Review-first drafts"
              body="Drafts use available matter facts and source references. Missing facts and unsupported citations need advocate review before filing."
            />
            <PitchCard
              icon={Search}
              title="Research like a big firm"
              body="The same corpus the firms retrieve against — Supreme Court + high courts — embedded and searchable."
            />
            <PitchCard
              icon={Gavel}
              title="Hearing pack on open"
              body="Chronology, last order, proceeding directions, affidavit prep, mock-hearing prompts, and coach feedback compile from your own matter record."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Source checks and placeholders"
              body="When evidence is thin, the workflow flags gaps or leaves placeholders. The advocate remains responsible for checking every citation and fact."
            />
          </div>

          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)] md:p-8">
            <div className="grid gap-5 md:grid-cols-[1.1fr_0.9fr] md:items-center">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                  Less assembly, more review
                </div>
                <p className="mt-3 text-[15.5px] leading-relaxed text-[var(--color-ink-2)]">
                  Matter-linked drafts, hearing notes and billing records can reduce
                  repeated copying between tools. The actual time saved depends on
                  the practice, available source material and the advocate's review.
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-[13.5px] leading-relaxed text-[var(--color-mute)]">
                <span className="font-semibold text-[var(--color-ink-2)]">Agentic help:</span>{" "}
                cause-list reconciliation is an on-demand action. Scheduled provider
                updates depend on tenant eligibility, court coverage and configured
                access. Source material and substantive suggestions remain reviewable.
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="diary"
          index="04"
          tone="brand"
          eyebrow="Case diary + hearings"
          title="Morning opens with the day already compiled."
          description="Sign in. See today's listings as soon as they're imported into your matter record. One-click hearing pack for the matters you are arguing — chronology and last order already pinned. The bench-name resolver links each scheduled judge to their profile (Supreme Court + Delhi HC live; other High Courts as their judge data lands)."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Gavel}
              title="Cause-list import — manual today, automated incrementally"
              body="Review imported cause-list entries against their current court source. Bench names can resolve to mapped judge profiles where identities and coverage are available. Automated court adapters remain subject to lawful source access and readiness evidence."
            />
            <PitchCard
              icon={Layers}
              title="Hearing pack compile"
              body="Chronology, last order, proceeding directions, oral points and available source-backed bench context assembled from the matter record."
            />
            <PitchCard
              icon={Smartphone}
              title="iPad-ready in court"
              body="Responsive work areas support smaller screens. Check the workflows and controls you need during a pilot; confirm destructive actions before proceeding."
            />
          </div>
        </Slide>

        <Slide
          id="drafting"
          index="05"
          tone="light"
          eyebrow="Drafting with citations"
          title="Prepare a first draft for review."
          description="Open a matter, choose a template and add a focus note. Drafting uses available matter context and sources to propose text, citations and placeholders. Generated facts and citations can be wrong or incomplete; verify them before use."
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div className="grid gap-3">
              <ReviewRow
                icon={FileSignature}
                title="Check each citation"
                body="Inspect proposed authorities and source links. Missing facts may be marked as placeholders, but the checks cannot identify every gap. Verify generated facts and citations before use."
              />
              <ReviewRow
                icon={BookOpenText}
                title="Review statute attribution"
                body="Statute checks cover selected known mistakes, not every attribution error. Verify the Act, subsection and current law before use."
              />
              <ReviewRow
                icon={Scale}
                title="Reviewer findings block"
                body="Review open fact placeholders, citation coverage and statute checks before any filing decision."
              />
            </div>
            <div className="rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg)] p-6">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                A reviewable starting point
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-2)]">
                Start from the available matter record and cited sources, then test
                the draft against the file. No fixed time saving is promised.
              </p>
              <p className="mt-3 text-[14px] leading-relaxed text-[var(--color-mute)]">
                The review is still yours. The clerical work isn't.
              </p>
            </div>
          </div>
        </Slide>

        <Slide
          id="appeals"
          index="06"
          tone="light"
          eyebrow="Appeals + bench-aware drafting"
          title="Bench-aware appeal preparation."
          description="When the listing's bench is resolved and relevant decisions are indexed, appeal preparation can use that source context. Limited coverage stays visible. Only source-verified statute provisions are available for attachment; catalog coverage remains incomplete."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="Source-based" label="Judge references" note="Use available indexed decisions; missing history is not inferred." />
            <MetricCard value="Verified only" label="Statute citations" note="Unverified catalog entries cannot be attached as verified legal evidence." />
            <MetricCard value="Alias-aware" label="Bench matching" note="Known aliases resolve to canonical judge records; unresolved names stay visible." />
            <MetricCard value="0" label="Outcome forecasts" note="Bench-aware drafting stays on citation selection, source context, and limitation notes." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Gavel}
              title="Bench-specific authorities"
              body="When the next listing's bench is resolved, drafting can use indexed authorities from that bench. Missing or weak history is disclosed as a limitation."
            />
            <PitchCard
              icon={BookOpenText}
              title="Verified statute references"
              body="Attach available verified provisions as cited, opposing or contextual references. Inspect the exact source version; catalogued does not mean verified."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Argument completeness, not forecasts"
              body="The Appeal Strength panel flags per-ground citation coverage and weak-evidence paths. The advocate decides; the system stays on source-backed preparation."
            />
          </div>
        </Slide>

        <Slide
          id="research"
          index="07"
          tone="brand"
          eyebrow="Research"
          title="Judgment research."
          description="Search indexed authorities by legal issue and inspect the returned sources. Ranking supports research; it does not establish that a decision applies to your matter."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="Source-linked" label="Judgment references" note="Inspect citations and available provenance." />
            <MetricCard value="Voyage" label="Embedding pipeline" note="Production retrieval uses voyage-4-large embeddings." />
            <MetricCard value="Reranked" label="Research results" note="Cross-encoder ranking supports source-based review." />
            <MetricCard value="Not certified" label="Corpus quality score" note="No representative legal-retrieval rating is claimed here." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Search}
              title="Phrase the issue"
              body="Search with issue phrases or keywords, then inspect the authority, jurisdiction and source context of each result."
            />
            <PitchCard
              icon={Briefcase}
              title="Tenant-private annotations"
              body="Flag or shortlist an authority for your matter. Annotations travel with the matter, not you."
            />
            <PitchCard
              icon={BookOpenText}
              title="Check coverage before relying on results"
              body="A no-result response can reflect limited corpus coverage. Inspect each returned authority and do not treat search rank as legal relevance."
            />
          </div>
        </Slide>

        <Slide
          id="billing"
          index="08"
          tone="ink"
          eyebrow="Billing + recoveries"
          title="The invoice goes out with payment tracking."
          description="Matter invoice PDFs, GST/TDS adjustments, partial payments, write-offs, and audit are live. Pine Labs payment collection remains disabled until UAT credentials, webhook evidence, settlement/refund/dispute proof, and founder go/no-go are complete."
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div className="grid gap-3">
              <ReviewRow
                inverse
                icon={IndianRupee}
                title="Time → invoice → paid, without re-keying"
                body="Log time from the matter. Draft the invoice. Send. Get paid. Every state change on the audit trail."
              />
              <ReviewRow
                inverse
                icon={Wallet}
                title="India GST on the line item"
                body="GST on the invoice row. Monthly report exports to the format your accountant already uses."
              />
              <ReviewRow
                inverse
                icon={BadgeCheck}
                title="Partial payments + write-offs first-class"
                body="Not a free-text note. Every recovery state is a real record."
              />
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">
                The practical win
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-white/85">
                Solos get a cleaner recovery workflow: invoice, payment state, write-off,
                and audit are in the matter record. External payment links remain
                provider-gated until UAT evidence is complete.
              </p>
            </div>
          </div>
        </Slide>

        <Slide
          id="pricing"
          index="09"
          tone="light"
          eyebrow="Pricing"
          title="Priced for a practice of one."
          description="Review the current plan catalog and discuss a pilot. Scope, duration, support and any pilot pricing require separate confirmation."
        >
          <div className="grid gap-5 md:grid-cols-3">
            <div className="rounded-2xl border-2 border-[var(--color-ink)] bg-white p-7 shadow-[var(--shadow-soft)]">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                Solo pilot
              </div>
              <div className="mt-3 font-display text-2xl font-normal text-[var(--color-ink)]">
                Early access
              </div>
              <p className="mt-2 text-[13px] text-[var(--color-mute-2)]">
                Review current plans; pilot terms confirmed separately
              </p>
              <ul className="mt-5 space-y-2 text-[13.5px] text-[var(--color-ink-2)]">
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Matter, hearing, and drafting workspace
                </li>
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Case diary; source-dependent cause-list coverage
                </li>
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Provider-gated Pine Labs readiness, disabled until UAT
                </li>
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Research corpus and authorities
                </li>
              </ul>
            </div>
            <div className="rounded-2xl border border-[var(--color-line)] bg-white p-7 md:col-span-2">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
                How a pilot starts
              </div>
              <ol className="mt-4 space-y-3 text-[14px] text-[var(--color-ink-2)]">
                <li className="flex gap-3">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white">
                    1
                  </span>
                  Request a conversation about your practice and court coverage. Scheduling is confirmed separately.
                </li>
                <li className="flex gap-3">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white">
                    2
                  </span>
                  Confirm court-source coverage, available templates and any setup before agreeing a pilot.
                </li>
                <li className="flex gap-3">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white">
                    3
                  </span>
                  Agree any pilot duration and commercial terms before using real matters. No pilot price is locked by submitting a request.
                </li>
              </ol>
            </div>
          </div>
        </Slide>

        <Slide
          id="contact"
          index="10"
          tone="ink"
          eyebrow="Contact"
          title="Write to the founder."
          description="Request a founder conversation about a possible solo pilot. Availability and response timing are confirmed separately."
          className="border-b-0"
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-8">
              <div className="text-xs font-semibold uppercase tracking-[0.2em] text-white/55">
                Direct contact
              </div>
              <a
                href="/demo/solo-lawyers"
                className="mt-4 inline-block font-display text-[2.25rem] font-normal leading-none tracking-tight text-white hover:text-white/85 md:text-[3rem]"
              >
                Request a conversation
              </a>
              <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
                Tell us about your practice without sharing client or case details.
                Any walkthrough, workspace setup, court coverage and pilot terms
                require separate confirmation.
              </p>
            </div>
            <PersonaSwitch active="solos" />
          </div>
        </Slide>
      </main>
      <Footer />
    </>
  );
}
