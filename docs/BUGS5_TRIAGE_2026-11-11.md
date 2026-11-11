# Ram Workbook 5: Triage And Acceptance

## Evidence Boundary

Source: `CaseOps_Bugs (5).xlsx`, Bug Sheet rows 2-21, SHA256
`0bc0288a03fb539abd5f9557e4739e1b6282f1c2af090fcd1ace1c0e631a776d`.
There are 20 populated, distinct reports, not 20 proven software defects.
The original workbook remains unchanged. Credentials are supplied at runtime,
not copied into this ledger or the output workbook.

On November 11 the reporting tester signed in through the actual production
form. Marked Playwright diagnostic reads before/after agree at API/web
`2816c29c30d8f13147f67a396f47321871096f0d`, API00524-bxl/web00499-snz.
This diagnostic is not fix acceptance. Fifteen captured page/tab views include
one unsettled statute-modal load, which is explicitly not option evidence.
Artifacts are in the primary workspace's
`outputs/bugs5-20261111/production-baseline-01/`.

PR597 is now merged through PR610. Its old local checkpoint is stale. Full
local Docker was interrupted; exact production QA42626416270 failed tester
and batch4, and certification did not run. Do not reuse earlier green hosted
components as certification of current production or this new candidate.
Native applications and MacBook/device acceptance are outside this task.

## Report Matrix

All row-level production verdicts start **Inconclusive** unless a concrete
present failure is named below. Candidate code, local tests, model quality,
source-data completion and production acceptance are separate fields.

