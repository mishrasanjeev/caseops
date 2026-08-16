# Open-Item Resolutions — 2026-08-16

Resolves the open requirements listed at
`docs/FEEDBACK_MERGE_BACKLOG_2026-08-16.md` §9, which the source feedback
document left for confirmation.

**Basis:** repository at `ba869fa2`, verified by direct code inspection.
**Method:** six readers gathered the constraint each open question is already
subject to, then an adjudicator challenged every proposal — both the ones
claiming to be safe defaults and the ones claiming to be unresolvable.

**Result: 47 sub-questions examined. 44 resolved from evidence; the 3 that needed
a commercial decision were decided on 2026-08-16 (§10). Nothing is blocked.**

| Basis | Count |
|---|---|
| Determined by existing code | 27 |
| Engineering default | 12 |
| Determined by statute or public record | 5 |
| Required a commercial decision — **since decided, §10** | 3 |

Most of these were not open questions at all. The repository had already
answered 19 of them and constrained a further 26; the answers simply were not
written down.

> **On not inventing things.** The source document instructs: *"Do not invent or
> hard-code document names until the shared list is approved"* (`DOC-IP-05`).
> That instruction is respected. Where a resolution names concrete values, they
> come from statute or official record — the Trade Marks Act 1999, the Trade
> Marks Rules 2017 First Schedule, the Nice Classification — never from
> preference. Where the value is a firm preference, it stays open and is marked
> as such.

---

## 0. Three live defects found while resolving

These are not decisions. They are bugs the questions exposed, and they should be
fixed regardless of how anything below is decided.

**D-1 — Registry office is not normalised before duplicate detection.**
`_duplicate_identifiers` (`services/ip_records.py:95-96`) keys on the raw
`office` value, so `"Delhi"` and `"delhi"` silently occupy different namespaces
and the duplicate check **misses real matches**. A duplicate-detection routine
that fails to detect is worse than none, because it is trusted.

**D-2 — Two identifier normalisations disagree.**
`normalize_ip_identifier` (`services/ip_identifier_rules.py:14-18`) applies
NFKC + casefold + alphanumeric-only. The docket create path applies only
`.strip().upper()` (`services/ip_operations.py:313`). So `TM-1234` and
`TM 1234` collide in the ledger but not on the docket — the same two strings are
"the same number" in one layer and "different numbers" in the other.

**D-3 — Terminal-status constants disagree.**
`services/ip_lifecycle.py:40-42` and `services/ip_records.py:708` define
different terminal sets; the latter mixes application phases
(`refused`/`withdrawn`/`registered`) into a docket-status test and omits
`archived`/`transferred`/`retired`. It is not fail-open today **only because an
adjacent `docket_is_active` check at `ip_records.py:721` happens to cover the
gap** — i.e. it is correct by luck, not by construction.

---

## 1. Trademark docket stages and transition rules *(was §9.2)*

**Resolved — no new stage list is needed from anyone.**

`EVENT_PHASES` already exists in the codebase and already tracks the statutory
prosecution sequence. Exactly one phase is missing: **`opposition`**, which
belongs between `published` and `registered` — s.21 of the Trade Marks Act 1999
sits precisely there, and `proceeding_kind` already includes `'opposition'`
(`services/ip_identifier_rules.py:9`).

- Adopt `EVENT_PHASES` + `opposition` as the shipped default stage list.
- Express transition rules as **workflow definition version 1**, seeded as a
  `candidate` `transition_table_json` travelling the existing approval path —
  not as a second hard-coded state machine.
- Fix **D-3** as part of this work: reconcile onto one terminal constant.

**Approver named 2026-08-16: Sanjeev Kumar.** The residual sign-off was the
approval act itself, because the schema refuses `approved` without approver
snapshots.

Note what this does and does not close. The named approver is now recorded, so no
further decision is outstanding. The act itself is a **runtime data action**, not
a documentation one: it requires a seeded workflow definition version 1 to exist
first (§1), and the approval must then be applied through the existing approval
path so the approver snapshot is persisted and auditable. Recording a name in a
document is not the same as an approved workflow version, and this document does
not claim otherwise.

---

## 2. Trademark pleading and document names *(was §9.3)*

**Resolved without inventing anything.**

The category level is already seeded and tenant-editable. Only the form/pleading
level is missing, and it does not need inventing because it is **public record**:
the First Schedule to the Trade Marks Rules 2017 defines the official form
namespace, and the repository has already committed to that namespace via its
`TM-A` default.

- Seed the official forms — `TM-A` (application), the `TM-O` opposition series
  including notice of opposition and counter-statement, `TM-M` (miscellaneous),
  `TM-R` (renewal), `TM-P` (post-registration) — with `is_seeded=True`, hung off
  the 14 existing categories rather than a parallel master.
