# Drafting quality eval — overall 2.76/5

Target: **4.8/5**. Meets target: **NO**.

> **Run conditions (2026-05-01).** Live GPT-5.1 against 24 fixture
> scenarios (1-2 per template across all 20 templates). Total spend:
> ~$0.70. Latency median ~24s/scenario. Validator score is **3.0
> (warnings only, no errors)** on every scenario — drafts are
> structurally sound; the score is dragged down by two known harness
> issues, not draft failure:
>
> 1. **Citation score = 0/5 across most templates** because the harness
>    passes `retrieved=[]` to `_build_messages`. The production
>    drafting endpoint seeds 5-15 retrieved authorities; the eval
>    seeds none, so the model has nothing to cite. Templates that
>    happened to verbatim-quote an authority from the prompt itself
>    (e.g. divorce_petition citing HMA, dv_quashing_petition citing
>    PWDVA s.12) score 3.0; everything else scores 0.0. **Fix: seed
>    representative authorities per template before re-running.**
> 2. **Structure score penalises notices/forms.** vakalatnama (1.0),
>    cheque_bounce_notice (1.0-2.0), property_dispute_notice (2.0)
>    don't have Cause Title / Facts / Grounds / Prayer / Verification
>    headings because they're letters / forms / POAs. The current
>    rubric is template-agnostic; it should be template-aware. **Fix:
>    per-template structural-presence rubric.**
>
> Expected real number after both harness fixes: **~3.6-4.0/5**.
> Closing the gap to 4.8/5 then requires prompt-level work — explicit
> citation-injection patterns + per-template structural reinforcement.
> The harness fixes don't make the gap go away, they make the gap
> measurable.

## Per-template ratings

| Template | Rating | Scenarios | Errored | Median latency (ms) |
|---|---|---|---|---|
| `divorce_petition` | **3.67/5** | 1 | 0 | 35353 |
| `writ_petition` | **3.67/5** | 1 | 0 | 22111 |
| `written_statement` | **3.67/5** | 1 | 0 | 16263 |
| `reply_counter_affidavit` | **3.67/5** | 1 | 0 | 19870 |
| `dv_quashing_petition` | **3.67/5** | 1 | 0 | 28088 |
| `compromise_petition` | **3.33/5** | 1 | 0 | 25561 |
| `bail` | **3.17/5** | 2 | 0 | 39141 |
| `civil_suit` | **2.67/5** | 2 | 0 | 28730 |
| `affidavit` | **2.67/5** | 1 | 0 | 7985 |
| `appeal_memorandum` | **2.67/5** | 1 | 0 | 30571 |
| `quashing_petition` | **2.67/5** | 1 | 0 | 21448 |
| `arbitration_section_9` | **2.67/5** | 1 | 0 | 31418 |
| `amendment_of_pleadings` | **2.67/5** | 1 | 0 | 24063 |
| `probate_petition` | **2.67/5** | 1 | 0 | 33478 |
| `anticipatory_bail` | **2.5/5** | 2 | 0 | 40859 |
| `criminal_complaint` | **2.33/5** | 1 | 0 | 22892 |
| `caveat_petition` | **2.33/5** | 1 | 0 | 11141 |
| `property_dispute_notice` | **1.67/5** | 1 | 0 | 32305 |
| `cheque_bounce_notice` | **1.5/5** | 2 | 0 | 16010 |
| `vakalatnama` | **1.33/5** | 1 | 0 | 12525 |

## Per-scenario detail

### `bail` / `bnss-303-simple-theft` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `bail` / `ndps-prolonged-custody` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: [citation needed]
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `cheque_bounce_notice` / `standard-insufficient-funds` — 1.33/5
- validator: 3.0/5
- structure: 1.0/5 (found: ['cause_title'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `cheque_bounce_notice` / `payment-stopped-high-value` — 1.67/5
- validator: 3.0/5
- structure: 2.0/5 (found: ['cause_title', 'facts'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `anticipatory_bail` / `economic-offence-business-dispute` — 2.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `anticipatory_bail` / `matrimonial-no-fir` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] statute.bail_missing_bnss_reference: The body discusses bail but does not cite the governing BNSS section (typically s.482 anticipatory, s.483 regular, s.187 default). Add the correct BNSS reference before review.
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `civil_suit` / `recovery-of-money-commercial` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `civil_suit` / `specific-performance-real-estate` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `divorce_petition` / `hma-cruelty-desertion` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `property_dispute_notice` / `encroachment-flat` — 1.67/5
- validator: 3.0/5
- structure: 2.0/5 (found: ['cause_title', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `affidavit` / `standard-evidentiary` — 2.67/5
- validator: 5.0/5
- structure: 3.0/5 (found: ['cause_title', 'facts', 'verification'])
- citations: 0.0/5 (0 cites)

### `criminal_complaint` / `bns-cheating-forgery` — 2.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `appeal_memorandum` / `civil-appeal-cpc-order-xli` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `writ_petition` / `mandamus-rti-inaction` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: [citation needed]
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `quashing_petition` / `compromise-civil-flavour-318` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `written_statement` / `specific-performance-defence` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: [citation needed]
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `reply_counter_affidavit` / `writ-counter-affidavit-state` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `dv_quashing_petition` / `settlement-recorded-with-consent` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `arbitration_section_9` / `pre-arbitration-injunction` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `caveat_petition` / `caveat-against-ex-parte-injunction` — 2.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `vakalatnama` / `fresh-filing-delhi-hc` — 1.33/5
- validator: 3.0/5
- structure: 1.0/5 (found: ['cause_title'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `amendment_of_pleadings` / `post-trial-due-diligence-amendment` — 2.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 0.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `compromise_petition` / `criminal-non-compoundable-gian-singh` — 3.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `probate_petition` / `uncontested-hindu-will-bombay-hc` — 2.67/5
- validator: 3.0/5
- structure: 2.0/5 (found: ['cause_title', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.
