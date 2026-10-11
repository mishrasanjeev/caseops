# AI Recommendations User Guide

## 1. Read This First

**Reviewed on 11 October 2026. Source-only documentation, not release acceptance.**

This guide describes the controls implemented in the checkout whose Git HEAD is
`dfda0eb3ee3d109f86092962a08d125878b24932`. It was prepared by reading the
recommendation pages, routes, services, schemas, permission rules, and error
messages. No browser, test suite, provider call, payment, deployment, or live
release-identity check was performed for this guide. Source in this shared
checkout is being updated by the release owner; a new file or local change is
not evidence that production serves it.

**October continues under the current behavior. Do not pause October AI use
because of the new budget policy.** The current source implements the shared
money-admission guard with **enabled by default** and **start month `2026-11`**.
It applies only when enabled and the current budget month, calculated in IST,
is at or after that start month. October therefore bypasses this new guard
because it precedes November, not because the default is off. Existing AI
credits, token quotas, and provider readiness still apply; this statement does
not remove an existing restriction.

The ceiling is **INR 10,000 shared across all paid providers**, not a separate
allowance for each provider. The guard, schema, and monthly-policy initializer
are implemented in source, but their tests, release, production deployment,
and effective activation are **not verified here**. At or after the start month,
an enabled guard refuses paid admission if the month's reconciled policy is
missing or invalid; it does not silently grant a fresh allowance. The intended
boundary covers paid SDK calls from API requests, background jobs, and local/CLI
execution, not only HTTP routes. Full caller coverage still requires verification.

There is no verified INR 10,000 budget dashboard, switch, warning threshold, or
cap-exhaustion recovery button to instruct a user to click. The old proposed
budget amounts are superseded. Gemini migration or fallback is under evaluation,
not an authorized production switch. A paid fallback cannot bypass the shared
ceiling. See Section 9 for the source-implementation and verification boundaries.

AI Recommendations is **decision support for a lawyer**, not legal advice, a
prediction of success, a filing, or an automatic instruction to a court or
colleague. An accepted suggestion does not perform the suggested action.

## 2. Where To Find It

| Purpose | Screen name | Route |
| --- | --- | --- |
| Choose a matter | Recommendations | `/app/recommendations` |
| Generate and review AI options | AI Recommendations, within a matter | `/app/matters/{matter_id}/recommendations` |
| Record human-authored plans and decisions | Strategy Plan, within a matter | `/app/matters/{matter_id}/strategy` |
| Look up supporting authorities | Grounded legal research | `/app/research` |
| Review generation and decision events | Matter Audit, within a matter | `/app/matters/{matter_id}/audit` |
| Inspect workspace token controls | Workspace AI policy on Workspace admin | `/app/admin` |
| Inspect subscription credits and usage | Plan, usage, invoices, and credits; Usage report | `/app/admin/billing` and `/app/admin/billing/usage` |

`{matter_id}` is the identity of an existing matter selected in the application.
Do not invent an ID or use another workspace's link.

### Open An Existing Matter

1. Sign in to the correct workspace with your own authorized account.
2. Open **Recommendations** at `/app/recommendations`.
3. In **Recent matters**, use **Filter matters** to match the title, matter code,
   practice area, or client name. Select the matching matter row.
4. Confirm the matter identity before generating. The destination is its
   **AI Recommendations** tab.
5. Alternatively, open the matter from **Matters**, then select
   **AI Recommendations** in its cockpit tabs. On a narrow screen, scroll the
   tab strip horizontally to find the label.

The hub loads a bounded recent list of up to 200 matters; its filter works on
that loaded list, not an exhaustive server-wide search. If an authorized matter
is not in the hub, open it from **Matters** instead. **No matter matches** is not
proof that the record was deleted. **Could not load matters** is a read failure,
not a confirmed empty workspace.

## 3. Prerequisites And Permissions

Before generating, check the following:

- You can currently access the matter in the signed-in workspace, including any
  restricted-access grants or ethical-wall rules.
- The matter can receive operational work. The source permits an active
  `Intake`, `Active`, or `On Hold` record; terminal or inactive records are
  refused. Do not reopen a matter merely to force AI generation.