- Because they are seeded rather than hard-coded, a firm can rename or
  deactivate any of them through the existing upsert path without a migration.

**Residual sign-off:** whether the firm's own internal working names (its label
for a counter-statement, say) should additionally be seeded as
`IpDocumentTaxonomyAlias` rows. That is labelling on top of a working system.

---

## 3. Application Number uniqueness *(was §9.4)*

**Resolved — and the first proposed answer was overruled.**

A reader proposed dropping the hard constraint on `docket.primary_identifier` in
favour of the ledger's soft rule. The adjudicator rejected that: the two rules
answer **different questions** and both should stand.

- **The ledger stays non-unique.** A real registry number legitimately recurs
  during correction, supersession and multi-source observation — which is
  exactly why `effective_from`/`effective_until` and `supersedes_identifier_id`
  exist.
- **The docket key stays unique per company.** A *live* application number
  genuinely is unique at the Registry, so two live dockets sharing one inside a
  tenant is a data error.
- **Resolution:** make `primary_identifier` **derived, not independently typed** —
  set it from the confirmed, current, `is_primary` ledger row. The 409 then fires
  only after reconciliation has confirmed a true duplicate; everything else goes
  to the review queue instead of being rejected at the door.

This also closes **D-2**, because a derived value inherits one normalisation.

**Residual sign-off:** whether a supervisor may ever override the 409 (e.g. a
legacy migration carrying genuine duplicates). Default is **no** — use the
existing merge/supersede path. Nothing is blocked while that stands.

---

## 4. Opposition Number — mandatory when, and how many *(was §9.5)*

**Resolved from the schema and the statute.**

- **Multiple oppositions per application: yes.** Already permitted by the schema
  (identifiers bind to `proceeding_id` under `ck_ip_identifier_single_owner`) and
  legally correct — s.21 lets *any person* oppose within the statutory window, so
  several notices against one advertised mark are routine.
- **Mandatory when:** not required to create the proceeding, because the Registry
  allots the number only on filing and it therefore cannot exist earlier.
  Required **before the proceeding leaves its pre-filing stage**.
- Implement as `assert_proceeding_can_enter_filed_stage`, mirroring the existing
  application-side function line for line rather than inventing a second gating
  pattern.

**Residual:** the specific pre-filing/filed stage labels come from the workflow
version resolved in §1. A dependency, not a blocker.

---

## 5. Registry master and trademark class rules *(was §9.6)*

**Resolved from public record.**

- **Classes need no input.** The Nice Classification has exactly 45 classes; the
  code already enforces that bound in two independent paths, and multi-class
  filing matches s.18(2) of the Trade Marks Act 1999. Add the matching database
  `CHECK (class_number BETWEEN 1 AND 45)` so the rule is not schema-layer-only.
- **Registry:** seed the five Indian trademark registry offices — Delhi, Mumbai,
  Kolkata, Chennai, Ahmedabad — as a seeded-but-tenant-editable master, reusing
  the taxonomy pattern already proven at `services/ip_documents.py:124-172`.
- Fix **D-1** as part of this: normalise `office` before it is used as a
  duplicate-detection key.

**Residual sign-off:** whether non-Indian registries (Madrid/WIPO, EUIPO, USPTO)
are in v1 scope. A market decision, not an engineering blocker — the
`jurisdiction` column and the seeded-master pattern already accommodate them, so
the India-only seed ships now.

---

## 6. Notification channels and reminder timing *(was §9.7)*

**Resolved, and it exposes a product honesty problem.**

**SMS is structurally unavailable, not merely unconfigured.** There is no
verified phone number on `User` or `CompanyMembership`, so choosing `sms` on a
hearing today produces reminder rows that **can only ever reach FAILED**.
WhatsApp has no adapter at all. Offering a channel that cannot deliver is worse
than not offering it.

- **Ship two channels:** `IN_APP` (always on, never suppressible for critical
  items) and `EMAIL` (on per tenant when SendGrid is configured). Keep `SMS` and
  `WHATSAPP` in the enums for forward compatibility but **remove them from every
  user-facing selector** and mark them `roadmap` in the API response. Both
  shipped UIs already do this independently.
- **Reminder ladder — one published schedule, three tiers:**
  - Hearings: **T-72h, T-24h, T-3h** (replacing the current `[24, 1]`; T-1h is
    close to useless for an Indian listing where counsel must brief and travel).
    Date-only hearings anchor each offset off **18:00 IST**, keeping the existing
    and correct "never invent a hearing time" rule.
  - Statutory/registry deadlines: **T-30d, T-14d, T-7d, T-3d, T-1d**, anchored
    09:00 IST, with a non-empty server-side default so a caller omitting offsets
    no longer silently gets zero reminders.
  - Legal notices: keep `[7, 3, 1]` days.
