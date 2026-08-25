import type { Metadata } from "next";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "User guide",
  description:
    "The current CaseOps user guide: daily priorities, intake and optional conflict review, matters, governed IP documents, notices and reply deadlines, communications, tracked case refresh, compliance review, drafting, hearings, contracts, outside counsel, billing, and safe source-backed intelligence.",
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
  { id: "status-labels", title: "Product status labels" },
  { id: "daily-operations", title: "Today, calendar and portfolio" },
  { id: "workspace", title: "Workspace and roles" },
  { id: "intake-conflicts", title: "Intake, clients and optional conflict review" },
  { id: "matters", title: "Opening and running a matter" },
  { id: "documents", title: "Documents and indexing" },
  { id: "notices", title: "Notices and reply deadlines" },
  { id: "communications", title: "Communications and review queues" },
  { id: "drafting", title: "Drafting with citations" },
  { id: "hearings", title: "Hearing preparation" },
  { id: "case-tracking", title: "Case tracking refresh" },
  { id: "compliance", title: "Court-order compliance review" },
  { id: "cause-list", title: "Date-wise cause lists" },
  { id: "litigation-intelligence", title: "Litigation Intelligence" },
  { id: "bench-strategy", title: "Bench-aware appeal drafting" },
  { id: "statutes", title: "Statutes and sections" },
  { id: "research", title: "Research and authorities" },
  { id: "contracts", title: "Contracts and playbooks" },
  { id: "recommendations", title: "Recommendations" },
  { id: "outside-counsel", title: "Outside counsel and spend" },
  { id: "billing", title: "Matter billing and invoices" },
  { id: "admin", title: "Admin, audit and access controls" },
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
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-2)]">
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
              User guide · v3 · 2026
            </span>
            <h1 className="mt-3 max-w-4xl font-display text-4xl font-normal leading-[1.1] tracking-tight text-[var(--color-ink)] md:text-[3.25rem]">
              How to run your practice on CaseOps.
            </h1>
            <p className="mt-5 max-w-2xl text-[17px] leading-relaxed text-[var(--color-mute)]">
              A linear, end-to-end read for partners, associates, general counsel and legal
              ops. Twenty-six sections. Read front to back the first time; return for the
              section that matches the task in front of you after that.
            </p>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-[var(--color-ink-2)]">
              <span>
                <span className="font-mono text-[var(--color-ink-2)]">Audience</span>{" "}
                Litigation partners · GCs · legal ops · solos
              </span>
              <span>
                <span className="font-mono text-[var(--color-ink-2)]">Reading time</span>{" "}
                ~50 min
              </span>
              <span>
                <span className="font-mono text-[var(--color-ink-2)]">Updated</span>{" "}
                22 August 2026
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
                    documents, notices, drafting, hearings, contracts, outside counsel,
                    billing, and the audit trail that ties them together. After sign in,
                    use the left navigation to open the Home dashboard, Today queue, matters,
                    import activity, research, or the workspace administration surfaces your role permits.
                  </p>
                  <Steps
                    items={[
                      <>
                        <strong>Create a workspace.</strong> Visit{" "}
                        <a className="underline" href="/sign-in">/sign-in</a>, pick{" "}
                        <em>New workspace</em>, and enter your firm or company name. You
                        become the workspace Owner.
                      </>,
                      <>
                        <strong>Recover access.</strong> Use{" "}
                        <a className="underline" href="/account/forgot-password">
                          /account/forgot-password
                        </a>{" "}
                        from the sign-in page to request a single-use reset link. The
                        request message is intentionally generic so it never confirms
                        whether a workspace or email exists.
                      </>,
                      <>
                        <strong>Add colleagues.</strong> Open{" "}
                        <a className="underline" href="/app/admin/employees">
                          Admin → Employees
                        </a>{" "}
                        and assign an Owner-managed built-in or custom role. The available
                        actions remain capability-gated by the API.
                      </>,
                      <>
                        <strong>Verify the brand.</strong> Add your firm logo and a default
                        contact email so draft dispatches and invoices carry them.
                      </>,
                      <>
                        <strong>Secure your account.</strong> Open{" "}
                        <a className="underline" href="/account/security">
                          Account security
                        </a>{" "}
                        to enrol MFA, save recovery codes, and complete recent MFA step-up
                        before protected actions when policy requires it.
                      </>,
                      <>
                        <strong>Open your first matter.</strong> Continue through daily
                        operations, roles, and optional conflict review before opening or
                        working an active file.
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

                <Section id="status-labels" title="2 · Product status labels">
                  <p>
                    Public CaseOps claims use six labels. <strong>Live</strong> means the
                    capability is available in the product. <strong>Review-first</strong>{" "}
                    means the system proposes or drafts, but a human must approve the
                    substantive result. <strong>Provider-gated</strong> means CaseOps has
                    internal readiness but needs external provider credentials, consent,
                    or UAT evidence. <strong>Founder-only</strong> means the surface is
                    restricted to the platform super-admin. <strong>Disabled until UAT</strong>{" "}
                    means code and evidence scaffolding exist but production activation
                    is intentionally blocked. <strong>Planned</strong> means the public
                    claim is roadmap/readiness only.
                  </p>
                  <Callout tone="warn" title="Current gated claims">
                    Pine Labs production payments are disabled until UAT and founder
                    go/no-go. OIDC/SAML SSO, SCIM, private enterprise deployment, and
                    autonomous scoped-agent execution are planned/readiness-only.
                    Google Workspace, Microsoft 365, inbound email, SMS, WhatsApp, and
                    court-provider automation stay provider-gated where external
                    credentials, admin consent, or legal source proof is missing.
                  </Callout>
                </Section>

                <Section id="daily-operations" title="3 · Today, calendar and portfolio">
                  <p>
                    Start routine work at <a className="underline" href="/app/today">Today</a>.
                    It brings together hearings and deadlines in the next seven days, overdue
                    or due-soon tasks, drafts pending review, and overdue invoices across the
                    matters you can see.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Act from the source.</strong> Each Today item links back to its
                      matter, hearing, draft, or billing surface. Today is a prioritised feed;
                      the underlying list remains the source of truth.
                    </li>
                    <li>
                      <strong>Know when a stream is capped.</strong> A note appears when a
                      stream reaches its server-side limit. Open the relevant list view to see
                      the complete set.
                    </li>
                    <li>
                      <strong>Use Calendar for date work.</strong>{" "}
                      <a className="underline" href="/app/calendar">Calendar</a> combines
                      visible legal filing deadlines, internal targets, hearings/listings,
                      renewals, and task dates with distinct labels. IP legal dates link back
                      to their docket. Provider sync conflicts stay reviewable rather than
                      overwriting manually protected dates.
                    </li>
                    <li>
                      <strong>Inspect an IP deadline before relying on it.</strong> In the IP
                      workspace, open calculation provenance to see the stored trigger, rule,
                      working calendar, approved extension input, override, and predecessor
                      chain. An extension application alone does not move the legal date.
                    </li>
                    <li>
                      <strong>Use Portfolio for the roll-up.</strong>{" "}
                      <a className="underline" href="/app/portfolio">Portfolio</a> groups
                      matters by lifecycle status, forum, and practice area and calls out work
                      that needs attention.
                    </li>
                  </ul>
                </Section>

                <Section id="workspace" title="4 · Workspace and roles">
                  <p>
                    Every workspace is an isolated tenant. Data never crosses tenant
                    boundaries — the query layer, storage layer and audit trail all filter
                    by tenant id. Users inside a workspace see what their role permits, and
                    matter-level access restrictions can further narrow visibility.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    Roles at a glance
                  </h3>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Owner.</strong> Workspace owner with the broadest built-in
                      access, including ownership-sensitive employee administration.
                    </li>
                    <li>
                      <strong>Admin.</strong> Manages employees, roles, teams, workspace
                      settings, provider operations, billing configuration, and audit tools
                      according to assigned capabilities.
                    </li>
                    <li>
                      <strong>Partner.</strong> Runs matters and can receive approval and
                      conflict-resolution capabilities without becoming a workspace owner.
                    </li>
                    <li>
                      <strong>Member.</strong> The standard fee-earner or legal-team role for
                      day-to-day matter work.
                    </li>
                    <li>
                      <strong>Paralegal.</strong> A narrower operational role for permitted
                      matter, document, task, and hearing work.
                    </li>
                    <li>
                      <strong>Viewer.</strong> Read-oriented access where the capability grid
                      permits it. Custom roles can be configured from Admin → Roles.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Roles do not replace matter access">
                    The API is the source of truth for every capability. Owners and admins
                    can review an employee&apos;s matter access from Admin → Employees. The
                    dedicated ethical-walls admin UI is still status-gated and must not be
                    treated as a live self-service surface.
                  </Callout>
                </Section>

                <Section id="intake-conflicts" title="5 · Intake, clients and optional conflict review">
                  <p>
                    Use <a className="underline" href="/app/intake">Intake</a> for inbound
                    business requests before they become matters. Users with the relevant
                    capabilities can submit, triage, assign, update, reject, complete, or
                    promote a request once its scope is clear.
                  </p>
                  <Steps
                    items={[
                      <>
                        Capture the request, requester, business context, priority, target
                        date, and proposed matter code where known.
                      </>,
                      <>
                        Triage through <em>New</em>, <em>Triaging</em>, and{" "}
                        <em>In progress</em>; reject or complete requests with a recorded
                        reason when appropriate.
                      </>,
                      <>
                        Promote an approved request to a matter. Client records live in{" "}
                        <a className="underline" href="/app/clients">Clients</a> for users
                        with client capabilities.
                      </>,
                      <>
                        On the matter Overview, run <strong>Conflict check</strong> against
                        workspace clients and matters, including the opposing and related
                        parties entered for the scan.
                      </>,
                      <>
                        A partner or admin reviews candidate overlaps and records{" "}
                        <em>Cleared</em>, <em>Conflicted</em>, or an explicit{" "}
                        <em>Waiver</em> with a note. The result is auditable review evidence,
                        not a precondition for creating or activating the matter.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="Review evidence is not a status gate">
                    Candidate matching is a review aid. A pending or conflicted result is not
                    the same as clearance, but it does not block creation or a move to Active.
                    After a material party change or matter reopen, the earlier result remains
                    historical; run a fresh check before calling the matter currently cleared.
                  </Callout>
                </Section>

                <Section id="matters" title="6 · Opening and running a matter">
                  <p>
                    A new matter takes about a minute to open and is the anchor for every
                    other workflow. Create the shell with enough identifying detail to
                    support conflict review, then add parties, documents, dates, and work
                    from the cockpit.
                  </p>
                  <Steps
                    items={[
                      <>
                        Go to <strong>Matters → New matter</strong>. Give it a clear
                        plain-English title (e.g. <em>Arbitral award challenge — Acme v.
                        Kappa</em>).
                      </>,
                      <>
                        Enter a unique <strong>matter code</strong>, practice area, client,
                        and opposing party. These fields make lists and conflict review more
                        useful.
                      </>,
                      <>
                        Add the case number or CNR when available and select the structured
                        court/forum. If the catalog is unavailable, use the explicit
                        uncatalogued fallback instead of saving stale forum metadata.
                      </>,
                      <>
                        New Matter starts <strong>Active</strong> by default. If your team
                        chooses to keep a pre-engagement file in <strong>Intake</strong> while
                        its conflict check is pending, it can still move to Active. Conflict
                        review remains optional and available before or after that change.
                      </>,
                      <>
                        Add a concise description, create the matter, then attach the first
                        batch of <strong>documents</strong>. See section 7 for indexing and
                        OCR.
                      </>,
                    ]}
                  />
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Bulk upload matters
                  </h3>
                  <p>
                    Owners, Admins, and users with a delegated Matter Manager capability
                    can select <strong>Bulk upload matters</strong> from the Matter
                    portfolio. Download the canonical 21-column XLSX template for
                    status, forum, date, people, and team guidance; CSV is also available
                    for migration tooling. <strong>Court</strong> stores the name, while{" "}
                    <strong>Court Forum Number</strong> separately stores an optional
                    court, bench, room, or forum reference.
                  </p>
                  <ol className="mt-3 list-decimal space-y-2 pl-6 text-[15px]">
                    <li>
                      Enter one matter per row. Matter Title, Matter Code, Practice Area,
                      and Forum are required. Client Name is optional. Leave Matter Status
                      blank to create the matter as Active.
                    </li>
                    <li>
                      Upload a CSV/XLSX file of at most 500 non-empty rows and 2 MB, then
                      select <strong>Validate data before import</strong>. Validation does
                      not create matters. CSV accepts UTF-8, BOM-marked UTF-16, or
                      Windows-1252 with comma, semicolon, tab, or pipe separators. Quote
                      any field that contains the selected separator.
                    </li>
                    <li>
                      CaseOps accepts the documented client-register heading aliases and
                      can find a header below report-title rows or an import table on a
                      later XLSX worksheet. Status and Forum ignore case and presentation
                      separators: for example, <code>On Hold</code> and{" "}
                      <code>on_hold</code> match.
                    </li>
                    <li>
                      A valid non-catalog Practice Area is preserved. Normal business
                      punctuation is supported in applicable text and reference fields.
                      Client Email is limited to a valid 254-character address. Common
                      ISO, Indian day-first, month-name, and fractional Excel dates are
                      accepted; an XLSX workbook&apos;s 1900/1904 date system is honored
                      and its time-of-day fraction is discarded.
                    </li>
                    <li>
                      Review every row error. CaseOps checks required/type rules,
                      duplicates, dates, email and phone formats, status/forum values,
                      active users and teams, tenant boundaries, team scoping, and unsafe
                      formulas.
                    </li>
                    <li>
                      Confirm the job to create every row that remains valid. Invalid rows
                      are retained for correction, so a mixed file may complete with both
                      successful and failed counts.
                    </li>
                    <li>
                      Download the error CSV and use Import History to search by file or
                      uploader and review upload date, status, totals, imported, and failed
                      counts.
                    </li>
                  </ol>
                  <Callout tone="warn" title="Identifiers and spreadsheet safety stay strict">
                    Matter Code is 2-80 characters after trimming and uppercasing, starts
                    and ends with a letter or digit, and permits only letters, digits, and
                    internal hyphens. Formula nodes in the selected import header/data
                    cells and formula-like selected-table text remain blocked. A phone
                    needs 7-20 main-number digits and may have a trailing{" "}
                    <code>ext</code>, <code>ext.</code>, or <code>x</code> followed by
                    1-10 digits.
                    Only Client Contact Number may begin with <code>+</code>; after it,
                    the formula-safe grammar permits digits, spaces, parentheses, and
                    hyphens before the optional extension. Without <code>+</code>,
                    periods, commas, <code>#</code>, slashes, and <code>&amp;</code> are
                    also allowed.
                  </Callout>
                  <Callout title="Safe and recoverable imports">
                    Validation expires after 24 hours and is repeated at confirmation.
                    Repeating confirmation for a completed job creates no duplicates. The
                    upload, validation failures, completion, row outcomes, cancellation,
                    and error-report download remain tenant-scoped and audited. XLSX files
                    must be unencrypted, remain inside standard Excel A-XFD/1-1,048,576
                    coordinates, and pass bounded archive checks before parsing.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Import activity across the workspace
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/imports">Import activity</a>{" "}
                    to review accessible trademark, matter, and employee import jobs in one
                    status view. Filter by workflow, inspect the input manifest, download a
                    normalized row-error report, or follow the row action back to the
                    canonical import screen. The activity view is read-only: matter and
                    employee history stays in its existing owner and is never copied or
                    rewritten. Older employee jobs may show <strong>checksum not recorded</strong>{" "}
                    because that legacy workflow did not persist one.
                  </p>
                  <p>
                    Trademark files continue through{" "}
                    <a className="underline" href="/app/ip/portfolio/imports">
                      Trademark portfolio import
                    </a>
                    , matter files through{" "}
                    <a className="underline" href="/app/matters/imports">
                      Bulk upload matters
                    </a>
                    , and employee files through{" "}
                    <a className="underline" href="/app/admin/employees">
                      Admin → Employees
                    </a>
                    . Access to each history and its manifest/error report follows the same
                    capability and tenant boundary as its canonical workflow.
                  </p>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    The matter cockpit
                  </h3>
                  <p>
                    Opening any matter puts you in the cockpit. The top bar shows parties,
                    forum and next hearing. The live tabs are <strong>Overview</strong>,{" "}
                    <strong>Timeline</strong>, <strong>Tasks &amp; Deadlines</strong>,{" "}
                    <strong>Documents</strong>, <strong>Notices</strong>,{" "}
                    <strong>Drafts</strong>, <strong>Hearings</strong>,{" "}
                    <strong>AI Recommendations</strong>, <strong>Strategy Plan</strong>,{" "}
                    <strong>Predictive Intelligence</strong>,{" "}
                    <strong>Intelligence Review</strong>, <strong>Knowledge Graph</strong>,{" "}
                    <strong>Statutes</strong>, <strong>Communications</strong>,{" "}
                    <strong>Billing</strong>, and <strong>Matter Audit</strong>.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Timeline.</strong> Review hearings, orders, documents,
                      deadlines, tasks, and material activity together; filter by event type
                      and sort oldest- or newest-first.
                    </li>
                    <li>
                      <strong>Tasks &amp; Deadlines.</strong> Keep operational work and legal
                      dates on the matter. Source-backed compliance and notice workflows may
                      create linked deadlines; review their source before changing status.
                    </li>
                    <li>
                      <strong>Status.</strong> Active matters use the normal lifecycle
                      states. A completed matter is marked <strong>Dispose</strong> in the
                      UI and is stored by the API as <code>disposed</code>. Older
                      integrations that still submit <code>closed</code> are normalized to
                      <code>disposed</code> during the compatibility window.
                    </li>
                    <li>
                      <strong>Next hearing.</strong> The header shows the date plus its
                      source: manual, case tracking, court sync, proceeding intelligence,
                      cause list, or unknown. Manual lock prevents automatic overwrite;
                      conflicting provider dates become review suggestions with accept and
                      reject actions.
                    </li>
                    <li>
                      <strong>History.</strong> Every next-hearing change records old date,
                      new date, actor or system source, reason, source reference, timestamp,
                      and whether the manual lock was active.
                    </li>
                  </ul>
                </Section>

                <Section id="documents" title="7 · Documents and indexing">
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
                      <strong>Private by matter.</strong> Documents inherit the matter&apos;s
                      server-side access restrictions. They are never pooled across tenants
                      or used for cross-tenant training.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Court-order uploads
                  </h3>
                  <p>
                    Manual court orders can be uploaded from the matter or hearings view as
                    PDF, DOC, DOCX, or image files within the configured file-size limit.
                    Extraction starts only after the file-safety gate passes. If text is
                    not available immediately, the order shows <em>OCR pending</em>; failed
                    OCR or extraction shows a redacted error and a Retry action.
                  </p>
                  <Callout tone="warn" title="No unsafe court-source bypass">
                    CaseOps does not bypass captcha, login, or session-gated court sources.
                    Orders can come from configured lawful adapters, manual entry, or
                    uploaded documents that pass file-safety checks.
                  </Callout>
                  <Callout title="What gets embedded">
                    Only extracted text goes into the search index — not the raw file. An
                    audit entry records who uploaded and who retrieved it. The original PDF
                    stays in the document store and is served over a short-lived signed URL
                    when a user opens it.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Manual trademark applications
                  </h3>
                  <p>
                    In <a className="underline" href="/app/ip">IP docket</a>, select{" "}
                    <strong>New trademark</strong> to create the docket, trademark asset,
                    application, class scope, representation, parties, and any application
                    number as one controlled operation. A draft or pre-filing record does
                    not require an application number. A filed record requires either a
                    confirmed application number or an explicit registry-source statement
                    that allocation is pending.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Application, registration, opposition, rectification, cancellation,
                      non-use removal, appeal, and court identifiers retain separate labels
                      and legal owners. An opposition or post-registration proceeding number
                      is never displayed or stored as the trademark application number.
                    </li>
                    <li>
                      Punctuation and spacing variants are normalized for matching while
                      the source form remains visible. A possible duplicate is saved for
                      review and cannot silently merge records or enter filed phase.
                    </li>
                    <li>
                      Duplicate review shows the accessible candidates and blocking reasons
                      before a decision. Confirming a separate filing or superseding a number
                      requires a current preview and a written reason; supersession does not
                      delete or merge either docket.
                    </li>
                    <li>
                      Correcting a number creates a new identifier version. The prior source
                      value, effective range, correction reason, and audit evidence remain in
                      history.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Registry reconciliation
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/registry">Registry reconciliation</a>{" "}
                    to connect an application or proceeding to one IP-office identifier. Record the
                    office, jurisdiction, identifier type, source URL, and match evidence, then confirm
                    or reject the match with a written reason before adding source snapshots.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Manual intake stores both the source JSON and normalized register JSON with
                      retrieval time, parser version, attribution, and SHA-256 hashes. A correction
                      supersedes its predecessor with a reason; source snapshots cannot be edited or
                      deleted.
                    </li>
                    <li>
                      Every changed field remains a candidate until it is accepted, rejected, mapped,
                      or deferred. Proprietor, status, deadline, refusal, opposition, cancellation,
                      registration, and renewal fields are high risk and require IP approval. Mapping
                      a provider field to one of those canonical paths applies the same approval rule.
                    </li>
                    <li>
                      Accepting a change records candidate and reconciled IP docket events. A deadline
                      field also queues a durable calculation proposal; CaseOps does not invent or
                      confirm a legal deadline without an approved rule and calendar version.
                    </li>
                    <li>
                      The unresolved queue is paginated independently from bounded evidence history,
                      so an older pending review remains reachable. If accepted state changed after a
                      diff was created, CaseOps rejects the stale decision and requires a fresh snapshot.
                    </li>
                    <li>
                      A no-change check still updates freshness and attempt history. Authentication,
                      rate-limit, parsing, outage, configuration, or policy failures preserve the last
                      successful snapshot and accepted legal state.
                    </li>
                    <li>
                      Court or CNR proceedings reference the existing Matter bookmark and TrackedCase.
                      Court status, provider snapshots, and updates stay with case tracking and are never
                      copied into the IP registry record.
                    </li>
                    <li>
                      IP India live automation remains disabled until an approved provider contract,
                      licensing basis, credentials, and verified legal coverage exist. The current
                      workspace supports sourced manual evidence without claiming a provider call.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Madrid international registrations
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/madrid">Madrid portfolio</a>{" "}
                    to docket an outbound Indian basic-mark filing, an international
                    registration, or each designated member as a separate controlled record.
                    The international registration retains WIPO status; every designation
                    retains its own national status, local agent, deadlines, documents, fees,
                    and source history.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Outbound intake requires an eligible Indian trademark application,
                      office of origin, MM2 or applicable form, classes and goods/services.
                      Original and subsequent designations remain distinguishable and link to
                      the same parent registration without sharing legal status.
                    </li>
                    <li>
                      Record forms, fees, certification, irregularities, WIPO notification,
                      national examination, provisional refusal, response, publication,
                      opposition, grant or refusal statements, changes, renewals, and local-agent
                      instructions as versioned transactions. Link the canonical deadline,
                      document, or cost evidence used for the transaction.
                    </li>
                    <li>
                      A WIPO or national-office snapshot is always a source candidate. Counsel
                      opens the linked source and explicitly accepts, keeps separate, or rejects
                      it before CaseOps changes the authority-owned status. A stale version is
                      rejected and must be reviewed again.
                    </li>
                    <li>
                      Basic-mark dependency and central-attack reviews record affected
                      registrations, designations, deadlines, documents, and recommended work.
                      They do not automatically cancel, narrow, or otherwise change legal status.
                    </li>
                    <li>
                      WIPO live search, document retrieval, and polling remain disabled until an
                      approved provider contract, licensing basis, credentials, verified legal
                      coverage, and activation decision exist. The current workspace is manual,
                      source-linked docketing and makes no provider call.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Post-registration recordals and title
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/recordals">Post-registration</a>{" "}
                    for assignment, transmission, registered-user, licence, name/address,
                    association, division, limitation, disclaimer, certified-copy and
                    well-known-mark work. Renewal and restoration remain in Trademark renewals;
                    cancellation, rectification and non-use remain separate proceedings.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Select the affected application or registration, whole-right or
                      partial-class scope, parties, execution/effective dates, legal basis,
                      form, docket-linked instruments and cost items. Every party cites a
                      selected canonical instrument.
                    </li>
                    <li>
                      An authorized reviewer approves the package before filing. Record the
                      acknowledgement, defect, corrected instrument, rejection, withdrawal or
                      Registry acceptance as a separate transaction; prior attempts remain in
                      history.
                    </li>
                    <li>
                      Registry acceptance requires a confirmed affected application or
                      registration link, immutable snapshot, exact source, acceptance evidence,
                      Registry-recorded date and IP approval. Source links open from evidence
                      and history.
                    </li>
                    <li>
                      The dated title view separates Registry-recorded ownership from effective,
                      pending and beneficial interests. It surfaces overlapping title, partial
                      scope, unavailable or restricted source documents, effective-but-unrecorded
                      interests, title gaps and related-right cycles without changing another
                      family member.
                    </li>
                    <li>
                      Download the date-specific title report for the supported chain and its
                      unresolved issues. The report is based only on records and sources visible
                      to the signed-in user and remains subject to lawyer review.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Trademark journal watch
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/watch">Journal watch</a>{" "}
                    to define docket-specific word, phonetic, device, class, proprietor,
                    and jurisdiction criteria. Every profile records its check frequency,
                    notification recipients, provider, and cost ceiling. A cost ceiling or
                    unavailable provider visibly pauses the profile instead of silently
                    skipping a check.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Manual journal intake records the journal and application numbers,
                      published mark, classes and goods, proprietor, publication scope,
                      source URL and page, retrieval time, attribution, and parser version.
                      The source record is append-only and an idempotency key can replay only
                      its original payload and exact results.
                    </li>
                    <li>
                      Each hit shows the compared profile, candidate mark, class and goods
                      overlap, similarity-method evidence, publication date, and official
                      source link. AI and device-similarity signals are advisory; an attorney
                      must independently verify the source and record a reasoned disposition.
                    </li>
                    <li>
                      Final source-dependent decisions and action handoffs are blocked while
                      the source is unavailable or unconfirmed. Authorized recipients receive
                      a durable in-app notification when a new accessible hit is recorded.
                    </li>
                    <li>
                      A confirmed relevant hit can create an opposition proceeding,
                      enforcement Matter, task, operational deadline, or client-report evidence
                      item without re-entering the source and reviewer decision. The receiving
                      Matter or IP owner remains canonical.
                    </li>
                    <li>
                      Corrections and re-advertisements link to the prior publication and hit.
                      Prior evidence remains unchanged, partial published scope remains visible,
                      delayed intake raises a stale alert, and an earlier deadline state is
                      superseded only after the successor source is reviewed and confirmed.
                    </li>
                    <li>
                      Live journal-provider polling remains paused until the provider contract,
                      source licence, credentials, cost policy, and legal coverage are approved.
                      The current workflow supports sourced manual evidence and makes no external
                      call when those controls are absent.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Rectification, cancellation, and non-use proceedings
                  </h3>
                  <p>
                    Open the post-registration workspace in the{" "}
                    <a className="underline" href="/app/ip">IP docket</a> to create a
                    claimant- or respondent-side proceeding against the exact application.
                    Keep its proceeding number, profile, challenged classes, grounds, forum,
                    form, fee, service, rule map, and source records distinct from opposition.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      A rule applied mutatis mutandis requires counsel to record the source
                      rule, mapped provisions, excluded provisions, and confirmation. An
                      opposition template cannot be silently reused.
                    </li>
                    <li>
                      Link a parallel court or Registry proceeding without merging either
                      record. Record sourced stays and lift orders before proposing a legal
                      disposition.
                    </li>
                    <li>
                      Settlement, withdrawal, and closure require the legal effect, effective
                      date, evidence, and authorized confirmation. Candidate outcomes are
                      limited to the proceeding type and require a separate review.
                    </li>
                    <li>
                      Approval records the reviewed candidate but never changes the trademark
                      registration automatically. Any authoritative register update remains a
                      separate sourced, authorized action.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    IP and Matter relationships
                  </h3>
                  <p>
                    An IP docket can reference more than one accessible Matter. Open the
                    docket&apos;s <strong>Matter relationships</strong> panel to add an
                    operational, litigation, advisory, appeal, enforcement, billing, or
                    other role with a written reason. Creating an IP docket with a Matter
                    creates its operational relationship automatically.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Each relationship keeps an effective date and retirement history.
                      Retire a relationship instead of deleting it; retiring the operational
                      role also clears the compatibility Matter pointer.
                    </li>
                    <li>
                      The relationship panel shows the Matter and IP lifecycle states side
                      by side. Disposing or reopening a Matter does not archive, close, or
                      reopen the IP docket, and an IP lifecycle change does not change the
                      Matter status.
                    </li>
                    <li>
                      Accessible IP legal events appear in the linked Matter timeline by
                      reference and open the source IP record. CaseOps does not create a
                      duplicate Matter activity for the event.
                    </li>
                    <li>
                      If the two records have different access policies, authorized users
                      see a warning. A user who cannot access both sides sees no relationship
                      metadata, count, or hidden record identity.
                    </li>
                  </ul>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Applicant opposition docketing
                  </h3>
                  <p>
                    In the opposition workspace, confirm the applicant profile and source
                    notice first. A pending Registry opposition number remains visible and
                    must be recorded separately from the application number before stage
                    progression.
                  </p>
                  <Steps
                    items={[
                      <>
                        Select the exact active applicant-side rule and working calendar,
                        enter the trigger date and certainty, then propose the
                        counterstatement deadline.
                      </>,
                      <>
                        Confirm the calculated deadline with distinct primary and backup
                        membership owners. The linked operational Matter is required before
                        confirmation.
                      </>,
                      <>
                        At the counterstatement stage, record the TM-O filing reference,
                        final signed document, filing evidence, signatory, authority,
                        verification place/date, paragraph ranges, and knowledge basis.
                      </>,
                      <>
                        Record service separately. At the applicant-evidence stage, propose
                        and confirm the Rule 46 deadline and explicitly choose either filed
                        evidence or reliance on pleaded facts; no action is never treated as
                        an election.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="Exceptions remain evidence-backed">
                    An extension, waiver, skipped stage, supersession, or closure requires
                    its source, evidence, authority, and authorized confirmation. Withdrawing
                    the opposition does not close the linked Matter.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Opponent opposition docketing
                  </h3>
                  <p>
                    Select the opponent side when the firm is preparing the notice of
                    opposition. Keep the application number and Registry opposition number
                    separate; pending opposition-number allocation remains visible until the
                    Registry number is recorded.
                  </p>
                  <Steps
                    items={[
                      <>
                        Confirm the sourced opponent profile, relied-on rights, client
                        instruction, and limitation date. A watch hit can be closed with
                        evidence without marking an opposition filed; missing instruction is
                        escalated through an urgent shared task before limitation.
                      </>,
                      <>
                        Propose and confirm the notice deadline from the exact active
                        opponent rule and working calendar with distinct primary and backup
                        owners. Record the signed TM-O notice, filing receipt, verification,
                        source, and lawyer reason.
                      </>,
                      <>
                        If the Registry rejects the filing, record the rejection evidence and
                        corrective due date. CaseOps opens a corrective task and keeps the
                        filed stage blocked until an accepted corrected notice is recorded.
                      </>,
                      <>
                        Record notice service separately. At the evidence stages, confirm the
                        governed deadlines and make explicit Rule 45 and Rule 47 elections;
                        filed-evidence elections require final document and filing evidence
                        references.
                      </>,
                    ]}
                  />
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Trademark pleading review and filing
                  </h3>
                  <p>
                    Open <strong>Trademark pleadings</strong> inside an opposition proceeding.
                    The available notice, counterstatement, and evidence templates follow the
                    represented side, current stage, and Registry jurisdiction.
                  </p>
                  <Steps
                    items={[
                      <>
                        Generate from the confirmed application and opposition identifiers,
                        current proceeding, linked immutable document versions, and retrieved
                        authorities. Conflicting required identifiers block generation.
                      </>,
                      <>
                        Save every lawyer change as a new revision and open the revision
                        comparison before review. The original generated and previously filed
                        bodies remain available unchanged.
                      </>,
                      <>
                        Clear every blocker before approval: unresolved placeholders, changed
                        proceeding context or deadlines, lost authorities, missing or changed
                        source hashes, and unmapped exhibit references fail closed. Warnings
                        remain visible for lawyer resolution.
                      </>,
                      <>
                        Finalize the approved revision and download the filing bundle. The
                        Registry-formatted DOCX is separated from the internal generation
                        manifest and filing checklist inside the ZIP.
                      </>,
                      <>
                        Record filing, Registry rejection, corrected revision, and service as
                        separate human actions with references. A rejected filing reopens
                        drafting without rewriting the originally filed version.
                      </>,
                    ]}
                  />
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Shared evidence, hearing, order, and appeal work
                  </h3>
                  <Steps
                    items={[
                      <>
                        Record the filed Rule 45, Rule 46, or Rule 47 affidavit package with
                        its exhibits, index, verification, relied-on documents, filing receipt,
                        and service evidence. Further evidence stays blocked until the matching
                        leave or order is recorded.
                      </>,
                      <>
                        Schedule the canonical shared hearing with responsible attendance and
                        reminders. Link the cause list, issue checklist, evidence bundle,
                        authorities, written submissions, and post-hearing note to that hearing.
                      </>,
                      <>
                        Record an authorized deadline extension as a replacement of the
                        confirmed legal deadline. The original calculation and responsibility
                        history remain available; the replacement receives fresh ownership and
                        reminders.
                      </>,
                      <>
                        Record the operative order, affected application and opposition,
                        costs, compliance directions, appeal review, and final order document.
                        A later appeal must link that order to a separate appeal proceeding and
                        appeal identifier, or to an accessible Matter.
                      </>,
                      <>
                        Use the evidence-backed stage transition for withdrawal, settlement
                        closure, waiver, abandonment, or other exceptional outcomes. Closing an
                        opposition does not close its linked Matter.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="Specialist details remain bounded">
                    Multi-class partial outcomes, translation workflow, adjournment detail,
                    nonappearance, security for costs, and downstream application disposition
                    remain separately controlled work.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    Trademark renewals
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/renewals">Trademark renewals</a>{" "}
                    for the portfolio-wide due, instructed, filing, accepted, grace, and
                    overdue register. Each term shows the confirmed legal deadline, rule
                    citation, source version, grace date, recorded state, and any date-derived
                    state that still needs an explicit workflow transition.
                  </p>
                  <Steps
                    items={[
                      <>
                        Select a term and schedule instruction notifications. Active primary
                        and backup deadline owners receive an immediate in-app request plus
                        the future reminder offsets; repeating the action does not duplicate
                        them.
                      </>,
                      <>
                        Record the client decision, scope, authority, channel, and evidence
                        reference. Receiving an instruction cancels queued no-instruction
                        reminders. A reviewer then accepts, rejects, or requests clarification.
                      </>,
                      <>
                        Record filing initiation with its provider reference. This state is not
                        Filed, Registry accepted, or Completed.
                      </>,
                      <>
                        Link the confirmed filing event, then the separate registry-acceptance
                        event. Completion requires an accepted certificate document and a
                        confirmed next-term deadline calculated from that acceptance event.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="Calendar status never rewrites legal state">
                    When the renewal date passes, the portfolio reports Grace period or
                    Overdue and flags reconciliation. A user must still record the legal
                    transition with a reason; the report does not silently change the
                    canonical term.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    IP reports
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/reports">IP reports</a>{" "}
                    for internal portfolio register, application status, opposition status,
                    deadline control, renewal, watch, workload, data-quality, and
                    integration-freshness snapshots. Every result shows its generated time,
                    applied scope, audience, confidentiality, source freshness, row limit,
                    and snapshot hash.
                  </p>
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      Application and opposition reports retain their separate registry
                      identifiers and use the same permission-filtered portfolio reader.
                    </li>
                    <li>
                      Workload, deadline, renewal, and integration results are read from their
                      existing operational owners; generating a report does not create a second
                      docket, deadline, renewal, export, or connector record.
                    </li>
                    <li>
                      Sources that are stale, unavailable, or not activated appear as such.
                      Restricted records outside the user&apos;s access are omitted without a
                      count.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Current delivery boundary">
                    Internal previews remain transient. An IP approver may publish or
                    schedule a reviewed client-safe snapshot only to explicitly granted
                    IP records. CaseOps regenerates the preview and rejects a changed
                    snapshot; internal notes, strategy, privilege, work product, drafts,
                    AI traces, provider errors, and ungranted records are excluded.
                  </Callout>
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    IP client portal
                  </h3>
                  <p>
                    Open <a className="underline" href="/app/ip/client-portal">IP client portal</a>{" "}
                    to grant a named client selected dockets, identifier/status visibility,
                    event and date categories, approved document categories, an expiry, and
                    instruction rights. The same workspace lists active and historical grants,
                    approved-document publication, delivery state, and client instructions.
                  </p>
                  <Steps
                    items={[
                      <>Grant only the required IP docket and categories, with an expiry when appropriate.</>,
                      <>Generate and review an Internal report, select the client&apos;s active grants, then publish now or schedule delivery.</>,
                      <>Publish only an approved, non-privileged internal document version whose taxonomy category and docket are granted.</>,
                      <>Review each client instruction and accept, reject, or request clarification. A client instruction never changes legal state before firm acknowledgement.</>,
                      <>Revoke access with a reason. Active sessions are invalidated and queued publication delivery is cancelled.</>,
                    ]}
                  />
                  <h3 className="mt-8 font-display text-lg text-[var(--color-ink)]">
                    IP document workflow
                  </h3>
                  <p>
                    When the IP workspace is enabled for your firm, open{" "}
                    <a className="underline" href="/app/ip">IP docket</a> to classify,
                    name, version, and link portfolio documents without forcing them into
                    a synthetic Matter. Original bytes, filename, hash, processing result,
                    and every immutable version remain available separately from the
                    controlled display name.
                  </p>
                  <Steps
                    items={[
                      <>
                        Choose an accessible docket, file, classification, naming details,
                        document date, confidentiality, and privilege label.
                      </>,
                      <>
                        Select <strong>Preview controlled name</strong>. Review the proposed
                        name and filing state. Any changed input requires a new preview.
                      </>,
                      <>
                        Upload the reviewed document. CaseOps scans before storage, hashes
                        the bytes, and uses the shared extraction/OCR job. A duplicate hash
                        plus matching metadata offers a reusable link instead of another file.
                      </>,
                      <>
                        Move the current version through review. Approved and Filed actions
                        require the approval capability and lock the exact version, actor,
                        and time. Uploading replacement bytes creates a new version and
                        supersedes the prior one.
                      </>,
                      <>
                        Document managers preview bulk classification/name changes before
                        apply. Taxonomy administrators preview supplied law-firm aliases
                        before import.
                      </>,
                    ]}
                  />
                  <Callout tone="warn" title="Privilege and OCR are fail-closed">
                    Privileged or confidential documents cannot be used for portal sharing,
                    export, notification content, or AI retrieval through the IP document
                    policy boundary. Low or incomplete extraction disables AI/search legal
                    conclusions until the original is reviewed or a clearer version is
                    uploaded. This workflow records filing state; it does not submit a filing
                    or send a document externally.
                  </Callout>
                </Section>

                <Section id="notices" title="8 · Notices and reply deadlines">
                  <p>
                    Open <a className="underline" href="/app/notices">Notices</a> from the
                    main navigation to manage incoming and outgoing notices across the
                    workspace. A notice can be standalone, linked to one matter, or linked
                    to several matters. Existing matter attachment notices also appear in
                    this register with a clear read-only legacy label.
                  </p>
                  <Steps
                    items={[
                      <>
                        Open <strong>Notices</strong>, choose <strong>New notice</strong>, and
                        set the direction to <strong>Received</strong> or <strong>Sent</strong>.
                      </>,
                      <>
                        Record the subject, date, type, authority or counterparty,
                        department, optional owner, summary, status, and received-notice
                        reply due details where relevant.
                      </>,
                      <>
                        Optionally select any number of accessible matters. Leave every
                        matter clear when the notice is not yet associated with a case.
                      </>,
                      <>
                        Optionally attach the primary notice file. CaseOps saves the notice
                        record before uploading the file, so a file error cannot erase or
                        duplicate the notice itself.
                      </>,
                      <>
                        Track work from the register by changing an editable notice&apos;s
                        status or owner. Use linked matter chips to return to the relevant
                        matter workspace.
                      </>,
                    ]}
                  />
                  <ul className="mt-4 space-y-2 text-[15px]">
                    <li>
                      <strong>Dashboard.</strong> Received, sent, replies-due, and overdue
                      counters summarize the tenant-safe register.
                    </li>
                    <li>
                      <strong>Filters.</strong> Use received and sent tabs, full-text search,
                      status, matter, owner, and reply-due date filters.
                    </li>
                    <li>
                      <strong>Permissions.</strong> <code>documents:upload</code> enables
                      creation and first-file upload; <code>documents:manage</code> enables
                      metadata updates. Linked matter visibility remains server-enforced.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Legacy notice boundary">
                    Legacy notices created as matter attachments stay downloadable and
                    searchable in the global register, but they are read-only there. Use
                    the matter&apos;s Notices tab for its older attachment-specific reply and
                    supporting-document workflow. Sent notices do not create reply deadlines.
                  </Callout>
                </Section>

                <Section id="communications" title="9 · Communications and review queues">
                  <p>
                    Use a matter&apos;s <strong>Communications</strong> tab to review platform
                    messages, imported email, attachment references, internal notes, and
                    client- or outside-counsel-visible updates in chronological order.
                    Permitted users can log phone, meeting, note, SMS, or email activity and
                    send a template email when an approved delivery provider is configured.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Mailbox.</strong>{" "}
                      <a className="underline" href="/app/mailbox">Mailbox</a> is a Gmail and
                      Outlook metadata review queue. Link safe metadata to a matter, request
                      content import, or ignore a candidate. The queue does not import raw
                      bodies or attachment bytes by default.
                    </li>
                    <li>
                      <strong>Drive.</strong>{" "}
                      <a className="underline" href="/app/drive">Drive</a> reviews Google
                      Drive and OneDrive/SharePoint candidates. Link metadata, explicitly
                      import a file through the document safety pipeline, retry failures, or
                      ignore the candidate.
                    </li>
                    <li>
                      <strong>Notification preferences.</strong>{" "}
                      <a className="underline" href="/app/notification-preferences">
                        Preferences
                      </a>{" "}
                      controls in-app, email, SMS, and WhatsApp choices. An external channel
                      remains disabled unless its provider and delivery controls are ready.
                    </li>
                    <li>
                      <strong>Client and outside-counsel portals.</strong> External users
                      request a 30-minute one-time link at{" "}
                      <a className="underline" href="/portal/sign-in">Portal sign in</a>.
                      Clients see only explicitly granted matters. Outside counsel is routed
                      to its assigned-matter portal for permitted work product, time, and
                      invoice submission; cross-counsel visibility is off unless enabled.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Provider-gated imports and delivery">
                    Connector sync, content import, and external messaging require the
                    relevant credentials, consent, signing, and UAT evidence. A visible queue
                    or preference does not mean an external provider is active.
                  </Callout>
                </Section>

                <Section id="drafting" title="10 · Drafting with citations">
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

                <Section id="hearings" title="11 · Hearing preparation">
                  <p>
                    The Hearings tab shows manual hearings, tracked case updates, and
                    cause-list entries linked to the matter. Open the next hearing and
                    press <strong>Compile pack</strong>. CaseOps stitches a pack in under a
                    minute, from the matter record and the authority corpus:
                  </p>
                  <p className="mt-3">
                    In an IP docket, record an exact time, a named session, or
                    <strong> time not published</strong>. CaseOps keeps date-based reminders
                    active for an unpublished time and asks for the published time later;
                    it never inserts a default hearing time. Rescheduling or confirming the
                    time preserves the cancelled reminder generation and labels the current
                    replacement, so the team can inspect what changed before relying on it.
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
                      <strong>Source-backed bench context</strong> with sample size,
                      linked sources, and limitation notes where the corpus supports it.
                    </li>
                    <li>
                      The <strong>source list</strong> — every piece of content in the pack
                      is traceable back to a matter document or a named authority.
                    </li>
                  </ul>
                  <Callout title="Cause-list and tracking sources">
                    Cause-list entries land in <code>matter_cause_list_entries</code>{" "}
                    via manual entry, import, or configured lawful adapters. Only matters
                    explicitly tracked or bookmarked are included in the scheduled refresh
                    by default. The bench resolver normalises free-text rosters like
                    &quot;Justice X &amp; Justice Y&quot; into clickable judge profiles using the
                    high-quality confidence floor - no silent guesses. Per-court source
                    adapters ship only after lawful access and source-quality proof.
                  </Callout>
                </Section>

                <Section id="case-tracking" title="12 · Case tracking refresh">
                  <p>
                    Case tracking is opt-in by default. A matter with a CNR or case number
                    is eligible, but the daily job refreshes only cases that a user has
                    explicitly tracked or bookmarked. Tenant admins may later enable
                    auto-tracking for eligible matters after reviewing source coverage and
                    operational risk.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Daily window.</strong> Scheduled production runs are intended
                      to start between <strong>4 PM and 6 PM IST</strong>, with the default
                      scheduler at about 4:30 PM IST. No new provider calls start after 6 PM
                      IST unless an operator uses an explicit force or local override.
                    </li>
                    <li>
                      <strong>Backlog.</strong> Unfinished work persists and resumes on the
                      next run. Batches are fair across tenants so one tenant cannot consume
                      the entire refresh window.
                    </li>
                    <li>
                      <strong>Provider safety.</strong> Disabled or misconfigured providers
                      make no external calls. The run records skipped or blocked state
                      instead of failing silently.
                    </li>
                    <li>
                      <strong>Operations view.</strong> Admins can review attempted,
                      refreshed, changed, skipped, blocked, provider-call, error, window,
                      started, ended, partial, and backlog counts in provider operations.
                    </li>
                    <li>
                      <strong>Freshness and cost.</strong> Each bookmarked case shows its
                      provider, last attempt, last good result, next scheduled refresh,
                      freshness, response class, redacted current error, and recorded
                      refresh cost. Stale data remains visible and is labelled stale for
                      lawyer and AI review.
                    </li>
                    <li>
                      <strong>Manual fallback.</strong> Manual refresh is rate-limited,
                      cost-attributed, and disabled when provider health is red or the row
                      is quarantined. Existing evidence remains available and the page
                      directs the user to manual docketing while the connector is degraded.
                    </li>
                    <li>
                      <strong>Replay and quarantine.</strong> Admin replay is previewed,
                      tenant-scoped, limited to 25 rows, step-up protected where MFA policy
                      applies, and executed by the next bounded poll. A poison record can be
                      quarantined without stopping other cases. Incident closure requires a
                      successful canary plus root-cause and prevention evidence.
                    </li>
                    <li>
                      <strong>Disconnect.</strong> Calendar, Gmail, and Drive disconnects
                      use recent security step-up where required, revoke stored access,
                      recompute health immediately, stop future connector work, and preserve
                      prior evidence for audit and manual fallback.
                    </li>
                  </ul>
                </Section>

                <Section id="compliance" title="13 · Court-order compliance review">
                  <p>
                    Court orders can produce compliance items, tasks, and deadlines, but the
                    default workflow is review-first. Deterministic proceeding extraction
                    runs before AI. AI extraction runs only when the tenant AI policy allows
                    it, and the output must pass JSON schema validation before it creates
                    review-required compliance items.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Source-backed fields.</strong> Each item shows description,
                      responsible party, due date if supported, timeline text, filing
                      requirement, court direction, next action, source order or attachment,
                      snippet, page or paragraph, confidence label, status, review status,
                      generated task or deadline link, and dedupe key.
                    </li>
                    <li>
                      <strong>Deadline caution.</strong> Calendar-day calculations use the
                      default convention shown in the item. Court holidays are not assumed
                      unless a court calendar exists. Ambiguous phrases such as
                      &quot;from today&quot;, &quot;within two weeks&quot;, &quot;next date&quot;, or a
                      missing order date stay review-required. CaseOps never invents a due
                      date.
                    </li>
                    <li>
                      <strong>Activation.</strong> Generated tasks and deadlines stay draft
                      or review-linked unless a tenant/admin setting allows auto-activation.
                      A lawyer confirms, edits, assigns, rejects, waives, completes, or
                      retries items from the matter-level compliance panel.
                    </li>
                    <li>
                      <strong>Rejections.</strong> Rejected items do not appear as active
                      compliance, and every confirm, reject, waive, complete, and retry
                      action is audited.
                    </li>
                  </ul>
                </Section>

                <Section id="cause-list" title="14 · Date-wise cause lists">
                  <p>
                    The cause-list workspace at <code>/app/cause-list</code> creates a
                    printable date-wise list from hearings, imported cause-list entries, or
                    both. Use it for daily court preparation, team allocation, and court
                    clerk handoff.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Filters.</strong> Pick date or date range, court, practice
                      area, matter status, include/exclude disposed matters, source, and
                      sort order. Sorting includes date, court, or lawyer.
                    </li>
                    <li>
                      <strong>Required columns.</strong> Serial number, file number, court
                      name, case number, case title, judge name, court number, item number,
                      lawyers appearing, and hearing date. Missing data appears as
                      <em>Not available</em> or a preview warning instead of a blank cell.
                    </li>
                    <li>
                      <strong>Fix source data first.</strong> The page has no per-row
                      override editor. If preview data is incomplete, update the underlying
                      matter, hearing, or imported cause-list entry and run the preview again.
                    </li>
                    <li>
                      <strong>PDF audit.</strong> Each download records filters, row count,
                      actor, timestamp, checksum, and file name.
                    </li>
                  </ul>
                </Section>

                <Section id="litigation-intelligence" title="15 · Litigation Intelligence">
                  <p>
                    Litigation Intelligence is the matter-level workspace for source-backed
                    preparation and review. It pulls together proceeding sheets, affidavits,
                    mock-hearing sessions, predictive context, legal-source readiness, a
                    matter knowledge graph, and transcript-first coaching without changing
                    the rule that a lawyer reviews substantive output.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Proceeding Sheet Intelligence.</strong> Court orders and order
                      sheets are parsed from raw order text only. Next hearing dates,
                      compliance directions, affidavit deadlines, and generated tasks keep
                      the source order, snippet, confidence, and review-required status.
                    </li>
                    <li>
                      <strong>Affidavit Intelligence.</strong> Mark a document as an
                      affidavit, chief affidavit, or counter-affidavit to extract key
                      statements, dates, figures, entities, annexures, gaps, contradictions,
                      and source-grounded cross-examination questions.
                    </li>
                    <li>
                      <strong>Mock Hearing and Coach.</strong> The simulator is typed-text
                      only and uses LI affidavit question banks. The coach requires a session
                      acknowledgement and scores observable preparation markers such as
                      whether the question was answered, whether a source reference was used,
                      and whether unsupported assertions were added.
                    </li>
                    <li>
                      <strong>Predictive and bench context.</strong> Predictive Intelligence
                      shows observed historical patterns only when indexed source evidence
                      exists. Supported signals display sample size, confidence band, source
                      links, snapshot references, and limitation notes.
                    </li>
                    <li>
                      <strong>Review queue and knowledge graph.</strong> The Litigation
                      Intelligence review page groups pending review items and lets permitted
                      users accept, reject, mark reviewed, or edit notes. The knowledge graph
                      materializes matter-scoped nodes and edges from source-backed LI records
                      with bounded snippets.
                    </li>
                    <li>
                      <strong>Strategy Plan.</strong> The matter strategy surface lays out
                      current posture, primary and alternative routes, forum sequence,
                      recommended draft pack, missing facts, risks, authorities, and a
                      lawyer-review workflow. It remains decision support, not an automatic
                      filing instruction.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Decision support, not legal advice">
                    These tools are preparation and review aids. They do not replace legal
                    judgment, do not create court filings automatically, and do not use audio,
                    voice analysis, emotion detection, biometric signals, psychological
                    scoring, mental-health inference, or broad external scraping.
                  </Callout>
                </Section>

                <Section id="bench-strategy" title="16 · Bench-aware appeal drafting">
                  <p>
                    When you generate an{" "}
                    <strong>appeal_memorandum</strong> draft for a matter that has
                    an upcoming listing, CaseOps doesn&apos;t just pull authorities
                    from the court at large — it pulls authorities authored by{" "}
                    <strong>the specific bench scheduled to hear the appeal</strong>{" "}
                    and prefers ones that align with the matter&apos;s practice area.
                    The advocate-bias selection is editorial: the system surfaces
                    the citations that support your grounds. Adverse-authority
                    duties to the court remain yours.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Career timeline</strong> on every judge profile —{" "}
                      <code>/app/courts/judges/&#123;id&#125;</code> shows every
                      court the judge has served on, with source-attributed
                      evidence.
                    </li>
                    <li>
                      <strong>Bench resolver</strong> on the matter hearings tab
                      — &quot;Justice X &amp; Justice Y&quot; renders as clickable
                      links to each judge&apos;s profile.
                    </li>
                    <li>
                      <strong>Appeal Strength panel</strong> on the appeal stepper
                      flags per-ground citation coverage and weak-evidence paths.
                    </li>
                  </ul>
                  <Callout tone="warn" title="No outcome-forecast copy">
                    Bench-aware drafting stays on source selection, citation coverage,
                    and limitation notes. Selection of supporting citations is allowed and
                    required - that&apos;s what advocates do - but the system never claims
                    an outcome.
                  </Callout>
                </Section>

                <Section id="statutes" title="17 · Statutes and sections">
                  <p>
                    Visit <code>/app/statutes</code> to browse the structured
                    catalog of central Indian Acts. The committed catalog as of 11 July
                    2026 contains 23 Acts and 3,393 sections, including the Constitution,
                    BNSS, BNS, BSA, CrPC, IPC, CPC, major commercial and regulatory Acts,
                    and source links to{" "}
                    <a
                      href="https://www.indiacode.nic.in"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      indiacode.nic.in
                    </a>{" "}
                    — the Government of India&apos;s official Acts repository
                    (public domain).
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Attach to a matter.</strong> The Statutes sub-tab on
                      the matter cockpit lets you mark which sections this matter
                      cites, opposes, or holds in context.
                    </li>
                    <li>
                      <strong>Fed into drafting.</strong> When you generate an
                      appeal-memorandum draft, the prompt receives the bare text
                      of each attached section. The LLM is instructed to{" "}
                      <strong>quote verbatim</strong> instead of paraphrasing.
                    </li>
                    <li>
                      <strong>BNSS vs BNS unambiguous.</strong> The structured
                      reference makes the act explicit, so &quot;Section 483
                      BNSS&quot; (bail) is never confused with &quot;Section 483
                      BNS&quot;.
                    </li>
                  </ul>
                  <Callout title="Bare text indexing">
                    Section number + label + source URL ship with the catalog
                    today. Bare text for the most-litigated sections is being
                    enriched from indiacode.nic.in; until a section&apos;s text is
                    indexed, the prompt and UI surface the source URL so you can
                    verify directly.
                  </Callout>
                </Section>

                <Section id="research" title="18 · Research and authorities">
                  <p>
                    Open <code>/app/research</code> from the left navigation to run
                    open-ended queries without tying the query to a specific draft. Choose
                    the CaseOps corpus or, where your workspace has completed every provider
                    gate, the licensed Indian Kanoon API.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Query.</strong> Natural language works best — phrase the
                      issue, not a keyword. Example: <em>triple test for anticipatory bail
                      under BNSS s.482</em>.
                    </li>
                    <li>
                      <strong>Results.</strong> Authority cards show the available title,
                      citation, publisher, court/date metadata, extract, and source action.
                      Licensed results also show required attribution, cache freshness,
                      provider cost, and unreviewed authority/binding status.
                    </li>
                    <li>
                      <strong>Save.</strong> Saving a result creates a tenant-private entry
                      in the workspace research notebook. It is not automatically attached
                      to the matter currently open in another tab.
                    </li>
                    <li>
                      <strong>Licensed source.</strong> Indian Kanoon access is disabled by
                      default. Contract and terms approval, server-only credentials,
                      permitted uses, retention, legal coverage, approved actual cost
                      profiles, and daily/monthly budgets must all pass before CaseOps makes
                      a request. CaseOps never scrapes Indian Kanoon public pages.
                    </li>
                  </ul>
                  <Callout title="No result, unavailable, and changed sources">
                    A genuine zero-result is separate from disabled access, expired terms,
                    quota or budget exhaustion, authentication failure, provider outage,
                    removed content, and a changed provider contract. A bounded stale cache
                    is labelled during an outage. Imported content is hashed; a changed
                    version resets two-person legal review and invalidates linked frozen
                    research reports.
                  </Callout>
                </Section>

                <Section id="contracts" title="19 · Contracts and playbooks">
                  <p>
                    Contracts live in the top-level <strong>Contracts</strong> workspace.
                    A contract record can hold its document, extracted clauses, playbook
                    comparison, obligations, and a parsed redline view.
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
                      <strong>Redlines.</strong> Upload a DOCX with tracked changes to parse
                      and review additions/deletions in CaseOps. The current surface does not
                      export a newly tracked Word document or claim version lineage.
                    </li>
                  </ul>
                </Section>

                <Section id="recommendations" title="20 · Recommendations">
                  <p>
                    CaseOps produces explainable recommendations — forum choice, supporting
                    authorities, next best action — with rationale, assumptions, missing
                    facts and a confidence label. Recommendations must show the source
                    trail and limitation note before anyone accepts them.
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

                <Section id="outside-counsel" title="21 · Outside counsel and spend">
                  <p>
                    General Counsel teams run <strong>Outside counsel</strong> from the
                    top-level navigation. The live directory records counsel and firm
                    profiles, contacts, jurisdictions, practice areas, panel status, and
                    notes. A matter can carry one or more counsel assignments.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Profiles.</strong> Add and maintain the panel identity,
                      contact information, jurisdiction, and practice-area coverage used
                      when selecting counsel.
                    </li>
                    <li>
                      <strong>Assignments.</strong> From a matter&apos;s Outside Counsel
                      surface, assign a panel record and record the fee arrangement, budget,
                      scope, dates, and assignment status supported by the form.
                    </li>
                    <li>
                      <strong>Spend and payment state.</strong> Record assignment-level
                      spend and payment status where available. The current UI does not
                      promise rate cards, outcome history, generated brief packets, budget
                      alert enforcement, realization, or aging roll-ups.
                    </li>
                  </ul>
                </Section>

                <Section id="billing" title="22 · Matter billing and invoices">
                  <p>
                    Matter billing is separate from CaseOps SaaS subscription billing.
                    Tenant admins configure law-firm billing at
                    <code>/app/admin/matter-billing</code>, then users generate invoices
                    from unbilled matter work, expenses, fixed fees, milestones, retainers,
                    advance adjustments, and manual line items.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Profiles.</strong> Store firm legal name, address, GSTIN,
                      PAN, invoice prefix and sequence, default currency, payment terms,
                      default SAC/HSN or service classification, footer/note, and logo or
                      header where tenant branding supports it.
                    </li>
                    <li>
                      <strong>Rates and arrangements.</strong> Resolve hourly rates by
                      user, role, practice area, or default. Fixed-fee matters, milestone
                      templates, retainers or advances, expense/reimbursement categories,
                      and manual line items can be added where applicable.
                    </li>
                    <li>
                      <strong>Tax and adjustments.</strong> Tax is calculated server-side
                      from invoice data: client billing name/address/GSTIN where available,
                      place of supply, taxable value, CGST/SGST/IGST split, totals, grand
                      total, amount paid, outstanding amount, and TDS deduction/payment
                      adjustment fields where recorded.
                    </li>
                    <li>
                      <strong>Double-billing guard.</strong> Time entries already attached
                      to an invoice cannot be billed again unless the original invoice path
                      is voided or adjusted under the tenant's audit rules.
                    </li>
                    <li>
                      <strong>PDF export.</strong> Downloadable invoice PDFs are rendered
                      server-side from stored invoice data. Invoice downloads and billing
                      profile or rate changes are audited. External payment links are used
                      only when a tenant has explicitly configured an approved provider.
                    </li>
                  </ul>
                </Section>

                <Section id="admin" title="23 · Admin, audit and access controls">
                  <p>
                    Admins run the workspace from <code>/app/admin</code>. The important
                    subsections are <strong>Employees</strong>, <strong>Roles</strong>,{" "}
                    <strong>Teams</strong>, <strong>AI policy</strong>, provider and connector
                    operations, <strong>Audit export</strong>, and{" "}
                    <strong>Matter billing</strong>. CaseOps SaaS subscription billing stays
                    separate from matter/client billing.
                  </p>
                  <ul className="mt-3 space-y-2 text-[15px]">
                    <li>
                      <strong>Employees and roles.</strong> Add employees, assign built-in or
                      custom roles, update employment state, and review per-employee matter
                      access. Prior activity remains attributed after deactivation.
                    </li>
                    <li>
                      <strong>Teams.</strong> Organize employees for practice and operational
                      workflows; continue to enforce permissions and matter access through
                      the server-side capability model.
                    </li>
                    <li>
                      <strong>AI policy.</strong> Cap the providers, models and context
                      shapes the workspace is allowed to use. AI actions outside the policy
                      are blocked before any token is spent.
                    </li>
                    <li>
                      <strong>Provider operations.</strong> Review scheduled case-tracking
                      runs, blocked/skipped reasons, provider-disabled states, last attempt,
                      last good state, response class, freshness, partial backlog, refresh
                      window, and per-tenant batching metrics. Replayable rows require a
                      short-lived scope-and-cost preview before an audited confirmation;
                      enrolled MFA also requires recent step-up.
                    </li>
                    <li>
                      <strong>Matter billing.</strong> Manage billing profiles, rate cards,
                      invoice numbering, tax split settings, expense categories, and invoice
                      templates for law-firm matter billing.
                    </li>
                    <li>
                      <strong>Audit export.</strong> JSONL or CSV for any date range. Large
                      exports run as background jobs; download when complete.
                    </li>
                  </ul>
                  <Callout tone="warn" title="Status-gated admin surfaces">
                    The dedicated ethical-walls UI is marked Coming soon on the Admin page.
                    Do not promise self-service wall creation or dissolution until that
                    surface and its production evidence are live.
                  </Callout>
                </Section>

                <Section id="security" title="24 · Security and data boundaries">
                  <p>
                    Security is not a tab — it is the way every other tab is built. The
                    short version:
                  </p>
                  <ul className="mt-3 list-disc space-y-2 pl-6 text-[15px]">
                    <li>
                      <strong>Tenant-private data isolation</strong> at query and storage
                      boundaries. Shared public authority records remain deliberately
                      separate from tenant-owned records and embeddings.
                    </li>
                    <li>
                      <strong>Matter access restrictions</strong> are enforced server-side
                      in addition to the workspace role and capability grid.
                    </li>
                    <li>
                      <strong>Audit on material and sensitive events</strong> — including
                      administrative changes, exports, AI runs and review decisions,
                      recommendation decisions, document activity, and payment state changes
                      where implemented.
                    </li>
                    <li>
                      <strong>Provider and AI data minimisation.</strong> Tenant-facing
                      screens do not expose provider tokens, raw provider payloads, raw
                      prompts, raw LLM responses, internal costs, or tenant-private data
                      to unauthorized users.
                    </li>
                    <li>
                      <strong>Notification safety.</strong> Scheduled job failures,
                      compliance review events, and provider-blocked states create durable
                      in-app notification intents. Email, SMS, and WhatsApp delivery are
                      not sent unless an approved provider is explicitly configured.
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

                <Section id="troubleshooting" title="25 · Troubleshooting">
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
                    The query may be too generic (<em>bail</em>) or the indexed corpus may
                    not cover that jurisdiction and year. Rewrite with the issue, statute,
                    forum, and date range rather than assuming the system will narrow it.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A colleague cannot see a matter I opened
                  </h3>
                  <p>
                    Ask an owner or admin to review the employee&apos;s built-in/custom role,
                    capabilities, active status, and matter access under Admin → Employees.
                    The dedicated ethical-walls UI is not yet a live self-service remedy.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A tracked case was skipped
                  </h3>
                  <p>
                    Open provider operations. Skipped and blocked runs show the reason:
                    outside the 4 PM-6 PM IST window, provider disabled, missing
                    configuration, source blocked, tenant batch limit, or backlog carried
                    forward. Disabled providers make no external calls. A configured
                    connector with no recent successful check is shown as unhealthy, never
                    as healthy merely because it is enabled. Preview any replay, review its
                    bounded scope and cost basis, then confirm and monitor the durable job.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A compliance due date is missing
                  </h3>
                  <p>
                    Check the source snippet and confidence label. Ambiguous text, missing
                    order date, missing court calendar, or phrases like &quot;next date&quot;
                    keep the item review-required. Add the date manually only after lawyer
                    review; CaseOps will not invent one.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A rejected compliance item still appears active
                  </h3>
                  <p>
                    Refresh the matter compliance panel and inspect the review status. A
                    rejected item should not appear as active compliance. If it does, export
                    the audit trail for the matter and contact support with the item ID.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A notice reply deadline is missing or still open
                  </h3>
                  <p>
                    Confirm the record is a primary received notice, <em>Reply required</em>
                    is enabled, and a reply due date is present. To complete the linked
                    deadline, upload via <strong>Reply document</strong> or use{" "}
                    <strong>Mark reply sent</strong>; a supporting document alone does not
                    change reply status.
                  </p>
                  <h3 className="mt-6 font-display text-lg text-[var(--color-ink)]">
                    A cause-list PDF has missing fields
                  </h3>
                  <p>
                    The preview must show <em>Not available</em> or a warning for missing
                    serial number, file number, court, case number, title, judge, court
                    number, item number, lawyers appearing, or hearing date. Correct the
                    underlying matter, hearing, or imported cause-list record, then preview
                    again before downloading; the page has no per-row override editor.
                  </p>
                </Section>

                <Section id="glossary" title="26 · Glossary">
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
                      <dt className="font-semibold text-[var(--color-ink)]">Matter access restriction</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        Server-enforced visibility below the workspace role/capability layer.
                        Employee matter access is live; the dedicated ethical-walls admin UI
                        remains status-gated.
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
                      <dt className="font-semibold text-[var(--color-ink)]">Disposed</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        The canonical backend status for a completed matter. The UI action
                        is <strong>Dispose</strong>; API responses emit <code>disposed</code>.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">Tracked case</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A matter-linked case a user explicitly bookmarked for scheduled
                        refresh. Eligible CNR or case-number matters are not refreshed by
                        default unless tracked or a tenant admin enables auto-tracking.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">
                        Compliance review item
                      </dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A source-backed court-order direction that requires lawyer review
                        before it becomes active compliance, a task, or a deadline.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">
                        Next-hearing suggestion
                      </dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A provider or intelligence-derived date that conflicts with the
                        current matter header or a manual lock. It must be accepted before
                        replacing the displayed next hearing.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">
                        Cause-list PDF
                      </dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A black-and-white, date-wise court table generated from hearings and
                        cause-list entries, with missing-field warnings and audited
                        downloads.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-semibold text-[var(--color-ink)]">TDS adjustment</dt>
                      <dd className="text-[var(--color-ink-2)]">
                        A recorded deduction or payment adjustment against a matter invoice.
                        It is tracked as invoice data and does not change the rule that tax
                        calculations are server-side.
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