- The matter's description, relevant facts, practice area, forum, court,
  procedural status, and dates are accurate. Separate allegations and assumptions
  from established facts. Do not add invented details to obtain a citation.
- Relevant hearings, orders, linked statutes, and readable processed attachments
  are recorded where available. Uploading a file does not guarantee that its text
  has been extracted or included in the recommendation context.
- The workspace's AI policy permits the operation, applicable token and credit
  checks allow it, and the configured provider is ready. A configured key or a
  enabled-looking button alone does not prove readiness.
- The authority corpus contains suitable sources. A recommendation can be
  refused even when the account, provider, and matter are otherwise ready.

### Default Role Permissions

| Operation | Capability | Default roles |
| --- | --- | --- |
| Read recommendations | Authenticated context plus current matter access | Subject to matter visibility |
| Generate the four AI recommendation types | `recommendations:generate` | Owner, Admin, Partner, Member |
| Accept, reject, or defer a recommendation | `recommendations:decide` | Owner, Admin, Partner |
| Manage human Strategy Plan entries | `strategy:approve` | Owner, Admin, Partner |
| Manage workspace token policy and subscription billing | `workspace:admin` | Owner, Admin |
| Export audit history | `audit:export` | Owner |

These are defaults, not a substitute for effective permissions. Custom roles,
membership state, workspace state, and record-level access can change what your
account is allowed to do. The current AI Recommendations page does not hide all
mutation controls according to these capabilities; the server can refuse a
visible button. Ask the workspace administrator to verify your authorization
instead of repeating a denied request or using another person's login.

The **Workspace assistant** toggle is for the separate assistant surface. It is
not a switch for turning this recommendation workflow on or off.

## 4. Generate A Recommendation

1. Open the matter's **AI Recommendations** tab.
2. In **What are you thinking or planning for this matter?**, optionally describe
   the specific question or proposed course of action. The field accepts up to
   1,200 characters. Include the issue, relevant posture, known facts, and what
   you need counsel to evaluate. This text is request context; it is not a saved
   human Strategy Plan entry.
3. Choose **Objective**. The implemented choices are **Matter status**,
   **Litigation strategy**, **Settlement strategy**, **Compliance risk**,
   **Contract risk**, **Case preparation**, **Appeal strategy**, and
   **Lawyer thinking**.
4. If you select **Lawyer thinking**, enter nonempty thinking text first. Otherwise
   the page shows **Add lawyer thinking before generating.** With the default
   **Matter status** and nonempty thinking text, the server uses that text as a
   custom goal rather than ignoring it.
5. Select one output button:

| Button | Use it to request |
| --- | --- |
| Authority | Relevant supporting authorities for the issue |
| Forum | Source-backed forum or jurisdiction options for lawyer review |
| Remedy | Source-backed relief or remedy options |
| Next-best action | Possible next procedural or practical steps for review |

The **Objective** is the context for the chosen output type. Selecting
**Litigation strategy** in this dropdown does not navigate to, create, or approve
a human **Strategy Plan** entry. Historical AI litigation-strategy rows belong
to the separate Strategy Plan surface and are excluded from this tab.

6. Click once. The selected button shows **Generating...**, and generation
   buttons are disabled while that request is pending. Do not start the same
   request in another tab or repeatedly click after navigating away.
7. On success, the page refreshes its saved recommendation list and shows
   **Recommendation ready for review**. Inspect the new card and its generated
   timestamp. New cards start with review required.
8. Reload the tab to confirm that the card is saved before treating the operation
   as complete. Each intentional generation is a new request; there is no visible
   generation-deduplication or durable queue/resume control on this page.

Example thinking text, only if it truthfully matches the record:

> Identify authorities relevant to whether an extension to file a reply may be
> available. Distinguish missing facts and applicable procedural requirements;
> do not predict the outcome or select a judge.

Never request success percentages, a favorable judge, judge shopping, illegal
conduct, invented facts, or a final legal opinion. The server can refuse such
an objective or output instead of saving a recommendation.

## 5. Review Every Option And Its Sources