| ID | Classification and current evidence | Existing ownership | Acceptance required before closure |
| --- | --- | --- | --- |
| B5-001 / BUG-001 | Mixed formatting defect candidate and court-rule enhancement. Retained draft body is editable text, contains unresolved factual placeholders and unrelated civil-revision citations. Review warnings are visible. Tester explicitly did not verify PDF parity. | J07/M06; US-017..021; FT-025..032; MOD-TS-008/012 | Compare the actual rendered paginated PDF preview and downloaded PDF for the same persisted version/profile, desktop/phone. Retain lawyer review and source/version-specific court-profile limitations. Formatting is not legal correctness or filing acceptance. |
| B5-002 / BUG-002 | Picker layout defect candidate. First production capture was loading, not settled options. | J03/J05/M02/M05; NFT-013/014; FT-090 | Settled long Act/section options, bounded popup, keyboard/scroll selection, attach and reload on desktop/phone. A genuinely pending section must remain unavailable. |
| B5-003 / BUG-003 | Confirmed placeholder leak plus composition/template enhancements. Actual retained email uses `{[client_name]}` and `{[hearing_date]}`, not only the report's `{{...}}` syntax. Existing admin template API is not a usable compose editor by itself. | J03/J08/M10; FT-046..048; MOD-TS-010 | Server preview and delivery use the same resolved values. Reject unknown/missing placeholders and malformed syntax. Manual compose/edit/save/preview has authorized UI proof. No external test email or provider acknowledgement counts as recipient delivery. |
| B5-004 / BUG-004 | Unconfirmed provider/matching/synchronization report. Exact supplied CNR, public case number, court and persisted tracked records need reconciliation. | J03/J08/M02/M08; FT-078..082/083 | Deterministic CNR and case-number/court matching plus pending/failure/recovery/manual/scheduled paths, persisted Matter and Calendar outcome. No weaker party-name match may override a conflicting CNR. Marked production tests cannot certify a credit-bearing provider result. |
| B5-005 / BUG-005 | Confirmed missing core metadata editor on the reported contract. Overview exposes only controlled type/legacy label. | J10/M09; FT-050; SEC tenant/role controls | Authorized full editable metadata save/reload/audit, validation, stale write and denial. Executed/terminal contracts retain their policy. |
| B5-006 / BUG-006 | Confirmed missing view action for an indexed PDF on the reported contract. | J04/J10/M03/M09; FT-053; NFT-013/014 | Authenticated PDF and DOCX actual visible content, navigation/zoom, original-byte download, permission revocation, responsive controls. No private third-party viewer. |
| B5-007 / BUG-007 | Legal-quality and authoring enhancement; screenshot/report does not reproduce faulty clause generation. Extraction already returns seven source clauses. | J10/M09; FT-051; SEC AI/source safety | Source-grounded clause editing/review and an independently reviewed legal benchmark with transaction/jurisdiction/version context. JSON-valid text is not legal suitability. |
| B5-008 / BUG-008 | Structured obligation/edit/approval/assignment enhancement. Actual retained rows include source quotes and `[auto]` markers. | J10/J08/M09/M08; FT-052/054 | Preserve source text separately from editable structured duty/party/trigger/date/frequency; no inferred unstated dates/consequences. Approve/promote/reload without duplicate tasks or events. |
| B5-009 / BUG-009 | Confirmed unreachable manual term-suggestion path: Terms(0) claims manual extraction but offers no action. Existing canonical dates do not imply an unreviewed suggestion should exist. | J10/M09; FT-050..054 | Explicit manual suggestion, source/evidence, accept/reject and canonical promotion/reload; extraction failures distinct. Never fabricate suggestions from already approved canonical dates. |
| B5-010 / BUG-010 | Extended playbook risk/replacement drafting enhancement and acceptance request, not reproduced broken comparison. | J10/M09; FT-051 | Compare an actual tenant-approved playbook, trace clause deviations and reviewer decisions; independently review legal replacement quality. No generic risk label proves legal validity. |
| B5-011 / BUG-011 | Native amendment/version/redline authoring enhancement. Existing Redline reads tracked changes in uploaded DOCX; it does not promise every metadata edit is a Word revision. | J04/J10/M03/M09 | Distinguish immutable original document, uploaded Word revisions, proposed app edits, accepted text and version history. Exact insertion/deletion/replacement/export acceptance before broader closure. |
| B5-012 / BUG-012 | Configuration/evidence dependency unless eligible active versions are proven missing from options. Existing empty states, governance link and disabled calculate action are intentional. | J08/M08; IP governed deadlines | Inspect exact jurisdiction/scope/status of persisted rule/calendar versions. Positive approved synthetic local workflow and negative pending/mismatch/permission tests. Do not invent or activate a legal rule in production. |
| B5-013 / BUG-013 | Retrieval report needing the exact question/session; research-response enhancement. A selected Matter is not proof that permitted verified evidence answers the question. | J05/J09/M04/M07; AST acceptance | Preserve policy/ACL/lifecycle/source manifests; reproduce query and source sufficiency; prove supported answer and safe abstention/recovery without paid automated calls. |
| B5-014 / BUG-014 | Unspecified search reliability report plus structured research-report enhancement. Cards alone are not a defect. | J05/M04/M15; US-010..013; FT-020..022; NFT-002/004/015 | Per-mode exact query/filters/candidate identity/relevance benchmark; source-grounded synthesis tested separately. No fabricated missing judgments or citations. |
| B5-015 / BUG-015 | Engineering-process enhancement. Existing suites/CI are real, but do not prove autonomous exhaustive diagnosis or safe automatic production repair. | J14/M14 | Route/workflow inventory, retained actual results, independent review and guarded release. Automatic code changes cannot bypass security, source, provider-cost or release gates. |
| B5-016 / BUG-016 | Compact-layout enhancement. No exact card/record/viewport supplied. Horizontal-only carousels are not the acceptance requirement. | J03/J09/J13/M02/M07/M12; NFT-013/014 | Define affected lists; accessible compact/expanded presentation, all records/actions reachable by keyboard and phone, meaningful title widths and no overlap. |
| B5-017 / ENH-017 | Reviewed directory/source coverage and update-feed enhancement. Forum-catalog hierarchy and judge directory are distinct existing data models. | J06/M05; US-060/062; FT-089/092/093 | Official source/edition/permission/update strategy, canonical identities, transfers/history, bounded synchronization and coverage accounting. Do not label a partial seed all-India complete. |
| B5-018 / BUG-018 | Confirmed legal-source coverage gap. Income-tax1961 and MotorVehicles1988 pages expose pending sections, not verified provision text. The fail-closed behavior is correct; business completeness is not achieved. | J05/M05; MOD-TS-017; US-061; FT-090 | Whole official numbered provision/continuation/schedule inventory, immutable source bytes and version/hash/link provenance, release-owned seed and positive browser opening/attachment. Preserve missing/conflicted provisions. Historical1961 and successor2025 applicability must be separately identified. |
| B5-019 / BUG-019 | Official IP synchronization integration enhancement, not evidence that a supported connector regressed. | J08/M08; IP source reconciliation | Confirm lawful machine interface/access contract, source identifiers, freshness, consent, budgets and audit; fixture/emulator success is not government live synchronization. No CAPTCHA/access-control bypass. |
| B5-020 / ENH-020 | Evidence/benchmark dependency plus proposed ML enhancement. Actual page honestly reports sample0 and missing bench IDs/aggregate snapshots. | J06/J09/M05/M07; predictive source controls | Supported descriptive source-backed aggregate and negative empty/weak sample; no invented probability, judge favorability or cross-tenant training. A trained model alone cannot establish calibrated legal usefulness. |

