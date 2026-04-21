import type { Metadata } from "next";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "User guide",
  description:
    "The CaseOps user guide. How to onboard a team, open and work a matter, draft with citations, run hearings, manage contracts and invoices, and use recommendations safely.",
  alternates: { canonical: "/guide" },
  openGraph: {
    type: "article",
    url: `${siteConfig.url}/guide`,
    title: `User guide — ${siteConfig.name}`,
    description:
      "Every workflow in CaseOps, end-to-end — for partners, associates, general counsel and legal ops.",
  },
};

const sections: { id: string; title: string }[] = [
  { id: "getting-started", title: "Getting started" },
  { id: "workspace", title: "Workspace and roles" },
  { id: "matters", title: "Opening and running a matter" },
  { id: "documents", title: "Documents and indexing" },
  { id: "drafting", title: "Drafting with citations" },
  { id: "hearings", title: "Hearing preparation" },
  { id: "research", title: "Research and authorities" },
  { id: "contracts", title: "Contracts and playbooks" },
  { id: "recommendations", title: "Recommendations" },
  { id: "outside-counsel", title: "Outside counsel and spend" },
  { id: "billing", title: "Billing, invoices and payments" },
  { id: "admin", title: "Admin, audit and ethical walls" },
  { id: "security", title: "Security and data boundaries" },
  { id: "troubleshooting", title: "Troubleshooting" },
  { id: "glossary", title: "Glossary" },
];

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-[var(--color-line)] pt-10">
      <h2 className="font-display text-2xl font-normal leading-tight tracking-tight text-[var(--color-ink)] md:text-[2rem]">
        {title}
      </h2>
      <div className="prose-guide mt-6 space-y-4 text-[15.5px] leading-[1.75] text-[var(--color-ink-2)]">
        {children}
      </div>
    </section>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center rounded border border-[var(--color-line)] bg-[var(--color-bg-2)] px-1.5 py-0.5 font-mono text-[11.5px] font-medium text-[var(--color-ink-2)]">
      {children}
    </kbd>
  );
}

function Callout({
  tone = "neutral",
  title,
  children,
}: {
  tone?: "neutral" | "warn" | "ok";
  title: string;
  children: React.ReactNode;
}) {
  const toneCls =
    tone === "warn"
      ? "border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/[0.04]"
      : tone === "ok"
      ? "border-[var(--color-success-500)]/40 bg-[var(--color-success-500)]/[0.04]"
      : "border-[var(--color-line)] bg-[var(--color-bg)]";
  return (
    <aside
      className={`mt-4 rounded-lg border ${toneCls} p-4 text-[14px] leading-relaxed`}
      role="note"
    >
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
        {title}
      </div>
      <div className="mt-1 text-[var(--color-ink-2)]">{children}</div>
    </aside>
  );
}

function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="mt-4 space-y-3">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3">
          <span
            aria-hidden
            className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-ink)] font-mono text-[11px] font-semibold text-white tabular-nums"
          >
            {i + 1}
          </span>
          <div className="flex-1 leading-relaxed">{it}</div>
        </li>
      ))}
    </ol>
  );
}

