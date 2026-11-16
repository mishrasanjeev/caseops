# Owner-supplied pleading and conveyancing formats

## Scope and status

The owner requested a separate PR on November 15, 2026, using the supplied
`Drafting-Pleadings-and-Conveyancing.pdf` throughout pleading and format
generation. This branch is isolated from the existing GitHub-bug candidate.
Implementation and verification are in progress; this is not a release claim.
The owner subsequently confirmed that this separate PR should add all applicable
formats from the PDF, including those not previously offered by CaseOps.
The owner has now explicitly requested PR creation while the shared test window
is still held. Publish this work as a draft stacked on PR621, with verification
pending. After the parent merges, retarget to canonical main and complete the
required checks before marking it ready for review or merging.
The owner subsequently requested completion through green CI, main merge and
production deployment. Those steps remain pending the explicit shared-window
handoff and successful required verification; draft publication is not sign-off.

PRD ownership: J07/M06, MOD-TS-008 and MOD-TS-012; US-017/018/019/020/021,
FT-025..033. Existing IP drafting retains J08/M08 and its immutable docket,
source-version, template and approval controls. This extends existing drafting
formats; it does not create another document system.

## Source identity

- Owner-supplied file: `Drafting-Pleadings-and-Conveyancing.pdf`.
- SHA256: `cc50806727ff07306d6fe0b0bceee500061edb10577b9c350b63e31ce35c6cd0`.
- Size: 921839 bytes; 99 PDF pages.
- Page references in this work use the PDF page index, starting at 1.
  Printed page numbers differ and contain gaps. The supplied extract starts
  at printed page 10 and ends at printed page 133; it is not a complete book.
- Source text was independently extracted with pypdf and PDFium. pypdf warned
  about unavailable optional CFF font decoding; PDFium text and rendered pages
  are the layout reference. The original PDF is retained outside the repository.

Only reusable structures are adapted. Do not ship the complete supplied book,
sample clients, sample disputes, fixed addresses, invented amounts or dates as
product content. An instructional sample is not evidence of current procedural
law, applicable court rules, jurisdiction, limitation or an actual execution.

## Existing surfaces requiring reconciliation

| Surface | Current source | Required result |
|---|---|---|
| Guided template discovery and facts | `schemas/drafting_templates.py`, `api/routes/drafting.py` and web drafting types/forms | The selected document family has an appropriate format and input fields. |
| Step previews | `services/drafting_preview.py` | Partial previews use the same selected format, with explicit missing fields and only the requested step. |
| Full generation and regeneration | `services/drafting.py`, `services/drafting_prompts.py` | Consistent headings, parties, paragraph numbering and execution/verification blocks; current source and citation controls remain effective. |
| IP pleadings | `_build_ip_drafting_messages`, governed IP template manifests | Registry-specific forms and immutable identifiers take precedence; ordinary court captions must not replace them. |
| Word export | Existing shared drafting export in `services/drafting.py` | Readable filing layout, preserved approved body, signatures and schedules, appropriate page layout and numbering. |
| PDF preview/export | `services/draft_pdf_export.py` and its existing callers | Match the same current draft body and document family; preserve Unicode, pagination and unsupported-glyph refusal. |
| Notices, replies and conveyancing | Current drafting and any separate active generation callers, to be fully inventoried | Notices use correspondence structure; deeds use recitals, operative terms, schedules and execution blocks. |

The base guided registry contains 31 template types. A family without a direct
example in the supplied PDF may inherit common presentation conventions, but
must not be labelled as an exact book form. Six deed examples are present:
sale (PDF79-81), mortgage (82-83), partnership (84-85), dissolution (86-87),
relinquishment (88-89) and gift (90-92). Guided availability and adjacent typed
consumers must be reconciled before claiming those formats are supported.

## Source-backed structural examples

