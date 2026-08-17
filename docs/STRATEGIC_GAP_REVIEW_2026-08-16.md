# CaseOps Strategic Gap Review — 2026-08-16

**Basis:** repository at `ba869fa2` (origin/main), verified by direct code
inspection.
**Origin:** an external strategy review supplied by the founder
(`caseops-gap-review.md`, 16 Aug 2026). That document benchmarked CaseOps
against named commercial platforms. The dated April/May benchmark analyses keep
the platform names and source URLs because they are evidence and provenance;
this review uses category descriptions in its narrative.
**Verdict:** **GO for continued implementation. NO-GO only for activation or a
pilot that relies on the affected controls in §2.** See §1.

> **How to read this.** The external review was *not* copied forward. Every
> factual claim in it was re-verified against the code, following the precedent
> in `docs/PRD_CLAUDE_CODE_2026-04-23.md` §6.1: an outside audit is a hypothesis
> until reconciled with repo truth. **35 of 111 verified claims were wrong or
> overstated, in both directions.** Corrections are in §3. Items the outside
> review missed entirely — several of them more serious than anything it found —
> are in §2.

---

## 0. Method and its limits

Three verification passes: 10 parallel readers over claim clusters, a
completeness critic over their merged output, then a second round closing the
gaps the critic flagged. 243 individual findings, each requiring a `file:line`
or an exact command and its output.

Two methodological rules were established during verification and are binding on
any future audit of this repository:

1. **Verify the commit you claim to verify.** The first pass measured a working
   tree 391 commits and 489 files behind `main` and produced figures wrong by
   3–6×. Confirm `git rev-parse --short HEAD` before measuring anything.
2. **`infra/cloudrun/api-service.yaml` does not describe production.**
   `scripts/deploy-prod.sh:364-389` deploys the API with
   `gcloud run deploy --update-env-vars`; it never applies that manifest, and
   `infra/cloudrun/deploy.ps1:234` explicitly warns against
   `gcloud run services replace` for it. No claim of the form "X is enabled/dark
   in production because the manifest says so" is sound for the API service.
   Cloud Run **job** manifests *are* applied, so inference from those is valid.

**What this method cannot settle.** Live database state (corpus size), live
Cloud Run environment variables for the API service, and organisational facts
(certifications, signed contracts) are outside the repository. Those are marked
`UNVERIFIABLE` rather than guessed.

---

## 1. Verdict

**GO for continued repository implementation.** The findings below are not a
repository-wide merge, implementation or documentation freeze. They are a
**NO-GO only for production activation, release claims, or a pilot that relies
on the affected billing, payment, citation, security or operational control.**
The evidence limitations recorded in
`docs/STRICT_REPO_QUALITY_AUDIT_2026-07-10.md` remain relevant to their affected
surfaces.

The activation blockers are **not** the strategic gaps the external review led
with. They are billing correctness defects that can produce the wrong statutory
tax, payment paths that can break matter records, and a citation verifier whose
production path does not verify. Unrelated implementation may proceed in
parallel.

This repository's governance artifacts remain more honest than its marketing.
`docs/ip-implementation/PROGRAM_MANIFEST.yaml` records `PROGRAM INCOMPLETE` and
`release_status: blocked`; `README.md:70` correctly labels autonomous agent
execution as readiness-only. That discipline is real and worth preserving. The
drift is concentrated in two customer-facing surfaces (§2.8, §2.9), not in the
engineering record.

---

## 2. Affected activation and pilot control gaps

Severity-first, per `.claude/skills/enterprise-hardening/SKILL.md`. Every item
here was found by verification, and **items 2.1–2.6 do not appear in the external
review at all**. Here, "stop-ship" means stop activation or pilot use of the
named surface until its control passes; it never means stop unrelated repository
implementation.

### 2.1 Intra-state invoices are issued with the wrong GST head — `Missing`

*Journey J11 · Module M10 · finding PAY-19, PAY-20*

Intra-state B2C invoices are issued with **IGST instead of CGST+SGST**, and any
malformed client GSTIN silently produces the same wrong tax head. Place of
supply — the field that legally determines the split under the IGST Act — is a
free-text display field that never reaches the tax engine; the engine infers
jurisdiction from GSTIN digits alone, which is why unregistered clients misfire.

This is a filing-level defect on real client invoices, not a display bug. Every
invoice already issued to an unregistered intra-state client is wrong.

