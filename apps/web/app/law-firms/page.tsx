import type { Metadata } from "next";
import type { ComponentType, ReactNode } from "react";
import {
  BadgeCheck,
  BookOpen,
  Briefcase,
  Building2,
  Clock3,
  FileText,
  Gavel,
  Landmark,
  Lock,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
} from "lucide-react";

import { Logo } from "@/components/marketing/Logo";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { cn } from "@/lib/cn";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "Law Firms",
  description:
    "A 10-part sales pitch for litigation-heavy law firms evaluating CaseOps as their matter-native legal operating system.",
  alternates: { canonical: "/law-firms" },
  openGraph: {
    type: "website",
    url: `${siteConfig.url}/law-firms`,
    title: `For law firms - ${siteConfig.name}`,
    description:
      "See how CaseOps connects matter management, drafting, hearing prep, billing and control into one operating system for law firms.",
  },
};

const slides = [
  { id: "cover", label: "Cover" },
  { id: "problem", label: "Problem" },
  { id: "matter-os", label: "Matter OS" },
  { id: "drafting", label: "Drafting" },
  { id: "hearings", label: "Hearings" },
  { id: "platform", label: "Platform" },
  { id: "billing", label: "Billing" },
  { id: "control", label: "Control" },
  { id: "ai-angle", label: "AI angle" },
  { id: "contact", label: "Contact" },
] as const;

const fracturePoints = [
  {
    title: "Matters live in one place, the actual work in five others.",
    body: "Case files, research notes, orders, draft versions, calendars and billing systems drift apart the moment a matter becomes active.",
  },
  {
    title: "Partners review without a clean operational spine.",
    body: "The draft sits in one tool, authorities in another, and the hearing note in a chat thread. Review quality depends on who remembers what.",
  },
  {
    title: "Institutional memory disappears between matters.",
    body: "The firm's strongest arguments, prior positions and practical playbooks are rarely structured enough to be reused on demand.",
  },
  {
    title: "Revenue systems do not reflect the legal workflow.",
    body: "Time, invoices and collections usually sit outside the matter, so real profitability and team discipline arrive late.",
  },
] as const;

const matterCapabilities = [
  "Parties, forum, stage and next hearing in one cockpit",
  "Documents, drafts and hearing packs tied to the same record",
  "Team scoping, ethical walls and audit at matter level",
  "Research, recommendations and billing anchored to live facts",
] as const;

const draftingFlow = [
  "Start from the matter record, not a blank document.",
  "Retrieve statutes, judgments and internal precedents against the issue.",
  "Generate a first draft with inline citations, assumptions and missing facts.",
  "Route it through reviewer sign-off before it becomes operational output.",
] as const;

const hearingFlow = [
  "Chronology assembled from the matter timeline",
  "Last effective order surfaced without manual digging",
  "Bench brief and oral points compiled into a repeatable pack",
  "Cause-list and listing awareness feeding the next action",
] as const;

const platformMoves = [
  {
    icon: FileText,
    title: "Contracts and playbooks",
    body: "Upload, compare against playbooks, surface deviations, and move obligations back into the matter graph.",
  },
  {
    icon: Search,
    title: "Research and knowledge reuse",
    body: "Search the public corpus and tenant-private annotations without leaving the operating workflow.",
  },
  {
    icon: Briefcase,
    title: "Outside counsel coordination + portal — shipped",
    body: "Manage counsel briefs, budgets and spend on the same matter portfolio. Briefed counsel get a magic-link login at /portal/oc — assigned matters, work-product upload, invoice submission, time entries — gated by MatterPortalGrant with audit on every action.",
  },
  {
    icon: ShieldCheck,
    title: "Client portal + KYC — shipped",
    body: "Each client gets their own /portal view of the matter with Comms, Hearings and KYC tabs. Magic-link auth on a separate cookie scope; matter-grant scoping; full audit trail on KYC + reply state.",
  },
  {
    icon: Users,
    title: "Team visibility",
    body: "Partners, associates and legal ops work from the same matter truth instead of status being rebuilt in meetings.",
  },
  {
    icon: BookOpen,
    title: "Institutional memory",
    body: "Strong prior arguments, preferred clauses and review patterns become reusable assets, not tribal knowledge.",
  },
  {
    icon: Building2,
    title: "Firm-wide operating discipline",
    body: "The product is designed to run across litigation, advisory, contract and portfolio workflows without changing systems.",
  },
] as const;