| PDF pages | Format |
|---|---|
| 1-3 | Recovery plaint: court, parties, numbered facts, jurisdiction/value, lettered prayers, signatures and verification. |
| 4, 40 | Supporting affidavit: deponent identity, numbered statements, verification and execution placeholders. |
| 5-7, 13-17 | Injunction, ejectment and specific-performance plaint structures. |
| 8-12 | Interim applications and procedural application formats. |
| 18-20 | Written statement: preliminary objections, paragraph-wise merits response, prayer and verification. |
| 21 | Caveat: caption, apprehended proceeding, service details and caveator/signature block. |
| 22-28 | Transfer and execution applications. |
| 29-30 | Matrimonial drafting introduction, including a list of possible reliefs; these pages contain no separate worked nullity, child-custody or interim-alimony form. Their historical legal statements are not treated as verified current law. |
| 31-39 | Matrimonial petitions: marriage particulars, facts, distinct grounds, relief and verification. |
| 41-48 | Probate, letters of administration and succession-certificate structures, including the supplied estate particulars, supporting statements and verification. |
| 49-54 | Civil and criminal writ petition structures. |
| 55-62 | Civil and criminal special-leave petition structures. |
| 63-68 | Bail, anticipatory bail and complaint formats; statutes in historical examples are not automatically adopted. |
| 69-73 | Maintenance application and consumer complaint, using supplied current law and forum particulars. |
| 74-78 | Contempt and domestic-violence complaint structures. |
| 79-92 | Conveyancing: instrument title, date/place, parties and capacities, recitals, operative numbered terms, schedules and execution. |
| 93-99 | Advocate notices and replies: sender/date/service, addressee, subject, numbered account/demand or paragraph-wise response and signature. |

These references identify presentation families. They do not certify the legal
propositions, sample fact patterns or historical enactments inside those pages.

### Worked-format map

Every worked format in the supplied extract has an explicit guided destination
below. The two supporting affidavits share the affidavit destination. This is a
source coverage map; all runtime acceptance remains pending.

| PDF pages | Worked format | Guided destination or choice |
|---|---|---|
| 1-3 | Summary recovery plaint | Civil suit: Summary recovery |
| 4, 40 | Supporting affidavit | Affidavit |
| 5-7 | Permanent injunction | Civil suit: Permanent injunction |
| 8-9 | Temporary injunction | Interim relief application |
| 10-11 | Breach of injunction | Injunction breach application |
| 12 | Indigent-person application | Application to sue as an indigent person |
| 13-15 | Ejectment and damages | Civil suit: Ejectment and damages |
| 16-17 | Specific performance | Civil suit: Specific performance |
| 18-20 | Written statement | Written statement |
| 21 | Caveat | Caveat petition |
| 22-26 | Transfer application/petition | Transfer petition |
| 27-28 | Execution application | Execution application |
| 31-32 | Restitution of conjugal rights | Restitution of conjugal rights |
| 33-34 | Judicial separation | Judicial separation petition |
| 35-37 | Divorce | Divorce petition |
| 38-39 | Divorce by mutual consent | Joint mutual-consent divorce |
| 41-43 | Probate | Probate petition |
| 44-46 | Letters of administration | Letters of administration |
| 47-48 | Succession certificate | Succession certificate |
| 49-50 | Civil writ | Writ petition: civil |
| 51-54 | Criminal writ | Writ petition: criminal |
| 55-58 | Civil special leave | Special leave petition: civil |
| 59-62 | Criminal special leave | Special leave petition: criminal |
| 63-64 | Regular bail | Bail application |
| 65-66 | Anticipatory bail | Anticipatory bail |
| 67-68 | Cheque dishonour complaint | Cheque-bounce complaint |
| 69-70 | Maintenance | Maintenance application |
| 71-73 | Consumer complaint | Consumer complaint |
| 74-75 | Contempt | Contempt petition |
| 76-78 | Domestic violence | Domestic-violence complaint |
| 79-81 | Sale | Conveyancing deed: Sale deed |
| 82-83 | Mortgage | Conveyancing deed: Mortgage deed |
| 84-85 | Partnership | Conveyancing deed: Partnership deed |
| 86-87 | Partnership dissolution | Conveyancing deed: Dissolution of partnership |
| 88-89 | Relinquishment | Conveyancing deed: Relinquishment deed |
| 90-92 | Gift | Conveyancing deed: Gift deed |
| 93 | Notice to quit/ejectment | Property notice: Notice to quit / ejectment |
| 94-95 | Notice before government suit | Government-suit notice |
| 96-97 | Cheque dishonour notice | Cheque-bounce notice |
| 98-99 | Reply to legal notice | Legal-notice reply |

## Current implementation checkpoint