## Why Reports Reopen

These are engineering failures to prevent, not an allegation that every
Disposed Matter silently reactivated. No workbook row supplies a persisted
Disposed-to-Active event. Lifecycle behavior must be investigated using state
and audit events before changing those controls.

1. **Workflow evidence was narrower than the claim.** A create API or mocked
   extraction can pass while the detail page lacks Edit, View or Add. Add the
   actual complete saved/reloaded browser journey, including negative paths.
2. **Mixed reports were flattened into one status.** Fixing typography cannot
   certify court rules, legal relevance and PDF parity. Preserve each claim and
   remaining acceptance boundary; never close an entire row from one subfix.
3. **Source data and code were conflated.** Empty verified statutes or missing
   legal calendars must remain safe, but are still unfulfilled product outcomes.
   Record the data/approval/version dependency, not a false software success.
4. **Test fixtures did not match persisted inputs.** The actual placeholder
   spelling differs from the workbook. Use the original record/syntax and a
   realistic adjacent malformed case, not only a convenient new fixture.
5. **Release and documentation drift obscured reality.** The old597 checkpoint
   now contradicts merged610 and serving2816. Read remote and live identities
   and retain full failed/incomplete evidence. Merge, availability and a green
   component do not imply whole-release certification.
6. **Model output shape was confused with quality.** Citations, provenance,
   jurisdiction, legal relevance and independent benchmark review are separate
   from HTTP200, seven clauses or valid JSON. Do not train away missing evidence.
7. **First candidate tests still missed security-sensitive interleavings.**
   Independent review found that message facts could change after preview,
   contract locks could conflict with lifecycle actor locks, duplicate viewer
   controls could reuse authorized bytes after revocation, and body reads could
   outlive abort/deadline handling. A green mocked or sequential path would not
   detect these. These candidates are not released or accepted; repair and
   deterministic race/revocation tests are mandatory before the full gate.
8. **A new convenience path contradicted an old safety contract.** Eager PDF
   acquisition on a passive draft view conflicts with the retained production
   journey's no-export fence. Existing dated journeys are part of integration
   acceptance, not obsolete tests to weaken. Explicit PDF intent, authenticated
   recovery and exact source-byte proof must remain separate from passive reads.
9. **Test setup failures wasted acceptance time.** The first PostgreSQL attempt
   never reached assertions because its internal Docker network did not expose
   the requested loopback port; the second had an absent temporary parent path.
   Preserve both failures, positively probe the bounded database connection and
   storage root before launch, and rerun the complete intended inventory. The
   five original cases now pass in attempt03, but do not cover the newly found
   lifecycle overlap until the replacement tests execute.
10. **Mocks hid a real browser/CSP boundary.** The first fresh built preflight
    on51d64c93 executed all12 cases:5passed/7failed, no skips/retries. Both draft
    exports and workers returned200, but the renderer's Blob-URL fetch was
    blocked by CSP. Unit component mocks and an enabled download button had
    not proved a visible PDF. Consume the already-authorized Blob directly in
    draft and contract viewers, keep CSP unchanged and rerun actual canvas,
    text, pagination and exact-byte proof at both widths. Other retained
    failures exposed a canonical trailing-slash mismatch after successful
    Matter creation, unscoped contract selectors and mixed pointer/keyboard
    focus in the statute test. Preserve the native failures and complete12
    replacement inventory; do not increase timeouts or remove assertions.
11. **The verification harness introduced its own failures.** Preflight02 mixed
    browser-only API origins into the unit environment. Every one of its12
    failures in303files/2927cases is an exact-origin mismatch; the CSRF header
    was present. Preserve that failed run, use a separate canonical unit
    environment and rerun all files. Replacement04 passes all2927 in303files,
    then a fresh build, but its12 browser cases still have9pass/3fail. The two
    remaining compose failures use exact wrapping-label lookup despite a
    visible correctly named Message textbox. The phone contract failure is a
    DevTools body-lookup error, not a proven content mismatch; require an exact
    GET and verify the real completed browser download, retaining observed
    method metadata rather than assuming its cause.
