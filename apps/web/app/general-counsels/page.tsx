import type { Metadata } from "next";
import {
  Activity,
  BadgeCheck,
  BookOpenText,
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
              <MetricCard inverse value="Audit export" label="Board preparation" note="Date-scoped records and retained activity history." />
              <MetricCard inverse value="Tenant-scoped" label="Access controls" note="Authorization is checked against the firm's records and permissions." />
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
          description="AI compresses 80 matters and 200 contracts into 'here is what is open, here is who said what, here is what is due next quarter' - with every number traceable to a source. Litigation intelligence stays source-backed, reviewable, and explicitly non-advisory."
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
              icon={GitBranch}
              title="Litigation Intelligence review"
              body="Proceeding directions, affidavit gaps, mock-hearing feedback, calibrated historical patterns, and knowledge-graph relationships appear with source links and review state."
            />
            <PitchCard
              icon={ShieldCheck}
              title="AI policy + ModelRun audit — shipped"
              body="Tenant-scoped tenant_ai_policy gate enforced at runtime on the structured-call path (matter summary, draft preview, recommendations, hearing pack). Every LLM call writes a ModelRun audit row with provider/model/tokens/latency/status — visible per matter."
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
                AI assistance is review-first: cause-list candidates, obligation-due
                suggestions, and intake triage stay behind human approval. Autonomous
                scoped-agent execution is planned, not live. Cross-tenant training is off by default.
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
            <PitchCard
              icon={Landmark}
              title="Outside-counsel portal — shipped"
              body="Every briefed firm gets a magic-link login at /portal/oc — see assigned matters, upload work product, submit invoices, log time. Scope-gated by MatterPortalGrant; the GC sees every action on the audit trail."
            />
            <PitchCard
              icon={ShieldCheck}
              title="Client portal + KYC — shipped"
              body="The client gets their own /portal view of the matter (Overview, Comms, Hearings, KYC tabs). KYC submit + GC review + audit on every state transition. Built on the same Phase C portal scaffold; no second auth system to operate."
            />
            <PitchCard
              icon={BookOpenText}
              title="Statutes attached to the matter"
              body="Attach available source-verified provisions to the matter and inspect their exact source version. Catalog coverage remains incomplete; unverified entries are not selectable as verified references."
            />
          </div>
          <div className="mt-8 grid gap-4 rounded-2xl border border-[var(--color-line)] bg-white p-6 md:grid-cols-[1fr_1fr] md:p-8">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                Board reporting
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-2)]">
                Review assigned matters, outside-counsel fees and budget use from the
                recorded portfolio. Keep the underlying invoices and activity history
                available for reconciliation.
              </p>
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand-600)]">
                Evidence limits
              </div>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-mute)]">
                Reports reflect the data entered and reconciled in the workspace.
                Missing invoices or activity records are not evidence of lower legal spend.
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
          description="Store contracts, review AI-extracted clauses, track obligations and compare against a playbook. Extraction depends on document quality and provider availability; review the source contract before relying on the result."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={FileSearch}
              title="Clause extraction"
              body="Review extracted parties, term, payment, confidentiality, IP, liability and other available clauses alongside the source contract. Missing or uncertain clauses require review."
            />
            <PitchCard
              icon={ClipboardCheck}
              title="Obligation tracker"
              body="Payment, reporting, notice, renewal and termination duties become tasks with due dates where the contract states them. Surfaces on the matter cockpit."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Playbook compare"
              body="A 15-rule default Indian commercial playbook seeds in one click. The OpenAI review model compares each clause against the expected position and flags matched / missing / deviation with severity."
            />
          </div>
        </Slide>

        <Slide
          id="risk"
          index="07"
          tone="ink"
          eyebrow="Risk, audit and AI posture"
          title="Control is built in, not bolted on."
          description="The standard a GC should expect: tenant isolation by construction, matter-level ethical walls, audit on sensitive actions, AI policy enforcement, malware-scan guardrails, and documented rotation runbooks. Enterprise SSO/SCIM, autonomous agents, and dedicated provider connectors remain planned or provider-gated until readiness evidence is complete."
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
                title="AI policy enforced at runtime"
                body="Tenant-scoped tenant_ai_policy gate runs on every structured AI call (matter summary, draft preview, recommendations, hearing pack). Blocked-model attempts return HTTP 403 with the specific model that was rejected, and a ModelRun audit row records the refusal."
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
          eyebrow="Research evidence"
          title="Sources you can inspect."
          description="Review the cited source and its available coverage. Corpus size and retrieval quality are different measures; a self-recall probe is not a guarantee of legal relevance."
        >
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard value="Source-linked" label="Judgment references" note="Open the cited authority and inspect its provenance." />
            <MetricCard value="Voyage" label="Embedding pipeline" note="Production retrieval uses voyage-4-large embeddings." />
            <MetricCard value="Reranked" label="Research results" note="Cross-encoder ranking supports source-based review." />
            <MetricCard value="Not certified" label="Corpus quality score" note="No representative legal-retrieval rating is claimed here." />
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-2">
            <PitchCard
              icon={Users}
              title="Tenant-private by default"
              body="Your matter documents never leave your workspace for training. Separate from the public authority corpus."
            />
            <PitchCard
              icon={FileSearch}
              title="Source-aware legal review"
              body="Inspect citations, source coverage and limitation notes before relying on generated work. Legal review remains necessary."
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