**Required:** place of supply must be a structured input that drives the tax-head
decision. For ordinary domestic services under IGST Act 2017 §12(2), use the
registered recipient's location; for an unregistered recipient use the
recipient's address on record when it exists, and the supplier's location only
when no such address exists. Validate the applicable rule and fail closed rather
than deriving the answer from malformed GSTIN digits. Add a regression per tax
head across registered/unregistered × address-present/address-absent ×
intra/inter-state.

### 2.2 A matter can be made permanently unopenable — `Missing`

*Journey J13/J11 · Module M10/M20 · finding PAY-11, PAY-05*

Two independent paths write a status the read schema does not admit, after which
`GET /api/matters/{id}` fails pydantic validation and returns 500 **on every
subsequent load**:

- an outside-counsel portal user submitting an invoice writes `needs_review`,
  which no approval path can clear;
- a refund webhook writes an out-of-enum status onto the payment attempt.

The matter becomes unopenable and there is no in-product remedy. This is the
exact failure class `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md` was written
about: a write path and a read path disagreeing on an enum.

**Required:** reconcile the status enum across DB, write path and read schema;
add the create/update/read-parse audit the bug-fixing skill mandates for enum
drift; backfill any rows already in the bad state.

### 2.3 Client payments are under-credited — `Missing`

*Journey J11 · Module M10 · finding PAY-17, PAY-18, PAY-15*

- An invoice settled across several attempts credits only the **single largest
  attempt**, not the sum. A client paying in two instalments is left showing a
  permanent balance due and will be chased for money already paid.
- The webhook cannot read the amount from the provider's own documented nested
  payload and silently yields **0**; full payments survive on a fallback, partial
  payments are recorded as zero collected. The flat `amount` key is interpreted
  as paisa or rupees depending on its JSON type.
- The matter-invoice webhook path has no out-of-order guard and will regress an
  attempt from `paid` to `failed` on a late delivery.

**Required:** sum attempts; parse the documented envelope with an explicit unit
contract; add the out-of-order guard the subscription path already has.

### 2.4 Invoice numbering is neither gapless nor concurrency-safe — `Partially implemented`

*Journey J11 · Module M10 · finding PAY-07, PAY-08, PAY-09, PAY-10*

Any admin — and any outside-counsel portal user — can supply an arbitrary invoice
number. The sequence is read unlocked, so concurrent creation on one billing
profile raises an uncaught `IntegrityError` (500, not a retry). A tenant without
a billing profile can auto-number exactly one invoice ever; the second fails 409
with no hint that the fix is to create a profile. Immutability exists only
because no edit endpoint was written — there is no CHECK, trigger or revision
table.

Gapless, immutable numbering is a statutory expectation for GST invoices.

### 2.5 Rate limiting covers 3.7% of the API — `Partially implemented`

*Journey J14 · Module M14 · finding RL-1, RL-2, RL-3*

The limiter is `slowapi` with **process-local in-memory storage** — no
`storage_uri`, no Redis anywhere in the repo. Limits are therefore per container
instance, and `scripts/deploy-prod.sh:58` pins the API to `max 20` instances at
concurrency 1, so the effective limit is up to **20× the documented one**.

Only **7 of 40 route modules** apply any rate limit, covering **23 of 622
endpoint decorators (3.7%)**. The governance test meant to enforce this
(`test_ai_route_governance.py:32`) inspects only `/api/ai/*` and
`/api/recommendations/*`, so provider-backed routes elsewhere are unguarded.

### 2.6 Two security controls fail open by construction — `Partially implemented`

*Journey J14 · Module M14 · finding SCR-08, SCR-09, OBS-12*

- `services/inbound_email.py:224-225` — `_verify_signature` bare-returns when the
  provider mode is `mock`, **before** the HMAC comparison.
- `core/csrf.py:72-80` — `_EXEMPT_SUFFIXES = ('/webhook',)` exempts *any* path
  ending in `/webhook`, with a comment noting that a new provider integration
  gets exempted without touching the list.
- No log redaction exists anywhere. Any `logger.x(..., extra={...})` carrying
  client names, emails or payment payloads lands in Cloud Logging in the clear —
  a live privilege risk in a legal product.

### 2.7 The citation verifier does not verify the proposition — `Partially implemented`

*Journey J05/J07/J09 · Modules M05–M07 · finding ST-1, GAP-citation-verification*

**The external review called this the product's greatest strength. It is the most
overstated claim in the document.**

