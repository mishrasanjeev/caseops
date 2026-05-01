# Drafting quality eval — overall 4.06/5

Target: **4.8/5**. Meets target: **NO**.

## Per-template ratings

| Template | Rating | Scenarios | Errored | Median latency (ms) |
|---|---|---|---|---|
| `quashing_petition` | **5.0/5** | 1 | 0 | 40164 |
| `civil_suit` | **4.33/5** | 2 | 0 | 33095 |
| `divorce_petition` | **4.33/5** | 1 | 0 | 30249 |
| `appeal_memorandum` | **4.33/5** | 1 | 0 | 30890 |
| `writ_petition` | **4.33/5** | 1 | 0 | 30624 |
| `dv_quashing_petition` | **4.33/5** | 1 | 0 | 40524 |
| `arbitration_section_9` | **4.33/5** | 1 | 0 | 36127 |
| `vakalatnama` | **4.33/5** | 1 | 0 | 14203 |
| `amendment_of_pleadings` | **4.33/5** | 1 | 0 | 25205 |
| `compromise_petition` | **4.33/5** | 1 | 0 | 26609 |
| `probate_petition` | **4.33/5** | 1 | 0 | 30340 |
| `bail` | **4.0/5** | 2 | 0 | 46687 |
| `written_statement` | **4.0/5** | 1 | 0 | 23977 |
| `anticipatory_bail` | **3.83/5** | 2 | 0 | 35066 |
| `property_dispute_notice` | **3.67/5** | 1 | 0 | 27953 |
| `reply_counter_affidavit` | **3.67/5** | 1 | 0 | 24296 |
| `caveat_petition` | **3.67/5** | 1 | 0 | 19318 |
| `cheque_bounce_notice` | **3.33/5** | 2 | 0 | 21324 |
| `affidavit` | **3.33/5** | 1 | 0 | 10054 |
| `criminal_complaint` | **3.33/5** | 1 | 0 | 27503 |

## Per-scenario detail

### `bail` / `bnss-303-simple-theft` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: (2014) 8 SCC 273

### `bail` / `ndps-prolonged-custody` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `cheque_bounce_notice` / `standard-insufficient-funds` — 3.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['from', 'to', 'instrument', 'demand'])
- citations: 3.0/5 (2 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 2 identifier(s) that never appear as inline anchors in the body: (2014) 9 SCC 129, (2013) 1 SCC 177

### `cheque_bounce_notice` / `payment-stopped-high-value` — 3.33/5
- validator: 5.0/5
- structure: 2.0/5 (found: ['instrument', 'demand'])
- citations: 3.0/5 (1 cites)

### `anticipatory_bail` / `economic-offence-business-dispute` — 3.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)
- findings:
  - [warning] statute.bail_missing_bnss_reference: The body discusses bail but does not cite the governing BNSS section (typically s.482 anticipatory, s.483 regular, s.187 default). Add the correct BNSS reference before review.

### `anticipatory_bail` / `matrimonial-no-fir` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `civil_suit` / `recovery-of-money-commercial` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `civil_suit` / `specific-performance-real-estate` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `divorce_petition` / `hma-cruelty-desertion` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `property_dispute_notice` / `encroachment-flat` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['from', 'to', 'property', 'demand', 'deadline'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: (2012) 1 SCC 656

### `affidavit` / `standard-evidentiary` — 3.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deponent_block', 'sworn_statements', 'verification', 'notary_block'])
- citations: 0.0/5 (0 cites)

### `criminal_complaint` / `bns-cheating-forgery` — 3.33/5
- validator: 3.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [blocker] statute.bns_bnss_confusion: Section 223 is a procedural provision of BNSS (successor to CrPC). The draft attributes it to the substantive Bharatiya Nyaya Sanhita — this is incorrect and must be corrected before review.

### `appeal_memorandum` / `civil-appeal-cpc-order-xli` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `writ_petition` / `mandamus-rti-inaction` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `quashing_petition` / `compromise-civil-flavour-318` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 5.0/5 (3 cites)

### `written_statement` / `specific-performance-defence` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `reply_counter_affidavit` / `writ-counter-affidavit-state` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'deponent_block', 'para_response', 'relief', 'verification'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `dv_quashing_petition` / `settlement-recorded-with-consent` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `arbitration_section_9` / `pre-arbitration-injunction` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'section', 'agreement', 'urgency', 'relief'])
- citations: 3.0/5 (2 cites)

### `caveat_petition` / `caveat-against-ex-parte-injunction` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['section', 'caveator', 'apprehended', 'notice_request', 'ninety_days'])
- citations: 3.0/5 (1 cites)
- findings:
  - [warning] citation.coverage_gap: The citations list contains 1 identifier(s) that never appear as inline anchors in the body: [citation needed]
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `vakalatnama` / `fresh-filing-delhi-hc` — 4.33/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['court_header', 'cause_title', 'authority', 'acceptance', 'signature'])
- citations: 5.0/5 (0 cites)
- findings:
  - [warning] citation.no_inline_anchors: The body reads like a substantive legal argument but contains zero inline citation anchors. Every legal proposition should be anchored to a retrieved authority — or flagged as `[citation needed]`.

### `amendment_of_pleadings` / `post-trial-due-diligence-amendment` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `compromise_petition` / `criminal-non-compoundable-gian-singh` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'statutory_basis', 'settlement_terms', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `probate_petition` / `uncontested-hindu-will-bombay-hc` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deceased', 'will', 'estate', 'prayer'])
- citations: 3.0/5 (1 cites)