export default function GuidePage() {
  return (
    <>
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] pb-14 pt-16 md:pb-16 md:pt-20">
          <Container>
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-brand-600)]">
              User guide · v1 · 2026
            </span>
            <h1 className="mt-3 max-w-4xl font-display text-4xl font-normal leading-[1.1] tracking-tight text-[var(--color-ink)] md:text-[3.25rem]">
              How to run your practice on CaseOps.
            </h1>
            <p className="mt-5 max-w-2xl text-[17px] leading-relaxed text-[var(--color-mute)]">
              A linear, end-to-end read for partners, associates, general counsel and legal
              ops. Fifteen sections. Read front to back the first time; return for the
              section that matches the task in front of you after that.
            </p>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-[var(--color-ink-2)]">
              <span>
                <span className="font-mono text-[var(--color-mute-2)]">Audience</span>{" "}
                Litigation partners · GCs · legal ops · solos
              </span>
              <span>
                <span className="font-mono text-[var(--color-mute-2)]">Reading time</span>{" "}
                ~35 min
              </span>
              <span>
                <span className="font-mono text-[var(--color-mute-2)]">Updated</span>{" "}
                19 Apr 2026
              </span>
            </div>
          </Container>
        </header>

        <Container className="py-16">
          <div className="grid gap-12 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-16">
            <nav
              aria-label="Contents"
              className="top-24 hidden self-start lg:sticky lg:block"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
                Contents
              </div>
              <ol className="mt-3 space-y-1.5 text-[13.5px]">
                {sections.map((s, i) => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      className="group flex gap-3 rounded-md px-2 py-1 text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] hover:text-[var(--color-ink)]"
                    >
                      <span className="font-mono text-[11px] tabular-nums text-[var(--color-mute-2)]">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="leading-snug">{s.title}</span>
                    </a>
                  </li>
                ))}
              </ol>
            </nav>

            <div className="min-w-0">
              <details className="mb-10 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4 lg:hidden">
                <summary className="cursor-pointer text-sm font-semibold text-[var(--color-ink)]">
                  Contents
                </summary>
                <ol className="mt-3 space-y-1.5 text-[13.5px] text-[var(--color-ink-2)]">
                  {sections.map((s, i) => (
                    <li key={s.id}>
                      <a href={`#${s.id}`}>
                        <span className="font-mono tabular-nums text-[var(--color-mute-2)]">
                          {String(i + 1).padStart(2, "0")}
                        </span>{" "}
                        {s.title}
                      </a>
                    </li>
                  ))}
                </ol>
              </details>

              <article className="max-w-[72ch] space-y-16">
                <Section id="getting-started" title="1 · Getting started">
                  <p>
                    CaseOps is a workspace for running a legal practice end to end — matters,
                    documents, drafting, hearings, contracts, outside counsel, billing, and
                    the audit trail that ties them together. You land on the <strong>home
                    dashboard</strong> after sign in; everything else is one keystroke away
                    from the command bar (<Kbd>⌘</Kbd> <Kbd>K</Kbd> or <Kbd>Ctrl</Kbd>{" "}
                    <Kbd>K</Kbd>).
                  </p>
                  <Steps
                    items={[
                      <>
                        <strong>Create a workspace.</strong> Visit{" "}
                        <a className="underline" href="/sign-in">/sign-in</a>, pick{" "}
                        <em>New workspace</em>, and enter your firm or company name. You
                        become the first admin.
                      </>,
                      <>
                        <strong>Invite colleagues.</strong> From <em>Admin → Members</em>,
                        send invitations with a role — Partner, Associate, General Counsel,
                        Legal Ops or Reviewer.
                      </>,
                      <>
                        <strong>Verify the brand.</strong> Add your firm logo and a default
                        contact email so draft dispatches and invoices carry them.
                      </>,
                      <>
                        <strong>Open your first matter.</strong> Skip to section 3 if you are
                        ready, or continue through sections 2 and 3 together for context.
                      </>,
                    ]}
                  />
                  <Callout title="New to matter-graph systems?">
                    A matter is the unit of work. Documents, drafts, hearings, invoices and
                    activity all hang off a matter. You do not keep drafts in a folder and
                    hearings in a calendar — the matter is the folder <em>and</em> the
                    calendar.
                  </Callout>
                </Section>

                <Section id="workspace" title="2 · Workspace and roles">
                  <p>
                    Every workspace is an isolated tenant. Data never crosses tenant
                    boundaries — the query layer, storage layer and audit trail all filter
                    by tenant id. Users inside a workspace see what their role permits, and
                    matter-level ethical walls can further restrict access below that.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    Roles at a glance
                  </h3>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Admin.</strong> Full access. Manages members, teams, billing
                      settings, AI policy and audit exports.
                    </li>
                    <li>
                      <strong>Partner.</strong> Owns matters; approves drafts; signs off
                      recommendations; sees team-wide portfolios.
                    </li>
                    <li>
                      <strong>Associate.</strong> Opens and works matters; produces drafts;
                      compiles hearing packs; requests approvals.
                    </li>
                    <li>
                      <strong>General Counsel.</strong> Portfolio view; intake routing;
                      contract and obligation oversight; outside-counsel spend.
                    </li>
                    <li>
                      <strong>Legal Ops.</strong> Intake, SLAs, reports; no draft
                      approvals.
                    </li>
                    <li>
                      <strong>Reviewer (outside).</strong> Scoped, time-bound access to a
                      specific matter; read-only by default.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Ethical walls">
                    Opposing parties or conflicted matters use a matter-level wall. Users
                    outside the wall cannot see the matter exists, even at admin level. The
                    wall overrides role access — it does not weaken it.
                  </Callout>
                </Section>

                <Section id="matters" title="3 · Opening and running a matter">
                  <p>
                    A new matter takes about a minute to open and is the anchor for every
                    other workflow. The fields below are the minimum that make downstream
                    drafting, hearing prep and recommendations useful — a thinner record
                    will still work but will lean on fact placeholders.
                  </p>
                  <Steps
                    items={[
                      <>
                        Go to <strong>Matters → New matter</strong>. Give it a clear
                        plain-English title (e.g. <em>Arbitral award challenge — Acme v.
                        Kappa</em>).
                      </>,
                      <>
                        Pick a <strong>type</strong> (litigation, arbitration, advisory,
                        contract, regulatory) and a <strong>forum</strong> (court, tribunal,
                        internal).
                      </>,
                      <>
                        Add <strong>parties</strong> on both sides. Each party row carries
                        its counsel, contact and role.
                      </>,
                      <>
                        Set the <strong>stage</strong> (pleadings, evidence, arguments,
                        post-judgment). Stages drive deadline templates and surface only
                        relevant actions in the cockpit.
                      </>,
                      <>
                        Attach the first batch of <strong>documents</strong>. See section 4
                        for how indexing and OCR work.
                      </>,
                    ]}
                  />
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    The matter cockpit
                  </h3>
                  <p>
                    Opening any matter puts you in the cockpit. The top bar shows parties,
                    forum and the next hearing. Tabs run across: <strong>Overview</strong>,{" "}
                    <strong>Documents</strong>, <strong>Drafts</strong>,{" "}
                    <strong>Hearings</strong>, <strong>Research</strong>,{" "}
                    <strong>Contracts</strong>, <strong>Billing</strong>,{" "}
                    <strong>Team</strong>, <strong>Audit</strong>. Everything that happens
                    here is recorded in the audit trail with the user, timestamp and before
                    and after state.
                  </p>
                </Section>

                <Section id="documents" title="4 · Documents and indexing">
                  <p>
                    Every document uploaded to a matter is queued for extraction and
                    embedding so you can search it semantically alongside the CaseOps public
                    corpus. Expect PDFs, DOCX, emails (EML) and scanned pages. Scanned pages
                    run through OCR before indexing.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      <strong>Upload.</strong> Drag and drop onto the Documents tab, or
                      paste a file list. Files above <strong>50 MB</strong> are rejected at
                      the edge.
                    </li>
                    <li>
                      <strong>Status pills.</strong> <em>Queued</em> → <em>Indexed</em>.{" "}
                      <em>OCR pending</em> appears on scans and typically clears in a few
                      minutes.
                    </li>
                    <li>
                      <strong>Retry.</strong> A failed extraction shows a Retry button.
                      Re-indexing a document does not duplicate chunks.
                    </li>
                    <li>
                      <strong>Private by matter.</strong> Documents inherit the matter's
                      ethical wall. They are never pooled across tenants or used for
                      cross-tenant training.
                    </li>
                  </ul>
                  <Callout title="What gets embedded">
                    Only extracted text goes into the search index — not the raw file. An
                    audit entry records who uploaded and who retrieved it. The original PDF
                    stays in the document store and is served over a short-lived signed URL
                    when a user opens it.
                  </Callout>
                </Section>

                <Section id="drafting" title="5 · Drafting with citations">
                  <p>
                    The Drafting Studio produces a first draft from the matter's own
                    record — parties, stage, documents, focus note — grounded in statutes
                    and judgments retrieved from the CaseOps corpus and your internal
                    precedents. Every inline citation resolves to a named authority. Every
                    fact gap renders as a placeholder the reviewer fills in, not as a
                    fabricated number.
                  </p>
                  <Steps
                    items={[
                      <>
                        In a matter, open <strong>Drafts → New draft</strong> and pick a
                        template (bail application, §34 petition, reply to summons,
                        quashing, etc.).
                      </>,
                      <>
                        Add a <strong>focus note</strong> — one or two lines of what this
                        draft must argue. This is the single most load-bearing field.
                      </>,
                      <>
                        Press <strong>Generate</strong>. The first pass finishes in 30–90s;
                        the draft opens with inline citation pills and a grounding panel on
                        the right.
                      </>,
                      <>
                        Review for: fact placeholders to resolve, citations to verify, and
                        statute attribution. The reviewer findings block at the foot of the
                        draft calls these out.
                      </>,
                      <>
                        Request approval from a partner. Approval is recorded in the audit
                        trail alongside the draft version.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="CaseOps will refuse to invent facts">
                    Missing facts render as <code>[____]</code> placeholders — FIR number,
                    dates, amounts, witness names. This is by design. A draft that invents a
                    fact is a ship-stopper; a draft that openly asks for a fact is normal
                    first-pass work.
                  </Callout>
                </Section>

                <Section id="hearings" title="6 · Hearing preparation">
                  <p>
                    The Hearings tab pulls the next listings for this matter. Open the next
                    hearing and press <strong>Compile pack</strong>. CaseOps stitches a pack
                    in under a minute, from the matter record and the authority corpus:
                  </p>
                  <ul className="mt-3 list-disc space-y-2 pl-6 text-[15px]">
                    <li>
                      A <strong>chronology</strong> built from the matter's documents and
                      activity — no manual entry.
                    </li>
                    <li>
                      The <strong>last order</strong> and its operative portion extracted
                      and pinned.
                    </li>
                    <li>
                      A short <strong>oral points</strong> list — the arguments you actually
                      want to make, keyed to the matter record.
                    </li>
                    <li>
                      A <strong>bench brief</strong> covering the judge's recent trend on
                      this class of matter (shown only where the corpus supports it).
                    </li>
                    <li>
                      The <strong>source list</strong> — every piece of content in the pack
                      is traceable back to a matter document or a named authority.
                    </li>
                  </ul>
                  <Callout title="Cause-list sync">
                    Workspaces in Delhi, Bombay, Karnataka and Telangana can opt in to
                    automatic morning cause-list ingest. A flagged matter means the cause
                    list shows a listing CaseOps did not expect from your records — a fast
                    prompt to refresh the pack.
                  </Callout>
                </Section>

                <Section id="research" title="7 · Research and authorities">
                  <p>
                    The Research workspace (<Kbd>⌘</Kbd> <Kbd>K</Kbd> then type{" "}
                    <em>research</em>, or visit <code>/app/research</code>) is the place to
                    run open-ended queries against the public corpus without tying the
                    query to a specific draft. It is a search tool, not a chatbot.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Query.</strong> Natural language works best — phrase the
                      issue, not a keyword. Example: <em>triple test for anticipatory bail
                      under BNSS s.482</em>.
                    </li>
                    <li>
                      <strong>Results.</strong> Judgments return with a short extract, court
                      and date metadata, and a link to open the full PDF. Cosine
                      distance is surfaced so you can judge strength at a glance.
                    </li>
                    <li>
                      <strong>Annotations.</strong> Flag or shortlist an authority for the
                      current matter. Annotations are tenant-private and travel with the
                      matter, not the user.
                    </li>
                  </ul>
                  <Callout title="Why some searches return no result">
                    CaseOps only returns what it can ground. If a query sits outside the
                    corpus (rare foreign judgments, unindexed tribunals, matters before
                    1990 in some courts), the system returns an explicit no-result rather
                    than invent one. This is the right behaviour for a legal tool.
                  </Callout>
                </Section>

                <Section id="contracts" title="8 · Contracts and playbooks">
                  <p>
                    Contracts are a first-class matter type. You can open a matter that is a
                    single contract review, or attach a contract to a litigation matter.
                    The Contracts tab shows clause extractions, obligations, redlines and
                    version lineage.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Upload.</strong> Drop the contract (.docx or .pdf). CaseOps
                      extracts parties, effective dates, key covenants and payment terms.
                    </li>
                    <li>
                      <strong>Playbook compare.</strong> Pick a playbook; the system flags
                      clauses that deviate from it and suggests an edit per deviation.
                    </li>
                    <li>
                      <strong>Obligations.</strong> Payment, reporting, consent and
                      termination obligations lift into the Obligations list with due
                      dates and owners.
                    </li>
                    <li>
                      <strong>Redlines.</strong> Track changes export cleanly to Word with
                      a single summary of what changed and why.
                    </li>
                  </ul>
                </Section>

                <Section id="recommendations" title="9 · Recommendations">
                  <p>
                    CaseOps produces explainable recommendations — forum choice, supporting
                    authorities, next best action — with rationale, assumptions, missing
                    facts and a confidence label. Recommendations are <strong>never</strong>{" "}
                    black-box favourability scores. You must see why a recommendation was
                    made before accepting it.
                  </p>
                  <ol className="mt-3 list-decimal space-y-2 pl-6 text-[15px]">
                    <li>
                      <strong>Rationale.</strong> Two to four sentences, grounded in named
                      authorities and the matter record.
                    </li>
                    <li>
                      <strong>Assumptions.</strong> Facts the system took as given. Wrong
                      assumptions are your signal to reject the recommendation.
                    </li>
                    <li>
                      <strong>Missing facts.</strong> Fields the system flagged as absent or
                      too thin. Filling these in and re-running sharpens the output.
                    </li>
                    <li>
                      <strong>Confidence.</strong> High / Medium / Low. Low-confidence
                      recommendations are deliberately surfaced, not hidden.
                    </li>
                  </ol>
                  <Callout tone="warn" title="Human review is the default">
                    No recommendation auto-acts. Accepting a recommendation is a tracked
                    action; the audit log records who accepted, when, and against what
                    version of the underlying draft or pack.
                  </Callout>
                </Section>

                <Section id="outside-counsel" title="10 · Outside counsel and spend">
                  <p>
                    General Counsel teams run <strong>Outside counsel</strong> from the
                    top-level nav. The directory carries rate cards, historical outcomes,
                    speciality tags and conflict flags. A matter can brief one or many
                    firms; spend and realisation roll up to the portfolio view.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Brief.</strong> From a matter, pick a counsel; CaseOps issues
                      a brief packet that respects the matter's ethical wall.
                    </li>
                    <li>
                      <strong>Budget.</strong> Assign a budget with alert thresholds.
                      Invoices above the cap require a partner override.
                    </li>
                    <li>
                      <strong>Realisation.</strong> The counsel dashboard shows billed,
                      collected and aging, with the portfolio roll-up on the home
                      dashboard.
                    </li>
                  </ul>
                </Section>

                <Section id="billing" title="11 · Billing, invoices and payments">
                  <p>
                    CaseOps produces invoices from tracked time and matter activity. Pine
                    Labs is wired as the default payment rail — every invoice goes out with
                    a payment link, and settlement writes back as paid automatically.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Time entries.</strong> Log from the matter or the global Time
                      tab. Filters for user, matter, client and date range.
                    </li>
                    <li>
                      <strong>Invoices.</strong> Draft → send → paid. Drafts pull WIP time
                      and matter-level expenses; sends attach a PDF and the payment link.
                    </li>
                    <li>
                      <strong>Recoveries.</strong> Partial payments, holds and write-offs
                      are first-class, not free-text notes. Every state change is on the
                      audit trail.
                    </li>
                    <li>
                      <strong>GST.</strong> India GST is handled on the invoice line-item
                      level; a monthly report exports to the format your accountant
                      expects.
                    </li>
                  </ul>
                </Section>

                <Section id="admin" title="12 · Admin, audit and ethical walls">
                  <p>
                    Admins run the workspace from <code>/app/admin</code>. The six important
                    subsections are <strong>Members</strong>, <strong>Teams</strong>,{" "}
                    <strong>AI policy</strong>, <strong>Audit export</strong>,{" "}
                    <strong>Ethical walls</strong> and <strong>Billing</strong> (workspace
                    billing, not client billing).
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Members.</strong> Invite, change role, deactivate. Deactivation
                      revokes access immediately; the user's prior actions stay attributed
                      in the audit log.
                    </li>
                    <li>
                      <strong>Teams.</strong> Matter visibility can be scoped to a team.
                      Useful for practice groups or conflict segregation short of a full
                      ethical wall.
                    </li>
                    <li>
                      <strong>AI policy.</strong> Cap the providers, models and context
                      shapes the workspace is allowed to use. AI actions outside the policy
                      are blocked before any token is spent.
                    </li>
                    <li>
                      <strong>Audit export.</strong> JSONL or CSV for any date range. Large
                      exports run as background jobs; download when complete.
                    </li>
                    <li>
                      <strong>Ethical walls.</strong> Add, edit, dissolve. Every change is
                      itself an audited event.
                    </li>
                  </ul>
                </Section>

                <Section id="security" title="13 · Security and data boundaries">
                  <p>
                    Security is not a tab — it is the way every other tab is built. The
                    short version:
                  </p>
                  <ul className="mt-3 list-disc space-y-2 pl-6 text-[15px]">
                    <li>
                      <strong>Tenant isolation</strong> at the query and storage layer,
                      not only the application layer.
                    </li>
                    <li>
                      <strong>Matter-level ethical walls</strong> override role access. A
                      partner outside a wall sees no traces of the walled matter.
                    </li>
                    <li>
                      <strong>Audit on every sensitive action</strong> — create, read,
                      update, delete, export, AI run, recommendation accept, payment state
                      change.
                    </li>
                    <li>
                      <strong>No cross-tenant training.</strong> Your documents and matter
                      activity are not pooled into model training without an explicit
                      opt-in.
                    </li>
                    <li>
                      <strong>Encryption in transit and at rest</strong>, signed URLs for
                      document downloads, and short-lived session tokens.
                    </li>
                    <li>
                      <strong>Hardened browser headers</strong> — CSP, HSTS, X-Frame
                      DENY, strict Permissions-Policy — reduce client-side exposure.
                    </li>
                  </ul>
                  <Callout title="Request a security review">
                    Enterprise prospects can request the security one-pager and a live
                    review from{" "}
                    <a className="underline" href={`mailto:${siteConfig.contact.sales}`}>
                      {siteConfig.contact.sales}
                    </a>
                    . DPAs and sub-processor lists are available on signature.
                  </Callout>
                </Section>

                <Section id="troubleshooting" title="14 · Troubleshooting">
                  <h3 className="font-display text-lg text-[var(--color-ink)]">
                    A document won't index
                  </h3>
                  <p>
                    Check the status pill in Documents. Most failures are OCR timeouts on
                    very large scans — press Retry. Persistent failures usually mean the
                    PDF has no extractable text and no OCR layer; convert to DOCX or
                    re-scan at a higher DPI.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    Citations in my draft look wrong
                  </h3>
                  <p>
                    Use the grounding panel on the right side of the Drafting Studio —
                    every inline citation has a source. If an authority is wrong for the
                    point, open it, remove it from the shortlist, and regenerate. The
                    reviewer findings block at the foot of the draft also flags likely
                    mismatches.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    Research returned 0 results
                  </h3>
                  <p>
                    Two common causes. The query is too generic (<em>bail</em>) and the
                    system refused to narrow arbitrarily — rewrite with the issue and the
                    statute. Or the corpus does not cover that jurisdiction and year — the
                    Home dashboard shows corpus coverage by court and year.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A colleague cannot see a matter I opened
                  </h3>
                  <p>
                    Ethical wall or team scope. Open the matter, check{" "}
                    <strong>Team</strong>, and either widen the team or dissolve the wall.
                    Admins can do this; partners inside the wall can too.
                  </p>
                </Section>

                <Section id="glossary" title="15 · Glossary">
                  <dl className="mt-4 space-y-4 text-[15px]">
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Matter graph</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The connected record of everything that belongs to one matter —
                        parties, documents, drafts, hearings, invoices, activity, audit.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Cockpit</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The single-page view of a matter. Every tab inside it is a lens on
                        the same graph.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Corpus</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The public pool of statutes, judgments and regulatory material
                        CaseOps retrieves against. Tenant documents are separate and
                        tenant-private.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Ethical wall</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A matter-level access control that restricts a matter to named
                        users, overriding broader role permissions.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Grounding</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The link between an AI output and the source it came from (a
                        judgment, statute, or matter document). A CaseOps output without a
                        grounding is a bug.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">
                        Recall@10 / MRR
                      </dt>
                      <dd className="text-[var(--color-ink-2)]">
                        Retrieval quality metrics. Recall@10 is the fraction of queries
                        whose correct answer appears in the top-10 results. MRR (mean
                        reciprocal rank) averages 1/rank across queries — higher means the
                        correct hit sits closer to the top.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">
                        Hearing pack
                      </dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The bundle a lawyer takes into court — chronology, last order,
                        oral points, bench brief, source list — compiled from the matter
                        record and authority corpus.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Playbook</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A named set of preferred contract positions. CaseOps compares any
                        inbound contract against the playbook and surfaces deviations.
                      </dd>
                    </div>
                  </dl>
                </Section>

                <div className="mt-14 rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-8">
                  <div className="font-display text-xl text-[var(--color-ink)]">
                    Still a question left over?
                  </div>
                  <p className="mt-2 text-[15px] leading-relaxed text-[var(--color-mute)]">
                    The support desk is at{" "}
                    <a className="underline" href="mailto:support@caseops.ai">
                      support@caseops.ai
                    </a>
                    . For security reviews and enterprise trials, write to{" "}
                    <a className="underline" href={`mailto:${siteConfig.contact.sales}`}>
                      {siteConfig.contact.sales}
                    </a>
                    . This guide is versioned; the top of the page shows when it was last
                    updated.
                  </p>
                </div>
              </article>
            </div>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  );
}