The prospective registry has 46 guided types: the original 31, one conveyancing
type with six deed choices, and 14 additional source forms. The additions cover
injunction breach, indigent-person and execution applications; restitution,
judicial separation and joint mutual-consent divorce; letters of administration,
succession certificate, cheque-bounce, maintenance, consumer and domestic-violence
applications/complaints; government-suit notice and notice reply. Each has an
explicit source-page mapping and its own ordered particulars. The execution
format retains the ten labelled decree/execution particulars; consumer forms
must use confirmed current forum/law rather than the historical sample.

The existing civil plaint has an optional selector for general, summary recovery,
permanent injunction, ejectment/damages and specific performance. The existing
SLP civil/criminal selector is retained. Writ petitions now distinguish civil
and criminal proceedings; property notices distinguish the general dispute
structure from notice to quit/ejectment, with supplied occupation and notice
requirements. These are optional selectors in existing families, preserving
old free-form admission. Shared source-choice validation rejects unknown supplied
choices before writes or retrieval/provider work. The criminal writ caption is
not forced into a civil case number, and a reply deadline is never substituted
for the applicable termination period. Saved references narrow their source
pages only when an actual choice is supplied; unspecified free-form writs/SLPs
are not labelled civil. General/adapted decisions are distinguished from a direct
worked example. The selected deed supplies the title and `other` category;
the new correspondence types use `notice` and `reply` respectively.

Partial previews permit an absent selection, but refuse an invalid supplied
choice before provider construction. Creation and generation validate the new
forms' required facts at the server before writing or paid retrieval/generation.
Public errors keep field locations/messages and exclude submitted input/context.
This does not alter admission for existing free-form callers. Required governing
law fields avoid hardcoding historical enactments for the new forms.

Shared prompt instructions now reach guided preview, generation and regeneration,
generic drafts and the separate IP builder. New generated versions capture the
reference version, source hash and selected PDF pages in their template manifest.
Older versions are not backfilled; manual edits retain the version's provenance.

New reference versions use their own approved-body caption/title in Word/PDF,
shared semantic heading/signature decisions, A4 dimensions, margins, page numbers
and retained Unicode rendering. Product/revision metadata moves to document
properties instead of becoming legal body text. Word's keep-with-next and PDF's
measured wrapped-heading height protect heading boundaries; actual render proof
is still owed. Registry profiles retain their governed header/margins. Legacy
versions keep their prior presentation and are not silently relabelled.

The execution application's ten particulars use a real three-column Word/PDF
table (number, particular, answer), following PDF pages 27-28. The final visual
source pass corrected an earlier two-column interpretation from extracted text.
`drafting_format_blocks.py` separates the existing number, label and value
without rewriting them; its retained original lines
allow a byte-for-byte body reconstruction. It accepts the supported numbered-row
styles, ordered continuation lines and explicit missing-value placeholders.
Missing, repeated, out-of-order or ambiguous rows are refused with a static
actionable message, without echoing private values. Approval, finalization and
each export path validate that same saved execution structure before mutation
or document rendering. This new-format guard does not relabel legacy versions
and does not certify legal sufficiency.

Word uses fixed-width columns, black borders and top-aligned cells. PDF measures
the actual label/value lines and splits long values across pages, retaining each
label once and preserving the complete source order. The authored regressions
cover supported numbering, malformed structure with zero renderer starts,
approval/finalization refusals with unchanged retained state, repaired-version
review, and long Unicode values across pages. These table changes are newer
than the historical first syntax receipt. The current 19-file syntax check now
passes, but these rendering and workflow paths have not been executed.
The source visual pass also preserves each deed's own party-introduction style:
BETWEEN/AND for sale, partnership, dissolution and gift; BY/IN FAVOUR OF for
mortgage and relinquishment. Joint matrimonial particulars distinguish supplied
status, age and residence at the two relevant stages; the domestic-violence
format preserves supplied children's particulars without copying the sample.

New notice/deed/reply references use generic document layout by default, with no
inferred court caption, court-field findings or court-bundle actions. The UI and
bundle service both enforce that distinction. Legacy versions retain their prior
court controls. Existing citation, review, source, access and finalization gates
remain in force, including zero-citation approval refusal. A new deed format is
not an exception to that approval rule or a legal-validity certification.

