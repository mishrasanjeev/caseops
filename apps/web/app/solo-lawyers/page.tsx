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
  title: "CaseOps for solo lawyers",
  description:
    "Operate like a 20-lawyer practice without hiring one. Case diary, drafting with citations, research, billing and Pine Labs payment links in one workspace for solo advocates.",
  alternates: { canonical: "/solo-lawyers" },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}/solo-lawyers`,
    title: `For solo lawyers — ${siteConfig.name}`,
    description:
      "Replace five subscriptions and a paper diary with one workspace built for the solo advocate on laptop, iPad and court mornings.",
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
          index="01"
          tone="ink"
          eyebrow="CaseOps for solo advocates"
          title="Operate like a 20-lawyer practice. Alone."
          description="The same matter-graph workspace the firms use — tuned and priced for the advocate on a laptop at night and in court by morning. One login replaces five subscriptions and a paper diary."
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="grid gap-3 sm:grid-cols-3">
              <MetricCard inverse value="1" label="Workspace" note="Replaces case diary, research, drafting and billing." />
              <MetricCard inverse value="< 60s" label="Hearing pack" note="Compiled from the matter record when you open it." />
              <MetricCard inverse value="Pine Labs" label="Payments" note="UPI + cards on every invoice." />
            </div>
            <div className="flex flex-col gap-3 lg:items-end">
              <PersonaSwitch active="solos" />
              <a
                href={`mailto:${siteConfig.contact.founder}?subject=Solo%20advocate%20pilot`}
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
          title="Five tools. Five logins. One paper diary the clerk cannot read."
          description="The work is the lawyer's. The infrastructure is no one's. Something is always lost."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={Search}
              title="SCC Online / Manupatra"
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
              body="Paper. Sometimes a shared Google Sheet. Never in sync with the court cause list."
            />
            <PitchCard
              icon={CircleDollarSign}
              title="Billing"
              body="Tally, an Excel invoice template, or a WhatsApp 'kindly pay' reminder."
            />
          </div>
          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-6 text-[14px] leading-relaxed text-[var(--color-ink-2)]">
            <span className="font-semibold text-[var(--color-ink)]">Real cost:</span>{" "}
            the lawyer does the work of five people before 10 am — and the work is
            administrative, not legal. CaseOps removes the administrative half.
          </div>
        </Slide>

        <Slide
          id="ai-angle"
          index="03"
          tone="light"
          eyebrow="The AI angle"
          title="The associate you couldn't afford to hire."
          description="AI takes the clerical half of a solo's day — first drafts, citation chasing, chronology assembly, invoice reconciliation — and hands it back as reviewable work. It never replaces the lawyer's judgment; it removes the work that kept the lawyer from doing judgment."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={FileSignature}
              title="First drafts in minutes"
              body="Grounded drafts with inline citations from the matter record. You review and sign; you don't assemble."
            />
            <PitchCard
              icon={Search}
              title="Research like a big firm"
              body="The same corpus the firms retrieve against — Supreme Court + high courts — embedded and searchable."
            />
            <PitchCard
              icon={Gavel}
              title="Hearing pack on open"
              body="Chronology, last order, oral points compiled from your own matter record when you tap the hearing."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Refuses to fabricate"
              body="Never invents a case law citation, never invents a fact. Placeholders and explicit refusals when evidence is thin."
            />
          </div>

          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)] md:p-8">
            <div className="grid gap-5 md:grid-cols-[1.1fr_0.9fr] md:items-center">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                  What a solo gets back
                </div>
                <p className="mt-3 text-[15.5px] leading-relaxed text-[var(--color-ink-2)]">
                  Two to three hours of first-draft assembly. An hour of citation chasing.
                  Forty minutes reconciling the diary and cause-list. Twenty minutes
                  building a hearing pack. Every one of those is clerical. Every one is
                  now a few minutes of review at best — time that goes back to clients,
                  or back to the family.
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-[13.5px] leading-relaxed text-[var(--color-mute)]">
                <span className="font-semibold text-[var(--color-ink-2)]">Agentic help:</span>{" "}
                cause-list reconciler exists as an on-demand action today — click to run
                against tomorrow's listings. Automated nightly scheduling via Cloud
                Scheduler ships in the next release. Corpus ingest runs on its own so
                your research stays current. Every substantive step is yours to accept.
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
              body="Today: cause-list entries are imported per matter (paste / API / nightly job for the courts that have a wired adapter). The bench resolver normalises 'Justice X & Justice Y' rosters into clickable judge profiles with the high-quality confidence floor. Per-HC automated scrapers ship as each court's PRD lands."
            />
            <PitchCard
              icon={Layers}
              title="Hearing pack compile"
              body="Chronology, last order, oral points and bench brief assembled from the matter record. Under a minute."
            />
            <PitchCard
              icon={Smartphone}
              title="iPad-ready in court"
              body="The UI stays legible on a 9-inch screen. No hover-only actions. No surprise modals."
            />
          </div>
        </Slide>

        <Slide
          id="drafting"
          index="05"
          tone="light"
          eyebrow="Drafting with citations"
          title="A first draft before the second coffee."
          description="Open a matter. Pick a template — bail, quashing, reply to summons, §34 petition. Add a focus note. Press Generate. Get a draft with inline citations to named judgments and fact placeholders for anything not in the record."
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div className="grid gap-3">
              <ReviewRow
                icon={FileSignature}
                title="Never a fabricated citation"
                body="Inline citations resolve to named authorities. Nothing is invented. Fact gaps render as placeholders for you to fill."
              />
              <ReviewRow
                icon={BookOpenText}
                title="Statute attribution kept clean"
                body="BNSS vs BNS clamped; Arbitration Act sections attributed by the right subsection; no cross-statute confusion."
              />
              <ReviewRow
                icon={Scale}
                title="Reviewer findings block"
                body="At the foot of every draft: open fact placeholders, citation coverage, statute checks. A 30-second pre-filing sanity pass."
              />
            </div>
            <div className="rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg)] p-6">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                What a solo typically saves
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-2)]">
                2–3 hours of first-draft assembly, plus an hour of citation chasing, per
                bail or quashing. That is a billable afternoon back, every day.
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
          title="The appeal cites the bench that's actually hearing it."
          description="When the matter has an upcoming listing, the appeal-memorandum draft pulls authorities authored by THAT specific bench (not just the court at large) and prefers ones that match the practice area. Section 482 BNSS quoted verbatim from the bare-acts catalog. Argument completeness flagged per ground — never win/lose prediction."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="63" label="Judges live" note="31 SC + 32 Delhi HC sitting bench, with career history and indexed authorities." />
            <MetricCard value="91" label="Statute sections" note="BNSS, BNS, BSA, CrPC, IPC, Constitution, NI Act — bare text + clickable indiacode.nic.in source." />
            <MetricCard value="269" label="Judge aliases" note="Tolerant matcher resolves 'A.K. Sikri' to the canonical judge row, no ILIKE fragility." />
            <MetricCard value="0%" label="Favorability score" note="Bench-aware drafting hard rule: no win/lose/probability/tendency language. Anywhere." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Gavel}
              title="Bench-specific authorities"
              body="When the next listing's bench is resolved, BAAD injects up to 5 authorities authored by that bench, picked to support the matter's practice area. Limitation note when the bench can't be resolved — never silent."
            />
            <PitchCard
              icon={BookOpenText}
              title="Statute model with verbatim quoting"
              body="7 central acts catalogued. Attach sections to a matter as 'cited' / 'opposing' / 'context'; the prompt receives the bare text so the LLM quotes verbatim instead of paraphrasing."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Argument completeness, not outcome prediction"
              body="The Appeal Strength panel flags per-ground citation coverage and weak-evidence paths. The advocate decides; the system never claims a win probability."
            />
          </div>
        </Slide>

        <Slide
          id="research"
          index="07"
          tone="brand"
          eyebrow="Research"
          title="The same corpus the big firms are retrieving against."
          description="Over 5,700 judgments from the Supreme Court and high courts, embedded and indexed. Hybrid retrieval: phrase the issue, not a keyword. Results come back with cosine-strength so you can judge at a glance."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="5,714" label="Judgments indexed" note="Supreme Court + high courts." />
            <MetricCard value="108k" label="Chunks" note="voyage-4-large embeddings · 1024-dim." />
            <MetricCard value="96.7%" label="Recall@10" note="Live self-recall probe with cross-encoder rerank." />
            <MetricCard value="0.95" label="MRR" note="Correct hit almost always rank 1 — mean rank 1.03." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Search}
              title="Phrase the issue"
              body="'triple test for anticipatory bail under BNSS s.482' works. Keyword-only tools can't."
            />
            <PitchCard
              icon={Briefcase}
              title="Tenant-private annotations"
              body="Flag or shortlist an authority for your matter. Annotations travel with the matter, not you."
            />
            <PitchCard
              icon={BookOpenText}
              title="Refuses to invent"
              body="If your query sits outside the corpus, you get an explicit no-result — not a fabricated citation."
            />
          </div>
        </Slide>

        <Slide
          id="billing"
          index="08"
          tone="ink"
          eyebrow="Billing + recoveries"
          title="The payment link goes out with the invoice."
          description="Pine Labs payment links land on every invoice today — UPI and cards. Automatic paid-state writeback from settlement callbacks ships in a near-term release; for now, you mark invoices paid when reconciling, and the payment link itself already converts faster than a polite reminder."
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
                Solos using CaseOps typically collect 8–15 days earlier than their previous
                cycle. The link in the invoice converts intention to paid faster than any
                polite reminder ever did.
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
          description="Early access means pilot pricing. The full rate card firms up after we understand how a solo actually uses the product. Lock in pilot terms now."
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
                per lawyer / month
              </p>
              <ul className="mt-5 space-y-2 text-[13.5px] text-[var(--color-ink-2)]">
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Matter, hearing, and drafting workspace
                </li>
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Case diary and cause-list sync
                </li>
                <li className="flex gap-2">
                  <span aria-hidden className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]" />
                  Pine Labs payment collection
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
                  30-minute sign-up call. You tell us which court(s) you appear in most often.
                </li>
                <li className="flex gap-3">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white">
                    2
                  </span>
                  We preload cause-list sync and a template pack (bail, quashing, §34, reply to summons).
                </li>
                <li className="flex gap-3">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white">
                    3
                  </span>
                  You use it for two weeks on real matters. Pilot price is locked in if you stay.
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
          description="Solo pilots are handled directly by the founder until we are larger. Expect a human reply within a working day."
          className="border-b-0"
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-8">
              <div className="text-xs font-semibold uppercase tracking-[0.2em] text-white/55">
                Direct contact
              </div>
              <a
                href={`mailto:${siteConfig.contact.founder}?subject=Solo%20advocate%20pilot`}
                className="mt-4 inline-block font-display text-[2.25rem] font-normal leading-none tracking-tight text-white hover:text-white/85 md:text-[3rem]"
              >
                {siteConfig.contact.founder}
              </a>
              <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
                Tell us the forum you appear in most and the two case types that take up
                the most of your week. We set up the sandbox, send a login, and jump on
                a 30-minute call to run through it with you.
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