Do this before making a decision:

1. Confirm the card's **type**, **status**, **Generated** time, overall confidence,
   and **Partner review required** indicator.
2. Read the overall rationale. Where present, also read **Recommendation**,
   **Risk analysis**, **Legal impact**, **Suggested actions**, **Confidence score**,
   and the confidence explanation. Older cards may not have this analysis block.
3. Read every numbered option, its own rationale, confidence, citations, and risk
   notes. **Primary** means the system's selected leading option, not a lawyer's
   approval or a finding of legal correctness.
4. Read **Assumptions**, **Missing facts**, and **Next action**, where present.
   Resolve significant gaps before relying on the output. A next-action sentence
   does not create a task, hearing, deadline, filing, or external message.
5. If the card shows **Sources considered: ... cited: ...**, inspect it. Expand
   **Considered but not cited** to see retrieved identifiers that were not cited
   in any option. The panel may be absent on older rows; absence does not prove
   that all possible sources were reviewed.
6. Independently open and read relevant authorities before relying on a
   proposition. Citations on the recommendation card are text chips, not
   source-opening links. Use **Grounded legal research** at `/app/research`,
   choose **CaseOps corpus**, search the cited case reference or title, and use
   the matching result's available **Source** action. Confirm the court, date,
   case identity, holding, procedural posture, and later treatment yourself.
7. If the source action is missing, unverified, blocked, or quarantined, read its
   reason. Use **Report** when that action is offered. Do not replace a refused
   source with a guessed URL or treat a missing match as a verified judgment.

Source lookup can itself involve a charge-bearing service. Do not assume that
an indexed-corpus search or a different research provider is automatically free;
use the current readiness, authorization, and applicable budget rules.

### What Citation Verification Does And Does Not Mean

The standard recommendation service retrieves a bounded set of authorities and
passes title, summary, and snippet text for grounding; it is not a full search of
every judgment or a full read of every matter document. Its matter context is
also bounded: recent hearings and orders, a limited set of statute references,
attachment excerpts, and recent activity. Older or truncated material can be
outside the prompt. A fact appearing somewhere in the workspace is not proof
that this particular recommendation considered it.

The citation gate resolves a cited source and checks topical overlap between
the option's rationale and the available source text. **It does not prove that
the source entails the proposition, resolve a negation or contrary holding,
certify that the law is current, or verify the full judgment.** It is a safety
filter, not a legal opinion. Do not describe it as preventing all hallucinations.

At least one verified citation across the recommendation is required to save it.
That does **not** require every option to have a verified citation. An individual
option can show **No citations survived verification for this option.** Do not
accept that option as source-supported simply because a different option has a
citation. An option with no verified citations is assigned low confidence; a
single verified citation cannot support high confidence under the source's cap.

Confidence labels are **low**, **medium**, or **high**, not calibrated win
probabilities or a substitute for counsel's assessment. The optional bench-aware
authority rerank depends on tenant policy and available indexed bench history;
it is not universal coverage, judge selection, favorability scoring, or an
outcome forecast. Check contrary and omitted authorities independently, too.

## 6. Record A Review Decision

Use an account with the decision capability and current matter access.

| Visible control | What it records | What it does not do |
| --- | --- | --- |
| Accept this option | `accepted`, with that option's index; acceptance clears review required | Does not file, execute the next action, or create/approve a human strategy entry |
| Defer | `deferred` | Does not schedule a reminder, collect a reason, or set a due date |
| Reject all | `rejected` for the recommendation | Does not delete the saved recommendation or undo an earlier real-world action |

1. Finish the source and fact checks in Section 5.
2. Select **Accept this option** on the exact option you approve, **Defer** if
   review is unfinished, or **Reject all** if the recommendation should not be
   used.
3. Wait for the decision request and list refresh. Decision buttons are disabled
   while a decision is being recorded.
4. Confirm the status and **Last decision** on the card, then reload and confirm
   the same persisted state. The accept buttons are disabled once the card is
   accepted; this is not a general undo or replace-approval workflow.
5. Treat a failed decision message as unconfirmed. Read the current saved card
   and audit history before sending the decision again.