Source tests now cover the original registry consumers, new facts/pickers,
provenance, safe rejection before provider work, generation/regeneration/manual
edit/history/reload, actual Word/PDF bytes and semantic layout. The offline
evaluators include all new source fixtures and separate correspondence/deed
structure rubrics. Lexical structure scores and synthetic catalogue matches
cannot establish legal proposition accuracy or real-model format fidelity.
The shared synthetic fixture now contains 31 workflow scenarios: 14 added forms,
six deeds, all five civil-plaint choices, and both choices for each existing
SLP, property-notice and writ family.
Preview and full-generation fixtures now use their actual separate transport
contracts: plain partial text for preview and structured JSON for generation.
Every positive journey asserts the exact partial-preview response and all three
marked provider observations. These strengthened assertions remain unexecuted.
All four optional selector families also have authored HTTP admission and
retained-input generation refusals, with zero provider/retrieval work and
unchanged persisted counts. These remain unexecuted expectations.

Two new loopback-only browser journeys are authored with exact literal identities
in both the Python evidence contract and independent frontend inventory. Intended
App inventory is 792 (728 desktop, 64 phone), preserving all previous 790 and
21 explicit historical skips. These are configured counts, not collected/executed
results. The journeys use the configured project's mobile/touch mode, existing
exact-owned synthetic fixture, marked HTTP clients, retained history and actual
version-pinned PDF canvas/download bytes. Production mutation remains refused.
The deed picker starts without a selected instrument. The browser source proves
the intended blank-choice rejection before creation and then exercises all six
choices. Word download verification uses the browser's normal attachment path,
checks the exact source URL, single request and successful stream, then reads the
downloaded OOXML body and provenance. It neither refetches nor fulfills a response
from a test-owned buffer. The request observer checks the complete original
browser headers for session-cookie presence and the no-paid marker, without
logging credentials or substituting the setup API token. This follows Playwright's
[complete-header contract](https://playwright.dev/docs/api/class-request#request-all-headers)
and [download API](https://playwright.dev/docs/api/class-download). This is
authored, unrun coverage, not a successful browser or document-rendering result.
Only the new owned synthetic journeys opt into retaining the actual downloaded
Word file, displayed PDF and a canvas PNG for every rendered page. The shared
PDF helper's callback is optional; existing production probes do not acquire
private document screenshots through this change. Full text, bounds, contrast
and pagination assertions remain unchanged.

## Active-generation source audit

| Consumer | Source decision |
|---|---|
| Matter routes and `assistant_actions` Matter drafts | Both use `create_draft` and the shared full-generation builder. Assistant-created untitled-type shells get the generic family-aware reference on generation. |
| IP routes and assistant IP drafts | Both use the existing governed IP target/builder; preserve immutable template, docket/proceeding and source-version manifests. |
| Guided preview, normal generation/regeneration and manual revision | Shared format instructions, new-version capture and retained manual-edit provenance. No regeneration of an older version's metadata during download. |
| `notices.py` | Notice register, attachments and lifecycle; it does not generate a notice body. Do not inject drafting prompts into its stored uploads. |
| `contract_intelligence`, intelligent reviews and file Q&A | Extraction, analysis and answers about supplied documents; these are not conveyancing/pleading generation paths. |
| `hearing_packs`, Matter summaries, recommendations and litigation strategy | Summaries, action items and recommendations. They do not independently generate a full court document; resulting draft workflows use the shared drafting service. |
| Workspace assistant | Answers/proposals; accepted draft actions flow through `assistant_actions`, not an independent pleading renderer. |
| Native mobile draft screen/repository | `DraftScreen.tsx` is explicitly read-only; repository calls are GETs and the decoder selects the saved current body/citations. There is no separate template picker, preview/generator or document renderer to modify. This is a source audit, not native-device acceptance. |
| Corpus/statute enrichment, retrieval normalization, reranking and predictive analysis | Retrieval/metadata/analysis outputs, not document formatting. No presentation prompts added. |
| Provider abstraction/cassettes | Transport/offline fixtures; no global prompt mutation. A deterministic response is not proof of model quality. |
| Three drafting evaluation CLIs | Actual full service or shared prompt builders; the type/quality fixture loaders now include the additional formats. No paid evaluation has run. |
| DOCX, PDF preview/download and retained filing-bundle documents | Shared saved-version reference. Deterministic placeholder/index bundle documents remain explicitly legacy/placeholder content. |

Generated OpenAPI/client refresh, actual Word/PDF visual rendering, execution of
the authored provider/HTTP integration tests and browser journeys, and required
release checks remain pending. The first cache-only setup failed because
`dnspython==2.9.2` was absent; its failure and historical 18-file syntax receipt
are retained. A later explicit ten-minute preparation exception allowed online
frozen dependency setup and syntax/Ruff only. Python 3.13.14 installation then
completed with `UV_LINK_MODE=copy` after retaining an initial Windows hardlink
error 396. The then-current 19 Python files and new JSON fixture passed isolated
syntax checks. Full API/evidence-script Ruff passed after 12 import/line-length fixes.
The dependency locks remain unchanged. These are scoped preparation results,
not application or schema execution.

Pinned Node 22.23.4 trust preparation passed. Its exclusively owned `npm ci`
did not finish and was interrupted; the Node installation is incomplete and
cannot be used for gates. Final process reconciliation at12:34:37UTC was later
than ten minutes after the first clock observation at12:24:19UTC. The aggregate
slot result is therefore incomplete; the late return and initial incorrect
on-time wording are preserved and corrected. Zero owned tree candidates were
observed at reconciliation. No CaseOps/schema/OpenAPI import, pytest, TSC,
server, DB/browser, Docker, hosted CI, push, PR or deployment ran. The wider
reservation remains in force.

Later source edits supersede those checks for the edited inputs. There are now
24 changed Python files, including an explicit PostgreSQL wrapper and changes
to existing build-context regressions. Several schema/reference, workflow and
rendering inputs changed after the recorded syntax/Ruff pass. New required text
particulars strip whitespace before validation; the HTTP missing-law negatives
also reject whitespace-only input without writes or reflected private values.
These are unexecuted assertions, not a passed validation claim.
The normal `client` fixture always uses SQLite. The PostgreSQL module therefore
replays all 31 positive and 13 negative cases through the existing canonical
`isolated_postgres_client`, whose database is migrated and independently owned.
The intended counts are 44 SQLite and 44 PostgreSQL cases; neither inventory has
been collected or executed. No environment-URL substitution is claimed as
cross-dialect coverage.

The new browser file now loads canonical API validators inside its journey,
with a matching case in the existing deferred-validator source guard. JSZip is
also loaded only when inspecting the actual downloaded Word file. The shared
PDF helper's configured touch mode has been propagated to the original dated
drafting file and production helper. The complete original November 11 browser
file, the new November 15 file and the changed frontend guard remain unrun.

At 13:47 UTC the shared reservation had no observed release. Parent PR621 had
advanced to `c29b2199b6fea467c7592dab50c4b01f5d818022`; its mobile workflow failed
the native-evidence harness and built-browser E2E typecheck, while later steps
were skipped. The coordinator's 13:34 handoff retained earlier candidate failures
and scoped repairs, with canonical full21 unstarted. These parent results do not
certify or reject this feature's separate source. Chat checks subsequently timed
out, and the latest handoff/preparation request has no observed delivery or
grant. No further dependency setup, application imports or tests were started.

The coordinator subsequently explicitly reaffirmed the hold: no new local
preparation, tests, servers, Docker, CI, main merge or deployment is handed over.
Static source work may continue, with a later explicit handoff promised after
PR621's critical gates. The new frontend AST guard's literal source-file read
now participates in the existing dynamic builder dependency inventory. That
exact browser file has builder-only COPY, Docker/gcloud allowlist, deployment
dirty-fence, native-source fingerprint and mobile-source trigger entries.
Existing independent upload, fingerprint and dirty-context tests were expanded;
no new native unittest method was added or existing count silently changed.
All those gates remain unrun. The parent's pending two PDF-support COPY repairs
are not duplicated here; reconcile them after rebasing onto actual canonical
main. Current source is unfrozen: 50 changed/untracked paths, including 24 Python
files, as recorded in the external source-state-06 snapshot before this note.

The older all-GitHub-bugs candidate remains separate and unverified. Its source
plan adds ten cases to the parent's 790-case App inventory, whereas this feature
adds two. If those bug repairs merge first without other inventory changes,
the combined expected inventory would be 802, not this branch's current 792.
Reconcile exact identities and role counts against actual canonical main after
each merge; do not copy a prospective count across branches or treat it as a
collected result. The older Windows cold-collection and npm-preparation findings
remain open and need their original bounded diagnostics and complete inventories.

At the November 15 11:07 UTC coordination checkpoint, the owner had published
PR621 source `7000424d554151f22f480c2a503d2643841be7fa` and stopped the next
Docker launch at a new API CI failure. That is a source-bound failed gate, not
an available test window. The owner explicitly declined online dependency,
type/lint/OpenAPI and application-test work pending a handoff. This feature
remains uncommitted on its isolated `724786c9` base. No later implementation
claim supersedes the failed setup or authorizes a replacement gate.

## Acceptance requirements

### November16 verification follow-up

All14 retained Word samples now have real LibreOffice26.2.5.2 output:21pages
were rendered and inspected, including six deeds, Unicode court text, three
execution-number styles and the eight-page execution continuation. Independent
PDF decoding confirms all120 ordered entries,120 literal ₹0.50 and Devanagari
values, page fields and prayer/verification after the last entry. Earlier
renderer setup/timeouts remain retained. No live legal-generation claim follows.

The complete independent Python source-inventory/font-closure run collected808
cases:807passed/1failed. Its actual native reporter bridge decoded Node's UTF-8
JSON with the Windows default code page, corrupting the title before comparing
it with UTF-8 JUnit. Production decoding was already strict UTF-8. Correct only
that fixture read and assert the literal Unicode title independently in both
real outputs; the original failure and complete identity/privacy checks remain.
The corrected native case passes; complete808-case replacement remains pending.

Fresh OpenAPI generation on source85ad115b using the owned pinned7.13.0 generator
produces the exact committed client. Parent2481e2b4 has fully green hosted API,
PostgreSQL, desktop/phone, security and source gates; this does not certify the
feature's still-pending full frontend, PostgreSQL, Docker or deployed workflows.

Linux frontend preparation preserves two refusals: a Windows archive with
converted line endings (replaced by exact stored Git bytes), then a30-second
installer preparation failure on overlay storage. A fresh executable tmpfs
keeps that deadline unchanged and permits the frozen309-package installation.
Subsequent browser acquisition failed DNS and ended after the workstation's long
clock interruption; it is incomplete preparation, never test acceptance. Prefer
the matching official digest-pinned Playwright producer for retained browser
bytes, then prove runtime and complete inventory with installation stopped.
All raw receipts remain under `C:/Users/mishr/.codex/merge161001`. **NO-GO**.

1. Inventory every active generation caller, including generic and untitled
   template paths, preview, regeneration, IP and any separate notice/deed flow.
2. Maintain one versioned, source-attributed format definition rather than
   contradictory instructions in several generators.
3. Preserve current facts, authority provenance, tenant policy, access controls,
   legal validation, version history and approval/finalization fences.
4. No sample facts or presumed attestation. Unknown particulars remain explicit
   placeholders. A verification block must identify the actual paragraph ranges
   when known; it must not invent the signer's knowledge or completed oath.
5. Complete schema, discovery, facts validation, web types and form propagation
   for any newly exposed format. Do not advertise an unsupported generator.
6. Exercise each format family through preview, generation, regeneration and
   saved/reloaded output, including missing particulars and conflicting sample
   values. Preserve both generic and IP-specific behavior.
7. Compare actual Word/PDF renders, complete text, page breaks and signature/
   schedule boundaries on representative long and Unicode documents. Test both
   desktop and phone workflows. Prompt string checks alone are insufficient.
8. Run required source, component, database and full release gates only in the
   explicitly released shared window. No paid-model probe or production
   document creation is authorized by this plan.
9. Publish the separately requested draft PR against the current PR621 branch.
   Rebase only this feature onto actual canonical main after the parent merges,
   retarget the draft and complete testing before readiness or merge. Do not
   combine the older bug-fix commits or duplicate the release owner's commits.

## Pending verification sequence

### November16 takeover evidence

The owner explicitly released takeover after the previous jobs ended and
authorized CI, merge and production deployment. Earlier holds and failed
preparations above remain historical evidence; they are superseded for current
work, not relabeled successful.

This worktree's own frozen npm installation completed using Node22.23.4.
Canonical OpenAPI dump/client generation completed. Complete format reference,
rendering and HTTP workflow replacement passed221cases, zero failures or skips,
including all44 SQLite workflow cases. The original44failures/177passes remain
retained: known-UTC persisted draft timestamps lost their offset on SQLite;
structured validation tests read the wrong problem field; and a graphics context
crossing a manual PDF page boundary corrupted the following heading. Corrections
retain legal dates, error locations, exact document text and lifecycle fences.

The complete web project (including component tests) and E2E TypeScript compile
pass. Fifteen actual renderer PDFs/23pages were inspected, including all six
deeds and the eight-page Unicode execution table. PDF acceptance now independently
decodes actual metadata for the presentation contract: saved internal title and
legal body caption may differ. Missing/wrong metadata and legacy title controls
remain strict. Four direct actual-oracle controls pass; these are not Vitest
acceptance. Vitest worker startup failed before collection on three attempts;
the cause remains unproven and complete frontend acceptance remains pending.
Word rendering attempts did not complete and remain unverified.

Evidence: `C:/Users/mishr/.codex/merge161001` (formats-sqlite-01/02, generated
OpenAPI, typecheck-web-01/02, typecheck-e2e-01, pdf-title controls, rendered-pdfs
and retained failed Word attempts). PostgreSQL, adjacent modules, configured
desktop/phone journeys, whole frontend, independent inventories, complete Docker,
fresh exact-head CI and deployed workflow proof remain pending. **NO-GO**.

The following acceptance stages remain open; the scoped syntax/Ruff results
above do not satisfy them. Record actual command, source identity, native exit
status and durable evidence in each explicitly released window.

| Stage | Required evidence |
|---|---|
| Dependency ownership | Activate the accepted Python 3.13.14 and Node 22.23.4 runtimes. Complete this worktree's exclusively owned dependency installation before any test/build consumes it. Retain the failed offline setup. |
| Contracts and static checks | Generate OpenAPI with `scripts/dump_openapi.py` and the pinned client generator. Run API lint, web project compilation including component tests, E2E TypeScript and dynamic build/deploy closure checks. |
| Format source and registry | Execute `test_drafting_format_reference.py` and complete affected template, golden, preview and bench-aware modules. Confirm all 46 types and each explicit selector choice. |
| Actual workflow and persistence | Execute the complete new `test_drafting_format_workflows_20261115.py` on SQLite and `test_drafting_format_workflows_20261115_postgres.py` through the canonical isolated PostgreSQL client. Collect and reconcile all 44 cases in each dialect, including malformed-table state/audit refusals and repaired revisions. Run affected existing drafting/IP/export modules. |
| Document output | Execute the complete new rendering module. Retain the actual renderer-produced Word/PDF files. Render every page; inspect all six deeds, representative court and correspondence forms, wrapped headings, legacy controls, and the multi-page Unicode execution table. Check text completeness, borders, contrast, clipping, footer placement and page breaks. |
| Frontend and inventory | Run the complete intended frontend inventory and independent Python/browser source-inventory modules. Collect the actual configured App inventory; compare every identity and per-role count, preserving original skips and budgets. |
| Browser workflow | Execute both new desktop/phone journeys and affected existing drafting journeys, including real marked requests, retained history, explicit instrument choice, actual Word attachment and full PDF canvas/download assertions. |
| Complete release | Close all source writers, enumerate every tracked/untracked input, reconcile exact hashes/sidecars, read the latest CI/security handoff and required checks, then run a fresh complete canonical gate in the released window. Preserve failures and all unreached boundaries. |
| Separate PR | The owner explicitly requested draft creation before the test-window handoff. Publish a separate draft stacked on PR621, then rebase/retarget only this feature to actual main after the parent merges. Complete and record the required tests before readiness or merge. Deployment and real-model legal accuracy remain separate claims. |


### November 16 CI reconciliation after PR621 merged

PR621 merged as `2d31f6b9cc305de137f8c8b7cc13ddfccb168964`.
PR623 is now based on main. The first reopened CI run retained the obsolete
merge `4abc2cdfff84ece1d199d4ca71635490f667b2db`, whose first parent is
`2481e2b4a2714bfb675ca9892645398eca02899d`, rather than the new main merge.
The secret scan refused the missing base ancestry before inventory or scanning;
this is incomplete security evidence, not a clean scan or a secret finding.
A fresh pushed candidate must receive the actual current-main merge and pass.

The same hosted Linux frontend run collected all 311 files / 3179 cases:
3178 passed and the single failure was the new loopback UUID fixture journey's
missing declaration in the existing explicit exception inventory. The journey
uses the same UUID-fenced local Python fixture as the older declared journey.
Declare that exact file and reason; production journeys remain covered by the
unchanged prohibition. The governance check also correctly refused the web
builder change without a map review; the map and generated projection now
record the builder-only synthetic closure and unchanged data boundaries.

The complete Windows frontend attempt failed: 2957 passed, 7 failed, 19 declared
skips and five worker-start timeouts; only 306 of 311 files collected. Two native
child deadlines, source-scan and Select deadlines, a recordal loading assertion
and a second recordal deadline remain failed Windows evidence. The hosted Linux
run passed these exact files; that is separate platform evidence, not a rewrite
of the Windows outcome. No deadline, loading assertion, inventory or worker
startup bound is relaxed. A complete replacement frontend run is required.

Actual Word output is now rendered and inspected: 14 documents / 21 pages,
including all six deeds and the eight-page Unicode table. The table separately
retains all 120 ordered entries, 120 literal sub-rupee amounts and Hindi labels,
page fields, prayer and verification after the final entry. Earlier incomplete
Word attempts remain retained. The complete 808-case independent inventory
attempt had 807 passes and one Windows default-codepage read failure on real
UTF-8 Node reporter output; explicit UTF-8 reads preserve strict JSON/XML literal
identity, and its focused replacement passed. Adjacent fixture reads now use
the same explicit encoding; the full replacement inventory remains required.

Evidence: `C:/Users/mishr/.codex/merge161001`, including the original native
reports, CI artifacts, rendered Word/PDF pages and independent content checks.
No combined-release or production GO is claimed by this review.

The focused Windows UUID-guard replacement collected two cases: the run-id
generator passed, but the unchanged whole-source scan exceeded its original
15-second limit (16.47 seconds). It remains failed evidence; no allowance or
source-scan deadline was changed. Fresh Linux CI must prove the corrected
inventory under the original full frontend contract.

### November 16 complete inventory and adjacent CI count reconciliation

On candidate `51b90c6c70bdda0c61b89b6c10412d0ca4c17ccd`, the fresh hosted
frontend passed all 311 files / 3179 cases under the original coverage, worker
and deadline contract; web/component and browser TypeScript, production build
and Docker builder also passed. Fresh security, mobile source, API lint and
governance checks passed. These do not turn the earlier Windows frontend
timeouts into passing evidence.

The complete Windows independent inventory replacement passed all 808 cases,
zero failures/errors/skips, in 2312.27 seconds with native exit 0 and completed
EOF. Its admission sidecar records the known untracked `apps/api/C` zero-case
XML from the earlier malformed launch; that file was inspected, hash-recorded
and moved to retained evidence. It was not application or test source, and no
tracked test/build input changed while this replacement ran. This artifact
reconciliation must remain explicit; it is not a clean-admission claim.

Hosted API shard9 then exposed one additional independent consumer of the
current browser role counts: `test_batch5_release_wiring.py` still expected
727 desktop / 63 phone cases. The two exact newly reviewed format journeys
make the current whole counts 728 / 64. Update only that literal equality;
the 719 / 55 historical base, expected skips, all Batch5 identities and proof
scopes remain unchanged. An adjacent source audit found the other current
Python and frontend equality contracts already use 728 / 64. Preserve the
original 1-failed / 1424-passed shard report and replay this complete affected
module plus fresh CI; no count inference, test omission or threshold waiver
is introduced. The complete Docker and deployed workflows remain pending.

### November 16 PR-merge CodeQL review

The branch-only open-alert query returned no rows, but that did not inspect
the PR's actual merge ref. The separate `refs/pull/623/merge` analysis reports
ten `py/implicit-string-concatenation-in-list` quality warnings in the shared
presentation instructions. These joins are deliberate; make each continuation
explicit with `+`, as the [CodeQL query documentation](https://codeql.github.com/codeql-query-help/python/py-implicit-string-concatenation-in-list/)
recommends. Preserve the
exact emitted instruction text across all 98 template/registry combinations.
No alert is dismissed or suppressed, and no list item or legal safety instruction
is removed. Fresh actual PR-merge analysis and its separate open-alert verdict
must pass before the next frozen release candidate.

Earlier candidate `64a31566` passed hosted API coverage, all 4,202 PostgreSQL
cases and the complete phone inventory (63 passed, one existing production-only
invoice skip). The new phone drafting journey passed once with zero retries.
Its pending desktop run remains separate. The third local release attempt built
both images, then failed before stack startup because Docker's default address
pools were exhausted. The fourth uses the existing explicit-subnet parameters;
it was intentionally interrupted at stack startup to supersede this source after
the merge-ref warnings were found. Its cleanup parent remained running, and its
partial startup, capture and cleanup evidence remain retained as incomplete.
Neither attempt proves complete local PostgreSQL or browser acceptance, and
no production verification is transferred from these results.