- **Do not build a rule-driven timing engine.** Two timing mechanisms already
  overlap; a third via `NotificationRule.offset_minutes` would be exactly the
  speculative configurability the house rules forbid.

**Blocking hazard — do not flip both delivery flags together.** Enabling
`hearing_reminders_enabled` and `notification_external_delivery_enabled` at once
may double-send, because the legacy worker and the durable queue can both own the
send. Sequence it: write a test that enables both, schedules one reminder, runs
the worker against a counting stub and asserts **exactly one** send. If it
double-sends, make the worker skip any reminder that already has a primary
delivery intent.

**Consequence worth accepting deliberately:** the external email body is
content-free by design (correct privileged-communication posture, and a tested
invariant). Once durable delivery owns the send, the lawyer's inbox shows
"Open CaseOps to review this notification securely" with no date, matter code or
link. Keep the posture; expect the complaint.

**DECIDED 2026-08-16 — deferred for the pilot.** SMS and WhatsApp are out of
scope for the pilot. No Twilio account, DLT sender registration, Meta Business
Account or per-message budget is required, and none should be pursued for this
release.

Consequences to implement:

- `IN_APP` + `EMAIL` are the complete product-supported channel set. Remove
  `SMS` and `WHATSAPP` from every user-facing selector and mark them `roadmap`
  in the API response (`EH-SGR-16`). Keep the enum members.
- `twilio_enabled` and `whatsapp_enabled` stay `false`; do not wire either into
  any deploy manifest.
- `T1-9` (WhatsApp distribution) in `docs/STRATEGIC_GAP_REVIEW_2026-08-16.md`
  moves out of the pilot window. The verified finding there stands — WhatsApp is
  a selectable channel with no delivery behind it — but the fix is now
  *removal from the selector*, not *implement delivery*.

---

## 7. Source links: new tab, in-app, or both *(was §9.9)*

**Resolved: both — the server picks, keyed off `destination_class`.**

- Content CaseOps **hosts** (`caseops_protected`: matter attachments, IP document
  versions) opens **same tab, in the in-app viewer**.
- Content CaseOps merely **references** (`verified_public`: statute deep links,
  official judgment PDFs, judge-appointment source pages) opens in a **new tab**
  with `rel="noopener noreferrer"` and `referrerPolicy="no-referrer"`.
- **Make `SourceAction` the only permitted way to render a source link.** Eight
  backend responses currently emit a bare `source_url`/`source_reference` string
  and the frontend renders raw `<a href>`. Convert them to emit a `source_action`
  object the way `routes/courts.py:384-389` already does, and add a repo test
  that fails any raw `href={` bound to a source field.
- **Fold this into FMB-01/FMB-02, not a separate ship.** Add one helper
  `authority_source_verified(row)` beside `inspect_source_target_action` in
  `services/source_actions.py`, derived from an ingest-populated provenance
  signal — this is the same fix as the F-13 trust predicate.

**DECIDED 2026-08-16 — no publisher licence.** CaseOps is not taking a
commercial legal-publisher licence for this release.

Consequences to implement:

- The source allow-list stays **official-only**. Commercial/licensed sources
  deep-link out and render the `unverified` badge; they never open in the in-app
  viewer.
- Do **not** build the `permitted_uses`-gated in-app display path now. The
  `permitted_uses` contract in `statute_source_governance._validate_source_policy`
  stays as the extension point if a licence is ever taken.
- This simplifies the F-13 work: `destination_class` has two live values for now
  (`caseops_protected` and `verified_public`), not three.

**Open consequence worth a separate decision.** This answers *display of licensed
content*. It does not by itself settle *corpus acquisition*, which
`docs/STRATEGIC_GAP_REVIEW_2026-08-16.md` T0-4 treats as the largest single gap.
If no publisher licence is taken at all, corpus expansion must run on official
and open sources only, which changes the shape of that gap rather than closing
it. Flagged, not assumed.

---

## 8. The Judge–Judgment–Lawyer use case *(was §9.10)*

**Resolved as a Bench Authority Map — and the Lawyer edge is explicitly out of
v1.**

For a matter with a resolved court and judge, render **four source-cited factual
mappings and nothing else**:

1. Judge identity and career — appointments with dates, each row linking its own
   `source_url` (`JudgeAppointment`, `models.py:11753`).
2. Judgments that judge sat on — from `JudgeDecisionIndex` (`models.py:10212`),
   each opening its source document, labelled with the row's own
   `match_confidence` and `matched_alias` so a weak match is visibly weak.
3. Court → judge roster.
4. Matter → the judge on *your* matter.