const trustLayers = [
  "Tenant isolation at query and storage layer",
  "Matter-level ethical walls that override broad role access",
  "Audit on sensitive actions, exports and AI runs",
  "Scoped, review-required AI workflows for legal output",
  "Signed access patterns for private documents and attachments",
  "Configurable workspace contact, ownership and oversight",
] as const;

export default function LawFirmPitchPage() {
  return (
    <>
      <SkipLink />
      <PitchHeader />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <Slide
          id="cover"
          index="01"
          tone="ink"
          eyebrow="CaseOps for law firms"
          title="The operating system for litigation-heavy law firms."
          description="CaseOps turns scattered files, research tabs, draft folders, hearing notes and billing workflows into one matter-native system of work."
        >
          <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
            <div className="max-w-2xl">
              <div className="flex flex-wrap gap-3">
                <Badge tone="brand">Built for Indian legal workflows</Badge>
                <Badge className="border-white/20 bg-white/10 text-white">Live at caseops.ai</Badge>
              </div>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-white/78">
                One workspace for matters, research, drafting, hearing preparation, contracts,
                outside counsel and billing, with control surfaces that legal teams can trust.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button href={`mailto:${siteConfig.contact.founder}`} size="lg">
                  Contact Sanjeev
                </Button>
                <Button
                  href={siteConfig.url}
                  size="lg"
                  variant="outline"
                  target="_blank"
                  rel="noreferrer"
                  className="border-white/20 bg-white/10 text-white hover:bg-white/15 hover:text-white"
                >
                  Open live site
                </Button>
              </div>
              <div className="mt-8 grid gap-3 sm:grid-cols-3">
                <MetricCard label="System" value="Matter-native" />
                <MetricCard label="Output" value="Cited legal work" />
                <MetricCard label="Control" value="Audit + review" />
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <PitchCard
                icon={Scale}
                title="Matter cockpit"
                body="Parties, forum, stage, documents, deadlines and the next hearing in one operating view."
                className="md:translate-y-10"
                inverse
              />
              <PitchCard
                icon={Sparkles}
                title="Drafting studio"
                body="Grounded first drafts with inline citations, assumptions and missing-fact placeholders."
                inverse
              />
              <PitchCard
                icon={Gavel}
                title="Hearing pack"
                body="Chronology, last order, bench brief and oral points assembled from the matter record."
                inverse
              />
              <PitchCard
                icon={Wallet}
                title="Billing and recovery"
                body="Time, invoice approval and payment links tied back to the same matter economics."
                className="md:-translate-y-10"
                inverse
              />
            </div>
          </div>
        </Slide>

        <Slide
          id="problem"
          index="02"
          tone="light"
          eyebrow="The problem"
          title="Most firms do not have a legal stack. They have fragments."
          description="The issue is not a lack of tools. It is that the tools do not share the same operational truth."
        >
          <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="grid gap-4 md:grid-cols-2">
              {fracturePoints.map((point) => (
                <PitchCard key={point.title} title={point.title} body={point.body} />
              ))}
            </div>
            <div className="rounded-[2rem] border border-[var(--color-line)] bg-[linear-gradient(180deg,rgba(15,23,42,0.98),rgba(15,23,42,0.88))] p-8 text-white shadow-[var(--shadow-soft)]">
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-white/55">
                What firms pay for
              </div>
              <div className="mt-6 grid gap-4">
                <ReviewRow
                  icon={Clock3}
                  title="Context switching"
                  body="Associates rebuild the state of the matter every time they change workflows."
                  inverse
                />
                <ReviewRow
                  icon={BadgeCheck}
                  title="Review friction"
                  body="Partners review a draft without the whole chain of facts, authorities and hearing context."
                  inverse
                />
                <ReviewRow
                  icon={Landmark}
                  title="Deadline risk"
                  body="Orders, listings and team ownership fall through gaps between systems."
                  inverse
                />
                <ReviewRow
                  icon={Wallet}
                  title="Late commercial visibility"
                  body="Revenue tracking arrives after legal work, instead of guiding it in real time."
                  inverse
                />
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="matter-os"
          index="03"
          tone="brand"
          eyebrow="The operating spine"
          title="Everything hangs off the matter."
          description="CaseOps uses the matter as the unit of legal work, so documents, drafts, hearings, teams and billing stay attached to one live record."
        >
          <div className="grid gap-8 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <div className="grid gap-4 sm:grid-cols-2">
              <MatterNode title="Parties" body="Claimants, respondents, counsel and role context." />
              <MatterNode title="Documents" body="Orders, pleadings, annexures and evidence with indexing state." />
              <MatterNode title="Hearings" body="Listings, chronology, last order and hearing packs." />
              <MatterNode title="Billing" body="Time entries, invoices, collections and payment state." />
            </div>
            <div className="rounded-[2rem] border border-[var(--color-line)] bg-white p-8 shadow-[var(--shadow-soft)]">
              <div className="inline-flex rounded-full border border-[var(--color-brand-100)] bg-[var(--color-brand-50)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-brand-700)]">
                Matter cockpit
              </div>
              <h3 className="mt-5 font-display text-3xl font-normal tracking-tight text-[var(--color-ink)]">
                The same record powers every workflow.
              </h3>
              <div className="mt-6 grid gap-4 md:grid-cols-2">
                {matterCapabilities.map((capability) => (
                  <div
                    key={capability}
                    className="rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-sm leading-relaxed text-[var(--color-ink-2)]"
                  >
                    {capability}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="drafting"
          index="04"
          tone="light"
          eyebrow="Research + drafting"
          title="Draft faster without giving up accountability."
          description="The goal is not to produce unverifiable text faster. The goal is to produce reviewable legal work anchored to sources and the matter record."
        >
          <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="rounded-[2rem] border border-[var(--color-line)] bg-[var(--color-ink)] p-8 text-white shadow-[var(--shadow-soft)]">
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-white/55">
                How the drafting loop works
              </div>
              <div className="mt-6 space-y-4">
                {draftingFlow.map((step, index) => (
                  <div
                    key={step}
                    className="flex gap-4 rounded-2xl border border-white/10 bg-white/5 p-4"
                  >
                    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/15 bg-white/10 text-sm font-semibold">
                      {index + 1}
                    </span>
                    <p className="text-sm leading-relaxed text-white/82">{step}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <PitchCard
                icon={BookOpen}
                title="Authorities attached"
                body="Substantive output is grounded in statutes, judgments and internal precedents, not free-floating model guesses."
              />
              <PitchCard
                icon={BadgeCheck}
                title="Reviewer-first design"
                body="Assumptions, missing facts and citation trails are visible so senior lawyers can judge output quickly and defensibly."
              />
              <PitchCard
                icon={Sparkles}
                title="Bench-aware appeal drafting — shipped"
                body="When the matter has an upcoming listing, the appeal-memorandum draft pulls authorities authored by THAT specific bench (court-scoped via the resolver) and prefers ones aligned with the matter's practice area. No win/lose copy; advocate-bias citation selection."
              />
              <PitchCard
                icon={BookOpen}
                title="Statute model + verbatim quoting — shipped"
                body="7 central acts catalogued (BNSS / BNS / BSA / CrPC / IPC / Constitution / NI Act, 91 sections). Attach sections to a matter as cited / opposing / context; the prompt receives bare text and quotes verbatim."
              />
              <PitchCard
                icon={Lock}
                title="Refusal over fabrication"
                body="Weak evidence and absent facts should produce a refusal or a placeholder, not a polished hallucination."
              />
            </div>
          </div>
        </Slide>

        <Slide
          id="hearings"
          index="05"
          tone="brand"
          eyebrow="Hearing readiness"
          title="Turn hearing preparation into a repeatable system."
          description="The team should not rebuild chronology, last order context and oral points by hand on the morning of a listing."
        >
          <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="grid gap-4">
              {hearingFlow.map((item) => (
                <div
                  key={item}
                  className="rounded-2xl border border-[var(--color-line)] bg-white p-5 text-sm leading-relaxed text-[var(--color-ink-2)] shadow-[var(--shadow-soft)]"
                >
                  {item}
                </div>
              ))}
            </div>
            <div className="rounded-[2rem] border border-[var(--color-line)] bg-[linear-gradient(180deg,#111827,#1f2937)] p-8 text-white shadow-[var(--shadow-soft)]">
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-white/55">
                What the team walks into court with
              </div>
              <div className="mt-6 space-y-4">
                <ReviewRow
                  icon={Gavel}
                  title="Bench brief"
                  body="Short court-ready context, current posture and the decision the team is asking for."
                  inverse
                />
                <ReviewRow
                  icon={FileText}
                  title="Chronology"
                  body="A defensible timeline assembled from filings, orders and matter activity."
                  inverse
                />
                <ReviewRow
                  icon={Scale}
                  title="Oral points"
                  body="The key propositions and supporting authorities, assembled into a usable hearing pack."
                  inverse
                />
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="platform"
          index="06"
          tone="light"
          eyebrow="Platform breadth"
          title="Run more of the practice in the same system."
          description="CaseOps is designed to keep adjacent legal workflows attached to the matter graph instead of forcing the firm back into disconnected tools."
        >
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {platformMoves.map((item) => (
              <PitchCard
                key={item.title}
                icon={item.icon}
                title={item.title}
                body={item.body}
              />
            ))}
          </div>
        </Slide>

        <Slide
          id="billing"
          index="07"
          tone="ink"
          eyebrow="Commercial discipline"
          title="Work and revenue live together."
          description="Legal teams should not finish the work and only then discover whether the matter was properly captured, billed and collected."
        >
          <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
            <div className="rounded-[2rem] border border-white/10 bg-white/5 p-8 shadow-[var(--shadow-soft)]">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.22em] text-white/55">
                    Billing path
                  </div>
                  <h3 className="mt-3 font-display text-3xl font-normal tracking-tight text-white">
                    Time -&gt; invoice -&gt; payment link -&gt; recovery
                  </h3>
                </div>
                <Wallet className="h-10 w-10 text-white/80" />
              </div>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <MetricCard label="Capture" value="Time + expense" inverse />
                <MetricCard label="Dispatch" value="Invoice workflow" inverse />
                <MetricCard label="Settlement" value="Pine Labs link" inverse />
              </div>
            </div>
            <div className="grid gap-4">
              <PitchCard
                icon={Clock3}
                title="Timekeeping inside the matter"
                body="Capture effort where work actually happens, instead of asking the team to reconstruct it later."
                inverse
              />
              <PitchCard
                icon={FileText}
                title="Invoice approval and dispatch"
                body="Billing states are visible, traceable and auditable from the same record used for legal work."
                inverse
              />
              <PitchCard
                icon={Wallet}
                title="Collections visibility"
                body="Payment state, partial recovery and write-off posture are visible without leaving the platform."
                inverse
              />
            </div>
          </div>
        </Slide>

        <Slide
          id="control"
          index="08"
          tone="brand"
          eyebrow="Trust and control"
          title="Control is built in, not bolted on."
          description="For law firms, product quality is not only speed. It is whether the system preserves boundaries, ownership and reviewer accountability."
        >
          <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <div className="grid gap-3">
              {trustLayers.map((layer) => (
                <div
                  key={layer}
                  className="rounded-2xl border border-[var(--color-line)] bg-white p-4 text-sm leading-relaxed text-[var(--color-ink-2)] shadow-[var(--shadow-soft)]"
                >
                  {layer}
                </div>
              ))}
            </div>
            <div className="rounded-[2rem] border border-[var(--color-line)] bg-[var(--color-ink)] p-8 text-white shadow-[var(--shadow-soft)]">
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-white/55">
                Review-required legal AI
              </div>
              <div className="mt-6 grid gap-4">
                <ReviewRow
                  icon={ShieldCheck}
                  title="Scoped access"
                  body="The system acts inside tenant and matter boundaries, not with broad, invisible privilege."
                  inverse
                />
                <ReviewRow
                  icon={BadgeCheck}
                  title="Acceptances are explicit"
                  body="Recommendations and draft approvals are tracked actions with ownership, not silent automation."
                  inverse
                />
                <ReviewRow
                  icon={Lock}
                  title="Legal outputs stay accountable"
                  body="The workflow is designed so a firm can justify what was used, what was reviewed and who accepted it."
                  inverse
                />
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="ai-angle"
          index="09"
          tone="light"
          eyebrow="The AI angle"
          title="AI as associate leverage, not as an autopilot."
          description="AI is a feature of the system, not the product. Legal knowledge stays in retrieval and source systems — statutes, judgments, your own precedents — not baked into model weights. Every substantive output is grounded in a named source; uncertainty renders as a refusal or a placeholder, not a polished hallucination."
        >
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <PitchCard
              icon={Sparkles}
              title="Drafting Studio"
              body="Produces a first draft from the matter record with inline citations to named judgments. Refuses to cite what it cannot ground."
            />
            <PitchCard
              icon={Search}
              title="Grounded research"
              body="voyage-4-large embeddings + HNSW + cross-encoder reranker return results with source links and cosine-strength."
            />
            <PitchCard
              icon={BadgeCheck}
              title="Explainable recommendations"
              body="Forum, authorities and next-best-action come with rationale, assumptions, missing facts, and a confidence label."
            />
            <PitchCard
              icon={Lock}
              title="Refusal over fabrication"
              body="Missing facts render as [____] placeholders. Out-of-corpus queries return an explicit no-result."
            />
          </div>

          <div className="mt-8 rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)] md:p-8">
            <div className="grid gap-5 md:grid-cols-[1.1fr_0.9fr] md:items-center">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-brand-600)]">
                  The partner's payoff
                </div>
                <p className="mt-3 text-[15.5px] leading-relaxed text-[var(--color-ink-2)]">
                  A junior who used to spend 3 hours on a first draft plus 2 hours chasing
                  citations gets a grounded draft in 10 minutes. The partner's review
                  becomes the actual legal work — not clerical assembly. Citation
                  discipline stays stricter than before, because the reviewer-findings
                  block catches BNS vs BNSS, uncited claims and fact gaps before the draft
                  leaves chambers.
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-[13.5px] leading-relaxed text-[var(--color-mute)]">
                <span className="font-semibold text-[var(--color-ink-2)]">Agentic scope:</span>{" "}
                today, four narrow agents — cause-list watcher, corpus ingest, structured
                extraction, document retry. Coming in Sprint I: Grantex trust plane +
                Temporal-durable filing-deadline, obligation, and intake-triage agents.
                Substantive legal judgment is always a human step. Outbound actions
                (filings, payments, client communications) default to human approval.
              </div>
            </div>
          </div>
        </Slide>

        <Slide
          id="contact"
          index="10"
          tone="ink"
          eyebrow="Contact"
          title="If the goal is to run the whole firm on one system, start here."
          description="Founder-led conversations for law firm pilots, strategic walkthroughs and deployment planning."
          className="border-b-0"
        >
          <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-end">
            <div className="rounded-[2rem] border border-white/10 bg-white/5 p-8 shadow-[var(--shadow-soft)]">
              <div className="text-sm uppercase tracking-[0.2em] text-white/55">
                Direct contact
              </div>
              <a
                href={`mailto:${siteConfig.contact.founder}`}
                className="mt-4 inline-block font-display text-[2.6rem] font-normal leading-none tracking-tight text-white hover:text-white/85 md:text-[3.5rem]"
              >
                {siteConfig.contact.founder}
              </a>
              <p className="mt-4 max-w-xl text-base leading-relaxed text-white/75">
                Write directly for a live walkthrough of the platform, law-firm pilot discussions
                or a founder-level conversation about how the operating model fits your practice.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button href={`mailto:${siteConfig.contact.founder}`} size="lg">
                  Contact us
                </Button>
                <Button
                  href={siteConfig.url}
                  size="lg"
                  variant="outline"
                  target="_blank"
                  rel="noreferrer"
                  className="border-white/20 bg-white/10 text-white hover:bg-white/15 hover:text-white"
                >
                  Visit caseops.ai
                </Button>
              </div>
            </div>

            <div className="grid gap-4">
              <PitchCard
                icon={Users}
                title="For litigation-heavy firms"
                body="A stronger operating system for firms where matters, hearings and drafting drive the workload."
                inverse
              />
              <PitchCard
                icon={Landmark}
                title="For growth-stage partnerships"
                body="Get operational visibility without turning legal work into generic workflow software."
                inverse
              />
              <PitchCard
                icon={ShieldCheck}
                title="For teams that need control"
                body="Review, audit and access boundaries remain visible even as the product becomes more capable."
                inverse
              />
            </div>
          </div>
        </Slide>
      </main>
    </>
  );
}

function PitchHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-line)] bg-white/90 backdrop-blur">
      <Container className="flex min-h-16 items-center justify-between gap-6 py-3">
        <div className="flex min-w-0 items-center gap-4">
          <Logo />
          <span className="hidden text-sm text-[var(--color-mute)] md:inline">
            Law firm pitch
          </span>
        </div>

        <nav aria-label="Pitch sections" className="hidden items-center gap-5 lg:flex">
          {slides.map((slide) => (
            <a
              key={slide.id}
              href={`#${slide.id}`}
              className="text-sm text-[var(--color-mute)] transition-colors hover:text-[var(--color-ink)]"
            >
              {slide.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Button href="/" variant="ghost" size="sm">
            Home
          </Button>
          <Button href={`mailto:${siteConfig.contact.founder}`} size="sm">
            Contact us
          </Button>
        </div>
      </Container>
    </header>
  );
}

function Slide({
  id,
  index,
  eyebrow,
  title,
  description,
  tone,
  className,
  children,
}: {
  id: string;
  index: string;
  eyebrow: string;
  title: string;
  description: string;
  tone: "light" | "ink" | "brand";
  className?: string;
  children: ReactNode;
}) {
  const isDark = tone === "ink";

  return (
    <section
      id={id}
      className={cn(
        "relative overflow-hidden border-b border-[var(--color-line)]",
        tone === "light" && "bg-white",
        tone === "ink" && "bg-[linear-gradient(180deg,#0f172a,#111827)] text-white",
        tone === "brand" &&
          "bg-[radial-gradient(circle_at_top,rgba(99,102,241,0.16),transparent_35%),linear-gradient(180deg,#f8fafc,#eef2ff)]",
        className,
      )}
    >
      <Container className="relative grid min-h-[88svh] content-center gap-10 py-16 md:min-h-[92svh] md:py-24">
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute right-0 top-6 font-display text-[6rem] leading-none tracking-tight md:text-[10rem]",
            isDark ? "text-white/6" : "text-[var(--color-ink)]/5",
          )}
        >
          {index}
        </div>

        <div className="relative max-w-3xl">
          <div
            className={cn(
              "text-xs font-semibold uppercase tracking-[0.24em]",
              isDark ? "text-white/55" : "text-[var(--color-brand-700)]",
            )}
          >
            {eyebrow}
          </div>
          <h1
            className={cn(
              "mt-4 font-display text-4xl font-normal leading-[1.03] tracking-tight md:text-[4.5rem]",
              isDark ? "text-white" : "text-[var(--color-ink)]",
            )}
          >
            {title}
          </h1>
          <p
            className={cn(
              "mt-5 max-w-2xl text-lg leading-relaxed md:text-xl",
              isDark ? "text-white/76" : "text-[var(--color-mute)]",
            )}
          >
            {description}
          </p>
        </div>

        <div className="relative">{children}</div>
      </Container>
    </section>
  );
}

function PitchCard({
  title,
  body,
  icon: Icon,
  className,
  inverse = false,
}: {
  title: string;
  body: string;
  icon?: ComponentType<{ className?: string }>;
  className?: string;
  inverse?: boolean;
}) {
  return (
    <article
      className={cn(
        "rounded-[1.75rem] border p-6 shadow-[var(--shadow-soft)]",
        inverse
          ? "border-white/10 bg-white/5 text-white"
          : "border-[var(--color-line)] bg-white text-[var(--color-ink)]",
        className,
      )}
    >
      {Icon ? (
        <div
          className={cn(
            "inline-flex h-11 w-11 items-center justify-center rounded-2xl border",
            inverse
              ? "border-white/10 bg-white/10 text-white"
              : "border-[var(--color-brand-100)] bg-[var(--color-brand-50)] text-[var(--color-brand-700)]",
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
      ) : null}
      <h3
        className={cn(
          "mt-4 text-lg font-semibold tracking-tight",
          inverse ? "text-white" : "text-[var(--color-ink)]",
        )}
      >
        {title}
      </h3>
      <p
        className={cn(
          "mt-3 text-sm leading-relaxed",
          inverse ? "text-white/74" : "text-[var(--color-mute)]",
        )}
      >
        {body}
      </p>
    </article>
  );
}

function MatterNode({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[1.75rem] border border-[var(--color-line)] bg-white p-5 shadow-[var(--shadow-soft)]">
      <div className="text-sm font-semibold tracking-tight text-[var(--color-ink)]">{title}</div>
      <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">{body}</p>
    </div>
  );
}

function ReviewRow({
  icon: Icon,
  title,
  body,
  inverse = false,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  body: string;
  inverse?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div
        className={cn(
          "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border",
          inverse
            ? "border-white/10 bg-white/10 text-white"
            : "border-[var(--color-brand-100)] bg-[var(--color-brand-50)] text-[var(--color-brand-700)]",
        )}
      >
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div
          className={cn(
            "text-base font-semibold tracking-tight",
            inverse ? "text-white" : "text-[var(--color-ink)]",
          )}
        >
          {title}
        </div>
        <p
          className={cn(
            "mt-1 text-sm leading-relaxed",
            inverse ? "text-white/74" : "text-[var(--color-mute)]",
          )}
        >
          {body}
        </p>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: string;
  inverse?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
      <div className="text-xs uppercase tracking-[0.2em] text-white/48">{label}</div>
      <div className="mt-2 text-lg font-semibold tracking-tight text-white">{value}</div>
    </div>
  );
}