### Editing And Recording Counsel's Actual Plan

There is **no inline Edit button, decision-notes form, or complete decision-history
timeline** on the standard AI Recommendations card. The API supports an `edited`
decision and optional notes, but recording that decision does not rewrite the
generated option text. Do not look for an unimplemented UI editor or treat the
disclaimer's word "editing" as a clickable workflow.

To record counsel-owned work product with the appropriate permission:

1. Open the matter's **Strategy Plan** tab.
2. In the human entry form, enter **Title**, choose **Type** (**Plan**, **Decision**,
   or **Note**), and choose **Status** (**Draft**, **Active**, or **Archived**).
3. Write the reviewed plan or reasoning in **Entry**, distinguishing verified
   facts, unresolved questions, and any AI suggestion you considered.
4. Select **Add**, wait for the saved entry, and reload to confirm persistence.
   If the form is not offered, ask the administrator to verify `strategy:approve`.

This is a separate human-authored record, not an edit of the AI recommendation.
AI acceptance does not populate or approve it automatically. Do not mark a plan
Active merely because the AI card is accepted.

## 7. Find Prior Recommendations And The Audit Trail

Saved standard recommendations are listed newest first on the matter's
**AI Recommendations** tab. Older generated cards remain available subject to
current matter visibility; new generation is not an update of the old card.

The current card shows **Not yet decided** or its **Last decision**, not every
decision's actor, timestamp, and notes. For audited events:

1. Select **Matter Audit** within the same matter.
2. Set **From** and **To** for the relevant period if needed.
3. In **Action**, enter `recommendation.generated` for generation or
   `recommendation.decided` for a review decision. Use the **Actor** or **Search**
   filters to narrow the results.
4. Inspect the event's action, result, target identity, actor, timestamp, and
   available metadata. Clear restrictive filters if no event matches; a failed
   audit load is not proof of absent history.
5. With `audit:export`, use **JSONL** or **CSV** for the authorized filtered audit
   export. Without that capability, request the export through the authorized
   workspace owner rather than bypassing access control.

The API retains decision records with actor identity, decision, selected option,
optional notes, and timestamp. The audit display is an event view with a bounded
metadata preview, not a full recommendation/decision editor or a guaranteed
display of every retained detail. A refusal may have model-run evidence without
a saved recommendation; operators should correlate the actual failure record
instead of expecting a successful-generation event for it.

### Source And Lifecycle Fences

Generation checks tenant-scoped matter access and operational state. After model
work, the service reloads the matter, reacquires the lifecycle fence, compares
its lifecycle version, rebuilds the bounded prompt context, and refuses saving
if that context changed. A disposal/reopen cycle or a source change while the
request runs can therefore produce **No recommendation was saved**.

Decision persistence also requires current matter access and an operational
matter. Retained history is not permission to mutate a terminal record. A
generation or review decision must not reopen it.

A saved recommendation remains a **snapshot**, not a live legal opinion.
Standard recommendation reads do not automatically regenerate it or rerun its
original citation verification. Do not assume a previous acceptance remains
appropriate after facts, access, source text, hearing posture, or applicable law
change. Re-review and, when permitted, generate a fresh recommendation. The
private-generation manifest rules of **Intelligence Review** and the workspace
assistant are separate workflows; do not infer that this standard card provides
their saved-source revocation or manifest controls.

## 8. Pending, Failed, And Budget Recovery

**Read the full error detail, not only the banner heading.** The current page
uses a broad "generation needs more grounding" heading for several non-quota
failures. The detail distinguishes missing evidence, lifecycle changes,
permissions, billing, and availability.

