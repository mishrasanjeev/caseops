# Drafting quality eval — overall 4.36/5

Target: **4.8/5**. Meets target: **NO**.

## Per-template ratings

| Template | Rating | Scenarios | Errored | Median latency (ms) |
|---|---|---|---|---|
| `anticipatory_bail` | **5.0/5** | 2 | 0 | 43983 |
| `quashing_petition` | **5.0/5** | 1 | 0 | 45759 |
| `vakalatnama` | **5.0/5** | 1 | 0 | 12594 |
| `bail` | **4.33/5** | 2 | 0 | 57536 |
| `civil_suit` | **4.33/5** | 2 | 0 | 49836 |
| `property_dispute_notice` | **4.33/5** | 1 | 0 | 22424 |
| `affidavit` | **4.33/5** | 1 | 0 | 9765 |
| `appeal_memorandum` | **4.33/5** | 1 | 0 | 30569 |
| `writ_petition` | **4.33/5** | 1 | 0 | 37307 |
| `written_statement` | **4.33/5** | 1 | 0 | 31629 |
| `reply_counter_affidavit` | **4.33/5** | 1 | 0 | 49566 |
| `dv_quashing_petition` | **4.33/5** | 1 | 0 | 54837 |
| `arbitration_section_9` | **4.33/5** | 1 | 0 | 41945 |
| `caveat_petition` | **4.33/5** | 1 | 0 | 10706 |
| `compromise_petition` | **4.33/5** | 1 | 0 | 30436 |
| `probate_petition` | **4.33/5** | 1 | 0 | 43074 |
| `cheque_bounce_notice` | **4.0/5** | 2 | 0 | 26162 |
| `divorce_petition` | **4.0/5** | 1 | 0 | 28555 |
| `criminal_complaint` | **4.0/5** | 1 | 0 | 29474 |
| `amendment_of_pleadings` | **4.0/5** | 1 | 0 | 29581 |

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

### `anticipatory_bail` / `economic-offence-business-dispute` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 5.0/5 (3 cites)

### `anticipatory_bail` / `matrimonial-no-fir` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 5.0/5 (3 cites)

### `civil_suit` / `recovery-of-money-commercial` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `civil_suit` / `specific-performance-real-estate` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `divorce_petition` / `hma-cruelty-desertion` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'grounds', 'verification'])
- citations: 3.0/5 (2 cites)

### `property_dispute_notice` / `encroachment-flat` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['from', 'to', 'property', 'demand', 'deadline'])
- citations: 3.0/5 (1 cites)

### `affidavit` / `standard-evidentiary` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deponent_block', 'sworn_statements', 'verification', 'notary_block'])
- citations: 3.0/5 (1 cites)

### `criminal_complaint` / `bns-cheating-forgery` — 4.0/5
- validator: 5.0/5
- structure: 4.0/5 (found: ['cause_title', 'facts', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

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

### `written_statement` / `specific-performance-defence` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
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

### `caveat_petition` / `caveat-against-ex-parte-injunction` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['section', 'caveator', 'apprehended', 'notice_request', 'ninety_days'])
- citations: 3.0/5 (1 cites)

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