Three code paths set `verified=True` in `services/citations.py`, and production
drives the one that checks nothing:

| Path | Location | What it checks |
|---|---|---|
| Bracket-tag short-circuit | `citations.py:161-171` | that `[n]` is an in-range list index — reads neither `source.text` nor `claim.proposition` |
| Bare citation | `citations.py:180-186` | nothing; `proposition is None` ⇒ verified |
| Proposition match | `citations.py:187-198` | the only real check, and weak: 2 tokens of length ≥3 appearing anywhere in the source, unordered, negation-blind |

Both production prompts **hard-require** the bracket tag —
`recommendations.py:1249-1256` ("The bracket tag is required — it is how the
verifier resolves the citation") and `litigation_strategy.py:653-655` ("The
verifier rejects citations without bracket tags") — so every citation routes to
the first path. Drafting passes `proposition=None` (`drafting.py:925-927`), i.e.
bare existence. `litigation_strategy.py:948` passes the literal placeholder
`proposition="strategy item citation"`.

The bypass is codified as intended behaviour: `tests/test_citations.py:99-115`
asserts that `"[1] paraphrased title that does not match the source"` with an
unrelated proposition passes.

In production, **"citation verified" means "the model emitted an in-range list
index."** A hallucinating model emitting `[1] <anything>` passes unconditionally.

Given that the Supreme Court has held reliance on fabricated precedents to be
misconduct rather than error, this is the highest-consequence finding in this
review, and it inverts the external review's recommendation: verification cannot
be productised or underwritten until it verifies.

### 2.8 Two customer-facing claims are not backed by code — `Missing`

*Journey J14 · finding T0-7, T2-18*

- `apps/web/components/marketing/Security.tsx:83` sells **"Prompt-injection
  tests"** as a shipped control. The programmatic stripper is unreachable from
  `AnthropicProvider` (`llm.py:398`), `OpenAIProvider` (`:509`) and
  `GeminiProvider` (`:653`), and `conftest.py:106` pins the suite to mock — so no
  injection control is ever exercised against any real model. The test is
  tautological against the mock.
- A billable **"API access — API keys and dashboard"** SKU is seeded and marked
  **active** while no API-key authentication exists anywhere in the codebase.

Both are sold today. Fix the code or withdraw the claim; the second is a
revenue-recognition problem as much as an engineering one.

### 2.9 Legal hold is a table, not a control — `Partially implemented`

*Journey J14/J15 · finding BDR-11, T1-7*

Retention policies and legal holds have immutable, trigger-enforced storage
(alembic `20260813_0001`) — genuinely good work landed 2026-08-13. But nothing
enforces them: there is no `legal-hold/` storage prefix, no hold check in the GCS
delete path, and nothing that can execute a retention decision. A hold can be
recorded and then silently violated.

---

## 3. Corrections to the external review

Copying these forward would have caused real damage. Each was verified at
`ba869fa2`.

| External claim | Verified truth |
|---|---|
| "31 templates claimed, 30 in code" | **31 in code.** `DraftTemplateType` has exactly 31 members, the parallel `Literal` has 31, all 31 have prompt implementations. The drift does not exist. |
| "README markets Grantex" | **`grep -c -i grantex README.md` → 0.** The README is explicitly cautious: "readiness-only until the agent trust plane is activated" (`README.md:10-11`, `:70`). |
| "GST/TDS-correct invoicing" *(listed as a strength)* | **No s.194J logic at all.** `tds_deducted_minor` is a free-form integer the user types, validated only `>= 0`. No rate, threshold, PAN-missing rule, or 26AS reconciliation. And GST is actively wrong — §2.1. |
| "~16,000 LOC of IP module deployed dark behind a default-False flag" | **~22.7k LOC production runtime.** Not flag-gated: **111 of 112 endpoints are capability-only**, and `ip:read` is granted to *every* authenticated role including VIEWER (`capability_catalog.py:65`). The rollout flag is enforced on one endpoint. The UI is dark only because `page.tsx:99-158` blocks on a readiness call. |
| "No vernacular capability" | **Indian-language OCR is implemented**, with tesseract Indic packs in the API image. It is dark by config: `settings.py:417` defaults `ocr_provider="rapidocr"`, `:426` defaults `ocr_languages="eng"`. |
| "No judge identity" | **Judge identity is the one genuinely built entity layer** — judges + aliases + appointments tables, court-scoped tolerant matcher, bench resolver. Residual gap: `Matter.judge_name` is still free text (`models.py:1424`) with no FK. |
| "No procedural intelligence engine" (T1-2) | **Implemented.** Order-to-deadline/task derivation with confidence scoring and human review gating, filing checklists, court-specific format profiles. |
| "Pricing not segmented, no published numbers" (T1-8) | **Implemented.** Three segments, 13 plans, concrete INR figures seeded in `20260531_0001`, rendered on a public page from an unauthenticated endpoint. Only "no self-serve" is true. |
| "No filing-format validation" | Exists — per-court PDF profiles with a required-field validator (`court_format_profiles.py:357`) and pre-filing checklists. Descriptive, not blocking. |
| "31 HCs / 26 HC judge registry" | **24 High Courts + SC, 785 judge records**, of which only 22 have a seeded `courts` row. Seed provenance is Wikipedia (`scripts/one-off/build-hc-judge-seeds.py:3-4`) — which sits badly against the repo's own source-lineage rule. |
| "Audit export at 96% coverage" | The 96% refers to `services/audit.py`, a 117-line write-path helper with **no export code**. The actual JSONL/CSV export (`services/audit_exports.py`, 403 lines) has no direct per-file floor, but it is included in the `services` bucket and overall line/branch floors. |
| "Corpus is 2,436 docs / 36,510 chunks" | **UNVERIFIABLE.** That figure is a single documentation assertion at `WORK_TO_BE_DONE.md:120` self-dated "as of 2026-04-18" — four months stale, never refreshed, with no mechanism to keep it current. Two in-repo numbers disagree with it. |
| "Test coverage 41.5% / 10.0% branch" | **UNVERIFIABLE at HEAD.** Those are a 2026-04-25 baseline recorded in a source file. No committed coverage artifact exists; CI uploads with 14-day retention. **Correction 2026-08-16:** `scripts/coverage_gate.py` runs in the aggregate `API (ruff + pytest)` job and enforces 9 direct per-file floors; line floors for every file grouped into the 5 `api`/`core`/`db`/`schemas`/`services` buckets; branch floors for `api`/`core`/`db`/`services` (the `schemas` bucket has no branch floor); and overall line/branch floors. A file absent from the 9-file list lacks a direct per-file floor but remains indirectly covered by its bucket and the totals; aggregate headroom can therefore absorb some file-level regression without CI failing. |

Two additional corrections that make the picture *worse*, not better:

- **A repo-reproducible deploy starts on mock AI.** No checked-in artifact sets
  `llm_provider` or `embedding_provider`; both default to `mock`
  (`settings.py:285`, `:339`) and no validator catches it. Production values must
  be applied out of band and are not reproducible from the repository.
- **OpenTelemetry cannot work in the shipped image.** `apps/api/Dockerfile:40`
  installs `.[ocr]` only — the `observability` extra is never installed, and
  line 39 says so verbatim. Staging sets `CASEOPS_OTEL_ENABLED=true`
  (`ci.yml:509`) against an image without the SDK, so it emits no traces while
  *reading as working evidence*. There is also no OTLP collector target anywhere
  (default `localhost:4318`). Three independent layers broken.

---

## 4. Tier map — external IDs reconciled to repo status

Statuses are `Implemented` / `Partially implemented` / `Missing` / `Stale-doc`
per the enterprise-hardening skill. `UNVERIFIABLE` marks items that are
commercial or organisational rather than code.

### Tier 0

| ID | Gap | Status | Note |
|---|---|---|---|
| T0-1 | SSO / SCIM | `Missing` | Readiness/status surface only; no OIDC, SAML or SCIM code |
| T0-2 | SOC 2 / ISO | `UNVERIFIABLE` | Organisational; marketing status labels are the only in-repo artifact |
| T0-3 | Marketing vs code | `Partially implemented` | Honesty framework is real but **prose-enforced, not test-enforced** — no test asserts a marketing claim against code. See §2.8 |
| T0-4 | Corpus size | `UNVERIFIABLE` | External DB state; two in-repo figures disagree, both stale |
| T0-5 | Test coverage | `Partially implemented` | 9 direct per-file floors + 5 all-file package line floors + branch floors for 4 buckets (not `schemas`) + overall line/branch floors. Files outside the direct list are indirectly, not individually, gated |
| T0-6 | Postgres RLS | `Missing` | Isolation rests on app-layer `company_id` across 622 routes; 128 of 178 tenant tables have no composite FK backstop |
| T0-7 | Prompt injection | `Partially implemented` | Verification is circular — §2.8 |
| T0-8 | Payments | `Partially implemented` | Built, ships fail-closed; live value unverifiable |
| T0-9 | Dark modules | `Confirmed, larger` | **23** subsystems built and default-off |
| T0-10 | Observability | `Partially implemented` | Logging plumbing real; **alerting entirely absent** — no alert policy, uptime check, SLO or paging integration anywhere |

### Tier 1 — the India-specific opportunity

| ID | Gap | Status | Note |
|---|---|---|---|
| T1-1 | Court entity graph | `Partially implemented` | Judge/bench/court resolvable; advocate, party and cross-instance linkage absent |
| T1-2 | Procedural intelligence | **`Implemented`** | External review wrong |
| T1-3 | Tribunal coverage | `Partially implemented` | Modelled and format-profiled; no working ingest for any tribunal |
| T1-4 | eCourts district | `Partially implemented` | Provider adapter + directories exist; national coverage and session-court automation do not |
| T1-5 | Vernacular | `Partially implemented` | Indic OCR shipped but dark; no translation pipeline |
| T1-6 | Residency / BYOK | `Partially implemented` | Core deploy configuration targets `asia-south1`, but the repository does **not** prove end-to-end India-resident processing: Anthropic/OpenAI/Gemini SDK calls have no pinned processing region and `corpus_ingest.py` opens S3 in `us-east-1`. No CMEK/KMS or per-tenant residency exists |
| T1-7 | DPDP artifacts | `Partially implemented` | Immutable storage landed 2026-08-13; nothing executes a retention or hold decision — §2.9 |
| T1-8 | Pricing segmentation | **`Implemented`** | External review wrong |
| T1-9 | WhatsApp | `Missing` | Selectable channel in schema and preference UI **with no delivery implementation behind it** — a user can choose a channel that silently does nothing. **Deferred out of the pilot 2026-08-16**; the fix is now *remove from the selector* (`EH-SGR-16`), not *implement delivery* |
| T1-10 | Firm-knowledge retrieval | `Partially implemented` | Per-matter document Q&A works; firm-wide layer absent |
| T1-11 | Approved-AI-tool positioning | `UNVERIFIABLE` | Commercial/regulatory |
| T1-12 | Citation verification productised | `Partially implemented` | Internal control only — and see §2.7 before selling it |
| T1-13 | Outcome-based pricing | `Missing` | Commercial |

### Tier 2 — selected

`Missing`: Word add-in (T2-1), e-sign/e-stamp (T2-4), tabular review (T2-5),
agentic execution (T2-6, by design), audio/video (T2-14), MCP server (T2-15),
on-prem/VPC (T2-20).
`Partially implemented`: Outlook (T2-2, one-way push only), DMS (T2-3, Drive only
— no legal DMS), workflow builder (T2-7), chunking (T2-8), reranker (T2-9,
implemented but **unproven in production**), eval harness (T2-11, foundation
only: the recorder explicitly does not drive a benchmark loop, the safety suite
is fixture-only, no expert-gold baseline exists, the committed drafting result
is 4.41/5 against a 4.8 target, and no live/gold evaluation runs in CI),
conflicts (T2-12, records but does not block),
time capture (T2-13, manual only), mobile (T2-16, responsive web), collaboration
(T2-17), public API (T2-18 — but see §2.8), model routing (T2-19).
`Missing as a maintained artifact`: the Indian-legal synonym/abbreviation map
(T2-10) — there is no CrPC/BNSS, IPC/BNS or citation-abbreviation map.

---

## 5. Sequenced plan

Re-sequenced around verified findings. The external review's ordering led with
strategy; the verified evidence says correctness first — you cannot pilot a
product that issues wrong tax and breaks its own matter records.

### Now — before an affected workflow is activated or included in a pilot (weeks 1–4)

1. **Billing correctness** (§2.1–§2.4). Place-of-supply-driven GST; sum payment
   attempts; parse the documented webhook envelope with an explicit unit
   contract; locked, gapless invoice numbering; reconcile the status enum and
   backfill broken rows. Regression per tax head and per payment shape.
   *Gate: no pilot invoice may issue until the tax-head matrix passes.*
2. **Citation verifier** (§2.7). Make the proposition gate mandatory on the
   production paths; keep the bracket tag as a *resolver*, not as proof. Delete
   or invert `test_citations.py:99-115`. Re-baseline any quality claim that
   depended on the old number.
3. **Withdraw or implement the two sold-but-absent claims** (§2.8). Cheapest
   credibility item on the list.
4. **Close the two fail-open controls and add log redaction** (§2.6).
5. **Extend direct coverage floors where risk warrants** (T0-5). The existing
   per-file, package-bucket and total gates remain; add a direct floor for a
   critical module when aggregate floors are too coarse to catch its regression.

### Next — earn the right to sell (months 2–4)

6. **Rate limiting**: shared limiter store, then extend beyond 3.7% of endpoints,
   prioritising provider-backed routes (§2.5).
7. **Observability that exists**: install the `observability` extra in the
   Dockerfile, set a collector target, emit Cloud Logging-shaped fields
   (`severity`, trace ids), wire `matter_id` — currently plumbed but never called
   — and add at least one alert policy. Today there is **zero** alerting.
8. **T0-1 SSO/SCIM.** Required before claims or pilots that depend on enterprise
   identity provisioning; it does not gate unrelated implementation.
9. **T0-6 RLS**, or an explicit accepted-risk record with compensating controls.
10. **Backup/DR**: one restore rehearsal has ever occurred (2026-04-24, 114 days
    before this review, 51 days past the missed quarterly slot). No backup
    configuration is in IaC; no artifact enables GCS versioning or lifecycle.
11. **T1-9 WhatsApp**: **decided 2026-08-16 — deferred for the pilot.** Remove
    WhatsApp and SMS from every user-facing selector and mark them `roadmap`
    (`EH-SGR-16`); do not build delivery. In-app + email is the complete
    pilot channel set.

### Then — build the differentiator (months 5–12)

12. **T1-1 advocate and party identity + cross-instance linkage.** Judge identity
    is already built; this is the remaining three-quarters and the genuinely
    defensible asset.
13. **T1-6/T1-7**: CMEK and an executable retention/hold path.
14. **T1-5 vernacular**: turn on the Indic OCR that already ships, then build
    translation.
15. **T2-1 Word surface**, **T2-8/T2-9/T2-10** retrieval quality, **T2-11** eval
    in CI.

---

## 6. Positioning

The PRD already states the answer at §7: *"the operating system for legal work
and court preparation."* No change is needed, and the external review's
positioning recommendation is consistent with it.

Three defensible proof points, in order — **each conditional on work above**:

1. **Procedure, not just research.** Already `Implemented` (T1-2) and genuinely
   differentiated. Lead with it.
2. **India-hosted core infrastructure.** The checked-in deploy path targets
   `asia-south1`. Do **not** claim end-to-end India-resident processing, BYOK or
   per-tenant residency: external AI provider regions are not pinned and one
   corpus source path is configured for `us-east-1`.
3. **Priced for Indian practice.** Already `Implemented` (T1-8).

Do **not** lead with citation verification until §2.7 is closed. It is currently
the weakest claim being made most confidently.

---

## 7. Deliberately not building

Unchanged from the external review's judgement, which is sound: full eDiscovery,
CLM as a system of record, a horizontal "chat with your documents" assistant
(being commoditised), a consumer/litigant marketplace (BCI Rule 36 solicitation
risk), and global jurisdiction expansion before India is won.

Add one: **do not build an MCP server (T2-15) before the agent trust plane
exists.** Exposing tools to external agents while `Grantex` is still three tables
and no scope checker would invert the product's own safety model.

---

## 8. Open items requiring non-repository verification

1. Live Cloud Run environment variables for the API service — provider settings,
   rerank enablement, OTel. Not reproducible from this repo (§0 rule 2).
2. Live corpus size. The only in-repo figure is four months stale.
3. Actual test coverage at HEAD.
4. Whether GCS object versioning, lifecycle and Cloud SQL backup retention are
   configured on the live project. No IaC artifact sets any of them.
5. Certification status (SOC 2, ISO) — organisational.

---

## 9. Cross-references

- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` — `EH-SGR-01..09` added by this review
- `docs/STRICT_REPO_QUALITY_AUDIT_2026-07-10.md` — prior deployment/evidence
  limitations remain for their affected surfaces; they are not an implementation freeze
- `docs/PRD_CLAUDE_CODE_2026-04-23.md` §6.1 — the reconciliation precedent this
  review follows
- `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md` — the enum-drift failure class
  that §2.2 repeats