| State or message | What to do |
| --- | --- |
| Loading recommendations | Wait for the list read. This is not confirmation of a saved generation. |
| No AI recommendations yet | The read succeeded with no standard AI cards. Check the selected matter before generating. |
| Could not load recommendations | Use the read error's Try again when appropriate. It reloads the list; it does not generate a new recommendation. |
| Generating... | Wait for the pending request. There is no visible durable background-job or resume control on this screen. If transport fails, inspect saved cards before starting another request. |
| No grounding authorities were retrieved for this matter | Add accurate facts, sections, and forum context to the matter description; check corpus coverage. A richer description cannot create a missing source. |
| The model returned citations, but none matched verified authorities in the corpus | Check relevant corpus sources and the factual context. Repeated unchanged generation is not a substitute for usable evidence. |
| Unsupported custom goal or unsupported output wording | Reframe as source-backed lawyer decision support without prediction, judge selection, illegal conduct, or final legal advice. Do not bypass the refusal. |
| The matter lifecycle changed, or the matter or its source material changed while generation ran | Reload the matter and inspect current state and source material. Retry only if the current record still permits the work; never reopen solely to make a request succeed. |
| Cannot generate a recommendation / record a recommendation decision because this matter is disposed | Keep the terminal state intact. Ask the authorized matter owner to review the legitimate lifecycle workflow if required. |
| A capability denial or tenant AI-policy denial | Ask the workspace administrator to verify effective permissions and the recommendation policy. Changing an assistant toggle or using another account is not recovery. |
| AI token quota exceeded. Contact your workspace admin to adjust the monthly token policy. | Ask an authorized admin to inspect Monthly token governance. Do not equate token quota with an INR ceiling or remove a quota without approved policy. |
| AI credit balance is insufficient for this action. | Ask a workspace owner/admin to inspect subscription credits and eligible top-ups. A payment screen or checkout redirect alone does not prove credits were granted. |
| Configured AI provider quota is exhausted; restore or top up provider credits, then retry; no output was saved | The provider account operator must resolve that provider's quota/billing. Buying CaseOps subscription credits alone may not resolve provider-account exhaustion. |
| Authority retrieval is temporarily unavailable | Wait for retrieval recovery; do not classify it as an empty corpus or fabricate supporting sources. Escalate persistent failures. |
| Provider timeout, temporary upstream error, or connection failure | Wait as directed, inspect the current saved list/audit first, then make at most one deliberate new request after recovery. An interrupted response can have an uncertain outcome. Do not automatically replay a mutation. |
| AI monthly spending is awaiting reconciliation. No external request was sent. | This refusal is implemented in the future-period guard's source, not verified as a live UI state here. At or after the start month, the operator must reconcile the month's opening spend and pricing policy before paid admission. A missing policy is not an unused allowance. |
| The shared monthly AI budget is exhausted | This refusal is implemented in source, not verified as a live UI state here. Further paid calls, including paid Gemini fallback, must remain blocked unless the reconciled policy admits them. A new month also requires its own reconciled policy; changing providers or buying unrelated credits cannot bypass the cap. |

The generation-error banner offers **Try again** and **Dismiss**. **Try again**
sends a new generation request of the same type using the current objective and
thinking fields. Correct the cause first. **Dismiss** hides local guidance; it
does not fix the cause, refund spend, remove an audit record, or cancel provider
work. The generation-error banner is page-local, not durable failure history.

**No output was saved does not mean no provider cost was incurred.** A provider
can consume tokens before a response is refused, fails validation, or loses a
post-call source/lifecycle check. Reconcile actual accounting evidence; do not
promise a refund or charge amount from the recommendation's status alone.

### Existing Admin Recovery Screens

- At `/app/admin`, inspect **Workspace AI policy > Monthly token governance**:
  **Firm used**, **Firm quota**, **Remaining**, and **Warning**. Authorized policy
  edits use **Firm monthly tokens**, **User monthly tokens**, **Warning %**, and
  **Save token policy**. The units are tokens. Blank quota fields mean unlimited
  under this existing policy; do not blank them to evade another budget.
- At `/app/admin/billing`, open **Usage report**, or go directly to
  `/app/admin/billing/usage`. Inspect **AI credits used**, **Top-up credits**, and
  the usage breakdown. Use **Buy credits** or **Buy credits/capacity** only with
  authorized billing action and configured merchant readiness. Confirm the
  backend-verified checkout and refreshed credit ledger before generating again.
- Existing licensed-source provider spend reporting is not proof that all AI
  providers are already admitted under the new INR 10,000 aggregate cap. The
  release owner must reconcile that contract before making such a claim.

