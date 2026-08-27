# Intelligent review foundation

## Scope and canonical owners

IPLF-063 extends the existing `Recommendation` owner to exactly one Matter or
IP docket target and optionally one proceeding under that docket. It reuses the
M4 target-aware `Draft`, `DraftVersion`, approval, source-action, authority
corpus, frozen research report, `ModelRun`, billing, audit, tenant AI policy,
and access-control owners. It does not add a second recommendation, research,
source, IP, Matter, drafting, approval, model-run, or billing subsystem.

Migration `20260828_0001` is additive. It introduces tenant-bound target and
source-report references plus review state, frozen context, source manifest,
lawyer selection, policy versions, progress, result hash, finalization, and
publication linkage on the existing recommendation record. Draft publication
uses one tenant-bound `source_recommendation_id`; one intelligent review can
create at most one Draft. Downgrade refuses while review or linked Draft
evidence exists.

## Frozen input and source boundary

A review starts only from an immutable `AuthorityResearchReport` visible to the
authenticated tenant. The actor selects one currently permitted operational
Matter or IP docket, an issue, bounded facts, document references, and up to 25
authority IDs already present in that report. The server resolves tenant scope,
target state, report membership, source access, and source text. The browser
does not invent a tenant ID, report result, target identity, content hash,
source version, or candidate count.

Every authority response also carries a server-owned `SourceAction` contract.
The browser renders that contract directly; it does not construct a source URL
or infer a source key. Generation requires the frozen authority to be both
`available` and openable under the canonical source registry. Clicking the
source action rechecks tenant access and the live source policy before issuing
the bounded redirect. An unregistered URL therefore abstains before the model
call even when the stored authority happens to contain valid HTTPS text.

The generated prompt includes at most 3,000 characters from each accessible
source. Source text is explicitly delimited as untrusted evidence; prompt-like
instructions in authority text are recorded in the manifest and never treated
as instructions. Inaccessible or textless sources remain in the frozen
manifest with their citation metadata but are excluded from generation. Zero
usable sources produces a typed abstention before any provider call.

Provider work runs with the database transaction released. Before accepting an
answer, CaseOps reopens a transaction and reauthorizes the actor, target,
report, source membership, content hashes, versions, and access states. Target
disposal, membership revocation, or a changed source causes fail-closed
abstention without saving generated legal analysis.

## Output verification and lawyer control

The structured result separates the issue summary, relevant facts, applicable
provisions, supporting authorities, contrary authorities, factual analogies,
research gaps, lawyer checks, and unresolved contradictions. Each authority
retains title, citation, court, date, exact passage, relevance, treatment,
source URL, access state, content hash, source version, and retrieval time.
Every cited passage must normalize to text in the frozen source, and every
assertion citation must resolve to one of those verified passages. Any mismatch
causes abstention and no review payload is accepted.

Duplicate fact labels with differing values are surfaced as unresolved
contradictions. Missing contrary authority becomes an explicit gap and lawyer
check. Sources older than 90 days, or without a retrieval timestamp, retain a
stale warning. Every result states that it is source-bounded decision support
and not exhaustive legal research.

Generated text is rejected if it contains judge favourability, outcome
probability, guaranteed strategy, or exhaustive-research claims. This static
safety boundary runs before any result is persisted. Later IPLF-065 evaluation
may broaden governed quality and red-team coverage; it does not replace this
IPLF-063 release gate.

An authorized lawyer may include or exclude generated authorities and add
notes while the result is ready. Completeness requires a selected supporting
authority, review of generated contrary authority, and every source cited by
each assertion. Removing any cited source marks the assertion unsupported and
blocks finalization. Finalization requires `recommendations:decide` and records
the lawyer and time. Publication requires `drafts:review`, is idempotent, and
creates a separate existing Draft and initial DraftVersion. The Draft then
follows the normal edit, review, approval, and finalization lifecycle.

For a Matter review, publication creates a Matter Draft. For an IP review, the
lawyer may analyze a whole docket, but Draft handoff additionally requires one
server-listed opposition proceeding under that same docket. Docket-only IP
analysis can be finalized but publication returns a typed conflict, so no
orphan pleading is created. A successful IP handoff opens the existing
opposition pleading workspace with the exact docket, proceeding, and Draft IDs;
the loading state does not discard those deep-link selections.

## Persistence and operational bounds

- 25 selected authorities, 50 facts, and 50 document references per review;
- 1,200 issue characters, 2,000 value characters, and 5,000 lawyer-note
  characters;
- one asynchronous provider call with the existing recommendation token and
  provider deadline policy;
- list endpoints capped at 100 permission-visible reviews;
- complete composite tenant foreign keys and deterministic covering indexes
  for target, source report, finalizer, Draft handoff, state, and creation time;
- constant-query listing: permission visibility is applied in SQL and Draft
  linkage is loaded in one batch, so a 50-row page does not add per-row target
  or publication queries;
- a queued job is claimed with a row lock and skip-locked semantics before the
  single provider call, preventing concurrent workers from duplicating it;
- no model or tokenizer download, corpus-scale scan, worker, or scheduler on
  the interactive path.

The review states are `queued`, `running`, `ready`, `abstained`, `failed`,
`finalized`, and `published`. Provider and unexpected errors are redacted.
Model run, prompt hash, source manifest, output hash, selection, finalizer,
Draft linkage, and audit events remain inspectable without storing provider
credentials or exposing source bearer tokens. Terminal failures and
abstentions record redacted system audit codes; raw provider exceptions are not
written to review records or audit metadata.

## Verification and rollback

Automated proof covers the normal Matter workflow, source URL and passage
lineage, supporting and contrary comparison, contradictory facts, incomplete
selection, finalization, idempotent Draft handoff, tenant isolation,
inaccessible-source abstention, passage tampering, prohibited output, stale
sources, prompt injection, source changes, and target disposal during provider
work. They also prove constant list query count, complete foreign-key indexes,
Matter publication, IP opposition publication, and rejection of an orphan
docket-level Draft. Web tests cover source selection, server-owned
target/proceeding IDs, exact URLs, lawyer completeness, finalization,
publication, typed abstention, and exact opposition/Draft deep-link selection
after asynchronous loading. Dated Playwright covers desktop and 360px
user-visible acceptance.

Release requires the full repository gates, PostgreSQL migration and index
health, exact Docker images, responsive browser acceptance, hosted CI/security,
migration-first production deployment, exact API/web identity, and the dated
production journey. The authority-metadata and judge-mapping refresh jobs stay
paused. Application rollback uses the prior exact images; database downgrade
is allowed only when no intelligent-review or linked Draft evidence exists.
