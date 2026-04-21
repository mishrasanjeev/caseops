import type { Metadata } from "next";
import {
  Activity,
  BadgeCheck,
  Briefcase,
  ClipboardCheck,
  FileSearch,
  GitBranch,
  Landmark,
  Layers,
  ScrollText,
  ShieldCheck,
  Users,
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
  title: "CaseOps for general counsels",
  description:
    "An operating layer for in-house legal teams. Portfolio visibility, outside counsel spend, contractual obligations and compliance posture on one matter graph.",
  alternates: { canonical: "/general-counsels" },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}/general-counsels`,
    title: `For general counsels — ${siteConfig.name}`,
    description:
      "Stop stitching together matter trackers, contract repos, spend spreadsheets and compliance calendars. One matter graph for in-house legal.",
  },
};

const slides = [
  { id: "cover", label: "Cover" },
  { id: "problem", label: "Problem" },
  { id: "ai-angle", label: "AI angle" },
  { id: "portfolio", label: "Portfolio" },
  { id: "counsel", label: "Counsel" },
  { id: "obligations", label: "Obligations" },
  { id: "risk", label: "Risk + audit" },
  { id: "proof", label: "Proof" },
  { id: "contact", label: "Contact" },
] as const;

export default function GeneralCounselsPage() {
  return (
    <>
      <SkipLink />
      <PitchNav persona="General counsels" slides={slides} contactEmail={siteConfig.contact.founder} />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <Slide
          id="cover"
          index="01"
          tone="ink"
          eyebrow="CaseOps for general counsels"
          title="The operating layer for in-house legal."
          description="Portfolio, counsel, contracts, obligations and compliance — one matter graph that gives the GC a real answer when the CEO asks, 'what are we exposed to?'"
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="grid gap-3 sm:grid-cols-3">
              <MetricCard inverse value="1" label="Portfolio view" note="Every matter, counsel and spend line on one surface." />
              <MetricCard inverse value="< 60s" label="Board-ready extract" note="Audit trail export for any date range." />
              <MetricCard inverse value="0" label="Cross-tenant spillover" note="Isolation at the storage and query layer." />
            </div>
            <div className="flex flex-col gap-3 lg:items-end">
              <PersonaSwitch active="gcs" />
              <a
                href={`mailto:${siteConfig.contact.founder}?subject=CaseOps%20for%20our%20legal%20team`}
                className="inline-flex items-center rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-[var(--color-ink)] transition-colors hover:bg-white/85"
              >
                Talk to the founder
              </a>
            </div>
          </div>
        </Slide>

        <Slide
          id="problem"
          index="02"
          tone="light"
          eyebrow="What's broken today"
          title="Five tools, none of them agreeing."
          description="A GC stitches a matter tracker, a contract repo, an outside-counsel spreadsheet, a compliance calendar and a board deck. Nothing rolls up. The quarterly board answer is improvised."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={Briefcase}
              title="Matter tracker"
              body="Internally built in Smartsheet or Excel; out of date within a week of board day."
            />
            <PitchCard
              icon={ScrollText}
              title="Contract repo"
              body="A DMS folder. Obligations extracted manually by a paralegal if at all."
            />
            <PitchCard
              icon={Wallet}
              title="Outside counsel spend"
              body="Email invoices, a quarterly consolidation, no realisation against budget."
            />
            <PitchCard
              icon={ClipboardCheck}
              title="Compliance calendar"
              body="A PDF owner's list; the owner left two quarters ago."
            />
          </div>
          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-6 text-[14px] leading-relaxed text-[var(--color-ink-2)]">
            <span className="font-semibold text-[var(--color-ink)]">The real cost:</span>{" "}
            every board meeting becomes a fire drill. The GC can answer the question, but
            only by paying a human week to reconcile four systems. CaseOps replaces the
            reconciliation, not the humans.
          </div>
        </Slide>

        <Slide
          id="ai-angle"
          index="03"
          tone="light"
          eyebrow="The AI angle"
          title="Explainable answers the board will accept."
          description="AI compresses 80 matters and 200 contracts into 'here's what we're exposed to, here's who said what, here's what's due next quarter' — with every number traceable to a source. No black-box risk scores, no favourability percentages, no surprise legal judgment."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={FileSearch}
              title="Contract → obligation — shipped"
              body="LLM extracts parties, covenants, payment terms, consent clauses, audit rights today. Every duty becomes a task; due dates pulled where the contract states them, placeholders where it doesn't."
            />
            <PitchCard
              icon={Activity}
              title="Portfolio rollups"
              body="AI summarises 80 matter records into a board-ready extract. Every line is traceable to the underlying matter and audit event."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Grounded recommendations"
              body="Forum, authority and next-action recommendations with rationale, assumptions, missing facts, and confidence on every option."
            />
            <PitchCard
              icon={ShieldCheck}
              title="AI policy scaffold"
              body="Tenant-scoped AI policy table in the data model; runtime enforcement ships in Sprint M. Until then, provider selection is set per deployment, not per tenant."
            />
          </div>

          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)] md:p-8">
            <div className="grid gap-5 md:grid-cols-2 md:items-start">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-brand-600)]">
                  What the GC gets to say
                </div>
                <p className="mt-3 text-[15.5px] leading-relaxed text-[var(--color-ink-2)]">
                  "Of our 83 open matters, 11 have a deadline in the next 30 days. Of our
                  214 active contracts, 6 have audit rights expiring this quarter and 3
                  have payment obligations overdue. Here is the audit export covering
                  every AI action that went into those numbers."
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-[13.5px] leading-relaxed text-[var(--color-mute)]">
                <span className="font-semibold text-[var(--color-ink-2)]">Agentic posture:</span>{" "}
                AI does the watching and the stitching — cause-list reconciliation,
                obligation-due watchers, intake triage. Humans accept substantive legal
                output. No filings, payments or client communications are sent without a
                recorded human approval. Cross-tenant training is off by default.
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="portfolio"
          index="04"
          tone="brand"
          eyebrow="Portfolio"
          title="Every matter on one surface, rolling up to the board."
          description="A matter is the unit of work. Its stage, documents, counsel, spend and obligations all attach to the same record. The portfolio view is the same record, aggregated."
        >
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            <PitchCard
              icon={Layers}
              title="Single matter graph"
              body="Open, pending, on hold, closed — with stage, forum and next action in one row per matter."
            />
            <PitchCard
              icon={Activity}
              title="Live stage + next action"
              body="No more 'last update on Tuesday'. The cockpit reflects state the moment anyone records an event."
            />
            <PitchCard
              icon={GitBranch}
              title="Team scope and walls"
              body="Restrict visibility at a matter level when a case is conflicted or sensitive — without reshuffling roles."
            />
          </div>
        </Slide>

        <Slide
          id="counsel"
          index="05"
          tone="light"
          eyebrow="Outside counsel"
          title="Brief, budget and measure — without a spreadsheet."
          description="Outside counsel becomes a first-class workspace. Assign a matter to a firm, set a budget with alerts, see realisation against it, compare outcomes across firms."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Briefcase}
              title="Directory with outcomes"
              body="Rate cards, practice areas, historical outcomes, conflict flags — not just a contact list."
            />
            <PitchCard
              icon={Wallet}
              title="Budget with alerts"
              body="Spend cap per matter. Invoices beyond the cap require a GC override, recorded on the audit trail."
            />
            <PitchCard
              icon={Activity}
              title="Realisation by firm"
              body="See billed, collected and aging per counsel. Compare realisation rates across firms before the next brief."
            />
          </div>
          <div className="mt-8 grid gap-4 rounded-2xl border border-[var(--color-line)] bg-white p-6 md:grid-cols-[1fr_1fr] md:p-8">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                What a GC gets to say in the board meeting
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-2)]">
                "We briefed 14 matters to 6 outside counsel this quarter. Realisation against
                budget is 92%. Two firms came in under; one is trending over — we moved the
                next brief away from them."
              </p>
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                Instead of
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-mute)]">
                "Let me come back to you with those numbers next week." — a sentence that
                quietly loses a GC their seat at the table.
              </p>
            </div>
          </div>
        </Slide>

        <Slide
          id="obligations"
          index="06"
          tone="brand"
          eyebrow="Contracts and obligations"
          title="Pull duties out of contracts. Track them where they live."
          description="Contract storage, LLM-powered clause extraction, obligation tracker, and playbook comparison — all shipped. Upload a vendor MSA, get structured clauses in 30 seconds and a deviation report against the default Indian commercial playbook."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={FileSearch}
              title="Clause extraction"
              body="Haiku reads the contract and lifts parties, term, payment, confidentiality, IP, liability, indemnity, governing law, arbitration, force majeure, notices — ~12 structured clauses per contract."
            />
            <PitchCard
              icon={ClipboardCheck}
              title="Obligation tracker"
              body="Payment, reporting, notice, renewal and termination duties become tasks with due dates where the contract states them. Surfaces on the matter cockpit."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Playbook compare"
              body="15-rule default Indian commercial playbook seeds in one click. Sonnet compares each clause against the expected position and flags matched / missing / deviation with severity."
            />
          </div>
        </Slide>

        <Slide
          id="risk"
          index="07"
          tone="ink"
          eyebrow="Risk, audit and AI posture"
          title="Control is built in, not bolted on."
          description="The standard a GC should expect — some shipped today, some on a dated roadmap: tenant isolation by construction (shipped), matter-level ethical walls (shipped), audit on every sensitive action (shipped), AI policy enforcement (Sprint M)."
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div className="grid gap-3">
              <ReviewRow
                inverse
                icon={ShieldCheck}
                title="Tenant isolation at the engine layer"
                body="Every record carries a tenant id. Storage, query and retrieval filter by it, not only the application layer."
              />
              <ReviewRow
                inverse
                icon={Landmark}
                title="Matter-level ethical walls"
                body="A walled matter is invisible to users outside the wall — including admins. Override, not weaken."
              />
              <ReviewRow
                inverse
                icon={Activity}
                title="Audit on every sensitive action"
                body="Upload, draft, approval, AI run, recommendation accept, invoice state change — recorded with actor and before/after state."
              />
              <ReviewRow
                inverse
                icon={BadgeCheck}
                title="AI policy — Sprint M"
                body="Tenant-scoped AI policy table exists; runtime enforcement ships in Sprint M. Until then, provider selection is set per deployment."
              />
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">
                When the board asks for evidence
              </div>
              <p className="mt-3 text-[14.5px] leading-relaxed text-white/85">
                Export the audit trail for a date range as JSONL or CSV. Every sensitive
                action is recorded with actor, timestamp and before/after state.
                Recommendation acceptances are distinguishable from human actions.
              </p>
              <p className="mt-3 text-[14.5px] leading-relaxed text-white/85">
                Cross-tenant training is off by default. Your matters and contracts are not
                pooled for model training without an explicit written opt-in.
              </p>
            </div>
          </div>
        </Slide>

        <Slide
          id="proof"
          index="08"
          tone="light"
          eyebrow="Proof plane"
          title="Numbers, not testimonials."
          description="We publish the retrieval metrics. We instrument the product. A 30-minute quality probe runs against the live corpus around the clock."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="5,714" label="Judgments indexed" note="Supreme Court + high courts, post-clean corpus." />
            <MetricCard value="108k" label="Embedded chunks" note="voyage-4-large · 1024-dim · HNSW cosine." />
            <MetricCard value="96.7%" label="Recall@10" note="30-query self-recall probe on the live corpus, with cross-encoder rerank." />
            <MetricCard value="0.95" label="MRR" note="Correct hit almost always at rank 1 — mean rank 1.03." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2">
            <PitchCard
              icon={Users}
              title="Tenant-private by default"
              body="Your matter documents never leave your workspace for training. Separate from the public authority corpus."
            />
            <PitchCard
              icon={FileSearch}
              title="Grounded, not generated"
              body="Every substantive answer cites a named judgment, statute or internal precedent. Refusal beats fabrication."
            />
          </div>
        </Slide>

        <Slide
          id="contact"
          index="09"
          tone="ink"
          eyebrow="Contact"
          title="A 45-minute walkthrough, shaped to your sector."
          description="We set up a sandbox with a sample portfolio from your industry — banking, SaaS, pharma, infrastructure — and walk through outside-counsel spend, obligations and the audit export with your team."
          className="border-b-0"
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-8">
              <div className="text-xs font-semibold uppercase tracking-[0.2em] text-white/55">
                Direct contact
              </div>
              <a
                href={`mailto:${siteConfig.contact.founder}?subject=CaseOps%20for%20our%20legal%20team`}
                className="mt-4 inline-block font-display text-[2.25rem] font-normal leading-none tracking-tight text-white hover:text-white/85 md:text-[3rem]"
              >
                {siteConfig.contact.founder}
              </a>
              <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
                Write directly for a walkthrough, a sector-specific sandbox or a security
                and DPA conversation. Founder-led until we are larger.
              </p>
            </div>
            <PersonaSwitch active="gcs" />
          </div>
        </Slide>
      </main>
      <Footer />
    </>
  );
}