For support, provide the workspace, matter code, output type, time and timezone,
visible error detail, and any available request/model-run identity. A refusal can
return `X-Model-Run-Id`, but the current recommendation card does not display a
copyable failure receipt. Ask an authorized operator to correlate it. Do not
send passwords, API keys, session cookies, authorization headers, or unnecessary
private document content in a support report.

## 9. New Shared Budget And Gemini Evaluation Status

Operators should use the [shared spending reconciliation runbook](runbooks/ai-spending-reconciliation.md)
for initialization, evidence retention and exhaustion diagnosis. Its conservative
reservations are not provider invoices; all paid executors must share one
authoritative database. The [dated Gemini assessment](AI_PROVIDER_BUDGET_GEMINI_ASSESSMENT_2026-10-11.md)
records current official research separately from deployment and legal-quality
acceptance.

This section distinguishes **current source implementation** from owner direction
and **unverified deployment or runtime behavior**. No budget initializer or paid
call was run for this guide.

| Item | Status and boundary |
| --- | --- |
| October operations | Continue current behavior. The new guard's source bypasses October because the current month is before its configured `2026-11` start, even though enabled defaults to true. No October pause was introduced here. Existing policy/readiness restrictions remain. |
| New monthly money policy | INR 10,000 total, shared by all paid providers. The guard, schema, and initializer exist in source. Enabled defaults to true; the guard applies from `2026-11` unless reviewed configuration changes it. Tests, release, deployment, and effective activation remain unverified. |
| Missing monthly policy after the start | With the guard enabled, missing or invalid reconciliation refuses paid admission before transport. The source initializer records opening liability and pricing evidence; replay cannot reset admitted liability or silently replace the policy. Its execution and production policy rows were not verified here. |
| Warning and conservative margin | Require a reviewed reservation/pricing policy; no replacement warning or operating amount is invented here. |
| All-provider coverage | Admission is implemented at paid SDK boundaries, not only API routes; the required scope includes jobs and local/CLI callers as well as primary, fallback, retry/repair, embedding/reranking, and any paid retrieval/lookup. Full coverage and supported cost bounds remain verification work; unsupported charge paths must fail closed once the guard applies. No paid provider or execution mode may evade the aggregate cap. Stricter existing provider limits do not create a separate spending allowance. |
| Budget UI | No INR budget dashboard, warning control, or recovery button was verified. Existing token and subscription-credit screens are not a dashboard for this shared money policy. |
| Gemini capability in source | An adapter and provider-factory branch exist. That is not proof of configured credentials, privacy approval, sufficient legal quality, cost coverage, full AI-call parity, or production readiness. |
| Full move to Gemini | Evaluation requested; no production switch authorized or performed. Users do not select a provider from this recommendation page. |
| Gemini after another provider's quota exhaustion | A prospective availability fallback, subject to authorization and remaining shared capacity. It is not automatically configured or accepted here. |
| Gemini after the shared cap is exhausted | A paid fallback must be denied by the same aggregate cap. Different pricing or a different credential does not replenish the allowance. Do not assume an API tier is free. |
| Deployment and paid acceptance | Not checked for this guide. Record exact serving API/web revisions and acceptance separately before describing any new control or provider change as live. |

### Evidence Needed Before Any Gemini Switch

1. **Legal benchmark:** compare identical approved legal scenarios, full source
   texts and expected results. Measure citation identity and proposition fidelity,
   contrary holdings, missing-fact handling, unsafe/refusal behavior, and
   structured-output validity. Do not judge quality from a successful HTTP status
   or a persuasive sample answer.
2. **Pricing and accounting:** review current official terms and input, output,
   reasoning, cached-token and any auxiliary charges; retain dated evidence.
   Reconcile native usage, currency conversion and conservative reservations
   before and after every paid attempt under the same INR 10,000 policy.
3. **Privacy and legal authority:** approve processing location, retention,
   training/data-use terms, permitted document content, tenant restrictions, and
   contractual requirements before sending private material. An available Google
   Cloud account is not by itself consent or provider readiness.
