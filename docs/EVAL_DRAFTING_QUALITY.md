# Drafting quality eval — overall 4.33/5

Target: **4.8/5**. Meets target: **NO**.

## Per-template ratings

| Template | Rating | Scenarios | Errored | Median latency (ms) |
|---|---|---|---|---|
| `quashing_petition` | **5.0/5** | 1 | 0 | 34027 |
| `caveat_petition` | **5.0/5** | 1 | 0 | 22370 |
| `vakalatnama` | **5.0/5** | 1 | 0 | 16256 |
| `bail` | **4.33/5** | 2 | 0 | 69719 |
| `civil_suit` | **4.33/5** | 2 | 0 | 44828 |
| `divorce_petition` | **4.33/5** | 1 | 0 | 40668 |
| `property_dispute_notice` | **4.33/5** | 1 | 0 | 32102 |
| `affidavit` | **4.33/5** | 1 | 0 | 10477 |
| `criminal_complaint` | **4.33/5** | 1 | 0 | 43644 |
| `appeal_memorandum` | **4.33/5** | 1 | 0 | 52458 |
| `reply_counter_affidavit` | **4.33/5** | 1 | 0 | 26989 |
| `dv_quashing_petition` | **4.33/5** | 1 | 0 | 45448 |
| `arbitration_section_9` | **4.33/5** | 1 | 0 | 51282 |
| `compromise_petition` | **4.33/5** | 1 | 0 | 37690 |
| `probate_petition` | **4.33/5** | 1 | 0 | 66516 |
| `cheque_bounce_notice` | **4.0/5** | 2 | 0 | 24871 |
| `writ_petition` | **4.0/5** | 1 | 0 | 67802 |
| `written_statement` | **4.0/5** | 1 | 0 | 29773 |
| `amendment_of_pleadings` | **4.0/5** | 1 | 0 | 52617 |
| `anticipatory_bail` | **3.67/5** | 2 | 0 | 45693 |

## Per-scenario detail

### `bail` / `bnss-303-simple-theft` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `bail` / `ndps-prolonged-custody` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `cheque_bounce_notice` / `standard-insufficient-funds` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['from', 'to', 'instrument', 'demand'])
- citations: 3.0/5 (2 cites)

### `cheque_bounce_notice` / `payment-stopped-high-value` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['from', 'to', 'instrument', 'demand'])
- citations: 3.0/5 (2 cites)

### `anticipatory_bail` / `economic-offence-business-dispute` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)
- findings:
  - [warning] statute.bail_missing_bnss_reference: The body discusses bail but does not cite the governing BNSS section (typically s.482 anticipatory, s.483 regular, s.187 default). Add the correct BNSS reference before review.

### `anticipatory_bail` / `matrimonial-no-fir` — 3.67/5
- validator: 3.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)
- findings:
  - [warning] statute.bail_missing_bnss_reference: The body discusses bail but does not cite the governing BNSS section (typically s.482 anticipatory, s.483 regular, s.187 default). Add the correct BNSS reference before review.

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

### `property_dispute_notice` / `encroachment-flat` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['from', 'to', 'property', 'demand', 'deadline'])
- citations: 3.0/5 (1 cites)

### `affidavit` / `standard-evidentiary` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deponent_block', 'sworn_statements', 'verification', 'notary_block'])
- citations: 3.0/5 (1 cites)

### `criminal_complaint` / `bns-cheating-forgery` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `appeal_memorandum` / `civil-appeal-cpc-order-xli` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `writ_petition` / `mandamus-rti-inaction` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `quashing_petition` / `compromise-civil-flavour-318` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 5.0/5 (3 cites)

### `written_statement` / `specific-performance-defence` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `reply_counter_affidavit` / `writ-counter-affidavit-state` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deponent_block', 'para_response', 'relief', 'verification'])
- citations: 3.0/5 (1 cites)

### `dv_quashing_petition` / `settlement-recorded-with-consent` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `arbitration_section_9` / `pre-arbitration-injunction` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'section', 'agreement', 'urgency', 'relief'])
- citations: 3.0/5 (2 cites)

### `caveat_petition` / `caveat-against-ex-parte-injunction` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['section', 'caveator', 'apprehended', 'notice_request', 'ninety_days'])
- citations: 5.0/5 (0 cites)

### `vakalatnama` / `fresh-filing-delhi-hc` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['court_header', 'cause_title', 'authority', 'acceptance', 'signature'])
- citations: 5.0/5 (0 cites)

### `amendment_of_pleadings` / `post-trial-due-diligence-amendment` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `compromise_petition` / `criminal-non-compoundable-gian-singh` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'statutory_basis', 'settlement_terms', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `probate_petition` / `uncontested-hindu-will-bombay-hc` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deceased', 'will', 'estate', 'prayer'])
- citations: 3.0/5 (1 cites)