**Highest-leverage fix in this cluster:** make `Matter → Judge` a resolved FK
(`matter.judge_id`, nullable, retaining `judge_name` as fallback), reusing the
`JudgeAlias` normalisation at `models.py:11702-11750` instead of the exact-string
match at `courts.py:800`. This is what turns "here is a judge profile" into "here
is the judge on your matter" — the only version of the feature that is worth
anything to a practitioner.

**Excluded, deliberately:**
- **Lawyer/advocate edge.** No advocate entity and no populated data to seed one.
  Judgment text *does* carry appearing-counsel information, but CaseOps is not
  capturing it, and `advocates_json` must not be treated as evidence that the
  edge is available. Naming the exclusion **is** the deliverable here: the open
  question asked what use case was intended, and the honest answer is the
  Judge–Judgment–Court triangle, which is real.
- **Any favorability, win/loss, tendency or reputation edge** — forbidden by
  CLAUDE.md and not reintroduced under a graph label.

**Also needed:** add a nullable `court_id` FK on `authority_documents`, populated
at ingest, *before* building the graph UI — the current substring match is not a
sound basis for an edge.

---

## 9. External source access *(was §9.8)*

**Engineering posture resolved. The commercial question genuinely is not.**

The provider choice is already late-bound enough that switching vendors is a
configuration change plus one adapter class, not a re-architecture:

- Treat `CaseTrackingProvider` as the **frozen capability contract**. A vendor
  evaluation reduces to: can it answer CNR lookup, case-number/party search and
  bulk refresh, and can its payload normalise into `ProviderCaseSnapshot`?
- Keep the two-part research split as standing design: `AuthoritySourceAdapter`
  is *how to fetch*, `LegalSourceRegistryEntry` is *whether we are allowed to*.
  Every new source lands as a registry entry **first**, defaulting to
  `readiness_status=proof_required`, `adapter_available=False`, so a vendor can be
  catalogued, reviewed and priced before any fetch code exists.
- Refactor `get_case_tracking_provider()` to a registry dict rather than
  comparing against the literal `"ecourtsindia"` in three places.
- Honour `Retry-After` on 429/503 in `request_with_retries` — the single change
  that makes CaseOps well-behaved against *any* vendor's published limit without
  knowing the number.

**Fix regardless of vendor choice:** the ingest fetcher currently sends a
**spoofed Chrome user-agent**. Replace it with an identifying one
(`CaseOps-AuthorityIngest/1.0 (+https://<domain>/crawler; contact <ops-email>)`),
add a per-host minimum interval, and honour `robots.txt`. This is cheap, and it
removes the clearest terms-of-use exposure in the ingest path.

**DECIDED 2026-08-16 — engineering posture accepted; vendor selection stays
commercially parked.** Build to the contract above so the vendor choice remains a
configuration change plus one adapter class. Do not block P0–P3 work on it, and
do not begin production ingestion from any vendor until the registry entry
carries a recorded access decision.

Consequences to implement:

- `EH-SGR-15` (identifying user-agent, `robots.txt`, per-host interval) proceeds
  now — it is required regardless of vendor and is the clearest terms-of-use
  exposure in the ingest path.
- `Retry-After` handling and the provider registry refactor proceed now.
- P4 sequencing in `docs/STRATEGIC_GAP_REVIEW_2026-08-16.md` stands unchanged.

---

## 10. Decisions taken

**All three external items were decided on 2026-08-16. Nothing is commercially
blocked.**

| Item | Decision |
|---|---|
| SMS / WhatsApp (§6) | **Deferred for the pilot.** In-app + email only; both channels removed from selectors. |
| Licensed source display (§7) | **No publisher licence.** Allow-list stays official-only; no in-app display of commercial sources. |
| Court-data vendor (§9) | **Engineering posture accepted**; vendor selection stays parked and blocks nothing. |

Sign-off status:

1. **Workflow definition version 1 approver — named 2026-08-16: Sanjeev Kumar**
   (§1). No decision outstanding. The approval act itself still has to be applied
   at runtime against a seeded version 1, through the existing approval path, so
   the approver snapshot is persisted and auditable.
2. **Non-Indian registries scope** (§5) — still open, blocks nothing. The
   India-only seed ships either way.

One consequence flagged rather than assumed: the "no publisher licence" decision
answers *display*, not *corpus acquisition*. See §7.

---

## 11. Cross-references

- `docs/FEEDBACK_MERGE_BACKLOG_2026-08-16.md` §9 — the open items this resolves
- `docs/STRATEGIC_GAP_REVIEW_2026-08-16.md` §2.7 — the citation/trust-predicate
  finding that §7 folds into
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` — `EH-SGR-*`; D-1/D-2/D-3 recorded there