4. **Runtime parity:** prove strict-output handling, total deadlines, bounded
   retries, source and lifecycle revalidation, audit/accounting durability,
   cancellation/crash recovery, and no duplicate side effects across callers.
   Existing adapter presence cannot establish these controls.
5. **Release readiness:** validate supported credentials and SDK/runtime,
   purpose-specific policy, migration compatibility and regression coverage;
   use the guarded exact-SHA release process and live replay. A paid human
   acceptance, if later separately authorized, must retain a meaningful
   source-backed result and actual account evidence.

No official pricing, privacy approval, comparative legal benchmark, free-tier
eligibility, or live Gemini paid result was acquired in this source-only task.
Those are open research/verification requirements, not completed findings.

## 10. Administrator Verification Checklist

Before circulating this as instructions for a particular production release:

- [ ] Record exact serving API and web revision identities; distinguish deployed
  behavior from this source guide and from a dirty candidate.
- [ ] Check effective generation/decision capabilities, active membership and
  workspace, matter ACLs/ethical walls, and operational lifecycle state.
- [ ] Confirm accurate matter facts, current document processing state, suitable
  corpus coverage, and usable source actions. Do not mark missing legal evidence
  verified to make the AI return output.
- [ ] Confirm server-side provider readiness and approved privacy/terms without
  exposing secret values. No model name or API key is needed in user instructions.
- [ ] Distinguish provider-account quota, CaseOps subscription credits, existing
  token quotas, and the source-implemented shared money policy when diagnosing
  a refusal.
- [ ] Preserve October behavior. Verify the deployed enabled/default-true setting,
  `2026-11` start month, and IST month comparison separately; October bypasses
  because it is before the start, not because the default is off. Do not infer
  activation from documentation, a migration, a build, or a provider change.
- [ ] Before the start month, verify the release schema and reconcile that month's
  opening liability, exact pricing evidence, and currency/fee policy. Prove an
  enabled post-start guard refuses a missing or invalid monthly policy instead
  of treating it as zero spend or an automatic new-month reset.
- [ ] Prove one common INR 10,000 ledger/admission boundary across all paid SDK
  paths, including API, jobs and local/CLI execution, reservations, actual usage,
  failures, retries, fallback and machine recovery. Confirm a paid Gemini switch
  cannot escape exhaustion. Do not invent warning or margin values, or describe
  the existing token/credit screens as an INR budget dashboard.
- [ ] Verify generation, reload, source checks, accept/defer/reject, current access
  denial, disposed-matter denial and history on the exact intended release.
- [ ] Run automated verification with
  `X-CaseOps-Automated-Test: no-paid-providers` and deterministic emulators/stored
  approved evidence only.
  Never remove the marker to obtain a paid success. Such runs prove the workflow
  and isolation boundaries, not paid-provider quality or operational acceptance.
- [ ] Keep skipped, unexecuted, interrupted, failed, or emulator-only paths
  explicitly classified. A configured provider, green source test, or accepted
  mock recommendation is not proof of a paid integration working end to end.

## 11. Source References And Documentation Limits

PRD mapping: **J09 / M07 / US-026, US-027, US-028 / FT-034, FT-035, FT-036**.
Related policy/billing/access concerns are **M14 / M10 / M13**. This guide adds no
feature, permission, provider activation, or release-closure claim. Historical
roadmap text describing only two recommendation types is not the current page's
four-button contract; conversely, API support for editing is not a UI editor.

The following references support the steps above. Paths are repository-relative;
line numbers identify the inspected source, not a production execution trace.