12. **New fixture reads were not reconciled across release boundaries.** The
    communications AST test introduces three undeclared builder inputs. All25
    hosted hardening failures share that missing baseline, including negative
    tests intended to remove other inputs. Restore the narrow complete closure,
    preserve each independent negative check and include every uploaded input
    in the pre-cloud dirty-source fence. A green local build with extra working
    files cannot prove the production upload closure.

## Release And Regression Gate

### Prior Release Residuals Reconciled November 11

Exact2816 QA42626416270 retained five failed executions: both widths of the
November7 Contract and Teams journeys received `caseops-qa` credentials although
their authorization contract requires `test-legal`; they failed before their
business workflows. Preserve that tenant fence and route all four cases to a
properly credentialed, required release role. They are not reproduced parser,
Teams or mobile product defects.

The original Watch desktop journey was independently replayed from a clean,
exact2816 checkout against serving2816. It again failed the original line338:
the publication mark matched **four visible report rows** belonging to distinct
retained profiles. The API had already proved this run's hit, paused profile,
Not relevant disposition, exact reason and source snapshot. This newly retained
strict-mode diagnostic establishes selector ambiguity, not lost assessment or
provider failure. The corrected journey binds the rendered row to the exact
API-proven hit in the report's preserved row order, asserts full row cardinality,
and retains mark, disposition, exact reason, reload, scope and layout assertions.
Do not change the renderer or delete old tenant evidence to hide a test defect.

The old failed run and its18 unexecuted Batch4 mobile/governance cases remain
historical evidence. Later read-only monitoring and current green main
CI42613717583/Security43017042497 do not supply that missing whole-release proof.
Full corrected local Docker and new exact-release production replay are owed.

The bounded contract tracks extend US-007 and US-029..031, with FT-013/014 and
FT-050..054. Communications extends US-035/036 and FT-046..048. Cross-tenant,
matter/source access and revoked-session acceptance retain SEC-002..005;
responsive and keyboard acceptance retain NFT-013/014. These are required
test mappings, not claims of executed coverage.

Every confirmed fix needs a discovered committed Playwright regression for the
original outcome and its highest-risk adjacent path, at desktop and phone widths
where applicable. Record intended/collected/executed/pass/fail/skip/retry, source
SHA and exact artifacts. Run current-source builds, canonical full Docker, green
CI/Security/CodeQL, protected main merge, guarded exact-SHA deployment and complete
production replay before a Properly fixed verdict. Retain every failed attempt.

User withdrew the Claude Code dependency on November11. Independent Codex agent
review is required; do not invent a Claude acknowledgement. Native/MacBook work
and other projects remain untouched. All automated application requests use
`X-CaseOps-Automated-Test: no-paid-providers`; no synthetic email/lead/provider
credit spending is authorized by this regression task.

### Adjacent Boundaries Still Open

The new private draft/contract binary path consumes the complete response under
one authentication/deadline/cancellation boundary. Eight older successful-body
consumers still use the unread `apiBlobRequest` Response contract: Matter bulk
update templates, IP pleading DOCX and filing bundles, Matter attachment preview
acquisition, IP portfolio exports, IP import errors, generic bulk-import errors
and Notice downloads. Their successful body consumption remains outside that
helper's deadline, tracked in [issue613](https://github.com/mishrasanjeev/caseops/issues/613).
This audit does not certify them as repaired. A separate
bounded migration must preserve each source's supported sizes, cancellation,
headers, original bytes and authorization before closing that class globally.

The existing Matter email transport still retains its parent lock across
SendGrid I/O. The new template fence now permits compatible readers and excludes
edit/archive, proven by two actual PostgreSQL cases, but does not certify
transaction-free recipient delivery or exactly-once external sending. Keep the
transport risk open; committing before send without durable admission/recovery
would weaken lifecycle protection rather than resolve it.

## Primary Source Context

- Income Tax Department transition FAQ:
  https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/objective-and-scope-new-act-faq?mobile-app=1
  (read November11). The successor/transition is relevant; historical1961 data
  cannot simply be relabelled current2025 text.
- Official Motor Vehicles Act catalogue:
  https://www.indiacode.nic.in/indiacode/handle/123456789/1798
  (discovered November11; discovery is not a compiled verified seed).
- IP India e-services: https://www.ipindia.gov.in/pages/e-services
  and public patent query https://iprsearch.ipindia.gov.in/Query
  (read November11). Public UI availability does not grant an unrestricted API
  contract. No automated challenge solving or access bypass was attempted.
