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
  MessageSquare,
  ScrollText,
  ShieldCheck,
  Smartphone,
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
  title: "Legal operations software for Indian in-house teams",
  description:
    "CaseOps connects matters, contracts and redlines, outside counsel, spend, trade mark portfolios and review evidence for Indian in-house legal teams.",
  alternates: { canonical: "/general-counsels" },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}/general-counsels`,
    title: `Legal operations software for Indian in-house teams - ${siteConfig.name}`,
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
          headingLevel={1}
          index="01"
          tone="ink"
          eyebrow="CaseOps for general counsels"
          title="Legal operations for in-house teams in India."
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
                href="/demo/general-counsels"
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
          title="A shared record for legal-team coordination."
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
          description="Review supported matter and contract workflows, records and dates in context. AI output depends on permitted sources, coverage and plan limits; it requires human verification and is not legal advice."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={FileSearch}
              title="Contract → obligation — shipped"
              body="Review extracted parties, covenants, payment terms, consent clauses and audit rights, plus any derived tasks or dates, against the contract. Extraction may omit duties or misread terms; check missing and uncertain fields before relying on them."
            />
            <PitchCard
              icon={Activity}
              title="Portfolio rollups"
              body="Review available matter summaries and portfolio records together. Per-line provenance is not guaranteed; verify generated statements against their matter records and supporting documents before board use."
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
                  What the GC can answer (illustrative figures)
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
              body="Intake, active, on hold, disposed — with forum, court, next hearing and tags in one row per matter."
            />
            <PitchCard
              icon={Activity}
              title="Live stage + next action"
              body="No more 'last update on Tuesday'. The cockpit reflects state the moment anyone records an event."
            />
            <PitchCard
              icon={GitBranch}
              title="Team scope and walls"
              body="Teams with leads can scope matter visibility, so colleagues see their teams' matters plus firm-wide ones. Restrict a sensitive matter or wall off a conflicted person without reshuffling roles; workspace owners always see everything."
            />
            <PitchCard
              icon={Landmark}
              title="Trade mark and patent portfolio"
              body="List, grid, family and deadline-tracker views, renewals chased against recorded client instructions, and client-safe IP reports. Registry data is entered or imported; there is no live IP India or WIPO feed. Added to a plan on request."
            />
            <PitchCard
              icon={MessageSquare}
              title="Ask this Workspace"
              body="Ask factual questions about the matters, IP records and documents you may see; answers cite the exact record, and opening a citation rechecks access and is audited. Off until the workspace owner enables it. Not legal advice."
            />
            <PitchCard
              icon={Smartphone}
              title="On a phone"
              body="The web app works in a phone or tablet browser. A native iOS and Android app is a development candidate, not yet in the App Store or Google Play."
            />
          </div>
        </Slide>

        <Slide
          id="counsel"
          index="05"
          tone="light"
          eyebrow="Outside counsel"
          title="Brief, budget and measure — without a spreadsheet."
          description="Outside counsel becomes a first-class workspace. Assign a matter to a firm with a budget ceiling, log spend against it, and review the firm's invoices and work product in one place."
        >
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            <PitchCard
              icon={Briefcase}
              title="Counsel panel"
              body="Profiles, contacts, practice areas, jurisdictions and panel status, kept with the matters each firm is assigned to."
            />
            <PitchCard
              icon={Wallet}
              title="Budget per assignment"
              body="Set a budget ceiling on each assignment and log spend against it as submitted, approved, partly approved, disputed or paid."
            />
            <PitchCard
              icon={Activity}
              title="Spend by firm"
              body="See approved and paid spend per counsel from the records you log. The view covers only what has been entered."
            />
            <PitchCard
              icon={Landmark}
              title="Outside-counsel portal — shipped"
              body="Briefed counsel sign in with an emailed link and see only their assigned matters. They upload work product, submit invoices and log time; files are scanned before your team sees them, and invoices arrive for review."
            />
            <PitchCard
              icon={ShieldCheck}
              title="Client portal + KYC — shipped"
              body="Clients sign in with an emailed link and see only what you share: matters (Overview, Comms, Hearings, KYC) and IP records with approved publications. They reply, submit KYC and send instructions for your acknowledgement, with audit on every state change."
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
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
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
              body="A partner or admin installs a 15-position default playbook for Indian commercial contracts. After clause extraction, a review model marks each position matched, deviation or missing, with severity. Review each finding against the contract."
            />
            <PitchCard
              icon={GitBranch}
              title="Counterparty redlines"
              body="Open a counterparty's Word mark-up to list insertions, deletions, moved passages and formatting changes by author. A warning appears when the file holds tracked changes the viewer cannot display; accept or reject changes in Word."
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
                body="A walled person, admins included, gets 'not found' on every list, search and detail view, and the attempt is audited. Workspace owners always keep access."
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
              body="Tenant-private documents are access-controlled separately from the public authority corpus. Review the configured model providers and data-processing terms before sending confidential material to AI workflows."
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
          description="Discuss the supported workflows for your team. Any walkthrough, sample workspace, security review and pilot terms require separate confirmation."
          className="border-b-0"
        >
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-8">
              <div className="text-xs font-semibold uppercase tracking-[0.2em] text-white/55">
                Direct contact
              </div>
              <a
                href="/demo/general-counsels"
                className="mt-4 inline-block font-display text-[2.25rem] font-normal leading-none tracking-tight text-white hover:text-white/85 md:text-[3rem]"
              >
                Request a conversation
              </a>
              <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
                Request a walkthrough or a security and DPA conversation. Availability,
                workspace scope and commercial terms are confirmed separately.
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