| Subject | Source reference |
| --- | --- |
| Matter tab names and routes | `apps/web/components/app/MatterCockpitNav.tsx:13` |
| Recent-matter hub, local filter and 200-row read | `apps/web/app/app/recommendations/page.tsx:23` |
| Objectives and request inputs | `apps/web/app/app/matters/[id]/recommendations/page.tsx:63`, `:154`, `:241` |
| Four generation buttons, pending state and success/error copy | `apps/web/app/app/matters/[id]/recommendations/page.tsx:121`, `:271`, `:578` |
| Card options, citation chips, decisions and source panel | `apps/web/app/app/matters/[id]/recommendations/page.tsx:360`, `:643` |
| Human Strategy Plan fields and Add action | `apps/web/app/app/matters/[id]/strategy/page.tsx:333` |
| Matter Audit filters, previews and export controls | `apps/web/app/app/matters/[id]/audit/page.tsx:54` |
| Generation and decision capability dependencies | `apps/api/src/caseops_api/api/routes/recommendations.py:46`, `:263`, `:304` |
| Default generation/review roles | `apps/api/src/caseops_api/services/capability_catalog.py:5`, `:86` |
| API thinking length and decision notes contract | `apps/api/src/caseops_api/schemas/recommendations.py:107`, `:130` |
| Bounded authority retrieval and matter context | `apps/api/src/caseops_api/services/recommendations.py:678`, `:1001` |
| Tenant-scoped access and generation lifecycle admission | `apps/api/src/caseops_api/services/recommendations.py:1464`, `:1619` |
| Post-call lifecycle/source comparison and refusal | `apps/api/src/caseops_api/services/recommendations.py:1782` |
| Citation refusal, confidence and review-required persistence | `apps/api/src/caseops_api/services/recommendations.py:1863`, `:1925` |
| Saved list, decision history, state updates and audit | `apps/api/src/caseops_api/services/recommendations.py:2044`, `:2089` |
| Citation topicality rather than entailment | `apps/api/src/caseops_api/services/citations.py:162` |
| Source actions and refused-source state | `apps/web/components/app/SourceAction.tsx:59`, `:109`; `apps/web/app/app/research/page.tsx:328`, `:1282` |
| Operational-state boundary | `apps/api/src/caseops_api/services/matter_operational_guard.py:14`, `:64` |
| Provider quota recovery message | `apps/api/src/caseops_api/services/llm_http.py:8` |
| Existing token-quota refusal | `apps/api/src/caseops_api/services/ai_token_governance.py:68` |
| Existing credit-balance refusal | `apps/api/src/caseops_api/services/saas_billing.py:1389` |
| Actual admin token controls | `apps/web/components/app/TenantAIPolicyCard.tsx:249` |
| Actual billing/usage/top-up screens | `apps/web/app/app/admin/billing/page.tsx:354`, `:599`; `apps/web/app/app/admin/billing/usage/page.tsx:239` |
| Gemini adapter and factory branch, not switch acceptance | `apps/api/src/caseops_api/services/llm.py:863`, `:1048` |
| Automated no-paid provider selection | `apps/api/src/caseops_api/services/llm.py`, `build_provider()`; `apps/api/src/caseops_api/core/automated_test_context.py:34` |
| Default-on guard and November start setting | `apps/api/src/caseops_api/core/settings.py:376`, `:492` |
| IST start-month condition and missing-policy refusal | `apps/api/src/caseops_api/services/ai_money_budget.py:44`, `:48`, `:112` |
| Shared ceiling and pre-transport budget reservation | `apps/api/src/caseops_api/services/ai_money_budget.py:28`, `:72` |
| Monthly-policy and admission schema | `apps/api/src/caseops_api/db/ai_spend_models.py:13`, `:39`; `apps/api/alembic/versions/20261011_0001_shared_ai_money_budget.py` |
| Reconciliation initializer and liability-preserving replay | `apps/api/src/caseops_api/scripts/reconcile_ai_money_budget.py:24`, `:36` |
| Paid SDK admission outside route-only enforcement | `apps/api/src/caseops_api/services/llm.py`, provider `generate()` implementations; `apps/api/src/caseops_api/services/embeddings.py:76`, `:85` |
| PRD journey, stories and tests | `docs/PRD_CODEX_2026-04-23.md:980`, `:1443`, `:1576` |

The release owner's provider adapters, budget settings, schema, guard, and
initializer were being changed during this source-only review. Their line
numbers, complete caller coverage, and deployed configuration require a fresh
source/release check before final publication. Source implementation does not
certify tests, migration execution, reconciled production policy, effective
activation, unchanged financial accounting, or production deployment.
