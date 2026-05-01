# Drafting quality eval — overall 4.41/5

Target: **4.8/5**. Meets target: **NO**.

## Per-template ratings

| Template | Rating | Scenarios | Errored | Median latency (ms) |
|---|---|---|---|---|
| `anticipatory_bail` | **5.0/5** | 2 | 0 | 47681 |
| `quashing_petition` | **5.0/5** | 1 | 0 | 26511 |
| `vakalatnama` | **5.0/5** | 1 | 0 | 20232 |
| `bail` | **4.33/5** | 2 | 0 | 52196 |
| `cheque_bounce_notice` | **4.33/5** | 2 | 0 | 29640 |
| `civil_suit` | **4.33/5** | 2 | 0 | 62797 |
| `divorce_petition` | **4.33/5** | 1 | 0 | 40487 |
| `property_dispute_notice` | **4.33/5** | 1 | 0 | 33155 |
| `affidavit` | **4.33/5** | 1 | 0 | 12678 |
| `criminal_complaint` | **4.33/5** | 1 | 0 | 39668 |
| `appeal_memorandum` | **4.33/5** | 1 | 0 | 49114 |
| `writ_petition` | **4.33/5** | 1 | 0 | 36711 |
| `reply_counter_affidavit` | **4.33/5** | 1 | 0 | 20449 |
| `dv_quashing_petition` | **4.33/5** | 1 | 0 | 44218 |
| `arbitration_section_9` | **4.33/5** | 1 | 0 | 52709 |
| `caveat_petition` | **4.33/5** | 1 | 0 | 14488 |
| `amendment_of_pleadings` | **4.33/5** | 1 | 0 | 46170 |
| `compromise_petition` | **4.33/5** | 1 | 0 | 36652 |
| `probate_petition` | **4.33/5** | 1 | 0 | 50083 |
| `written_statement` | **4.0/5** | 1 | 0 | 31817 |

## Per-scenario detail

### `bail` / `bnss-303-simple-theft` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `bail` / `ndps-prolonged-custody` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'facts', 'grounds', 'prayer', 'verification'])
- citations: 3.0/5 (2 cites)

### `cheque_bounce_notice` / `standard-insufficient-funds` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['from', 'to', 'instrument', 'demand', 'deadline'])
- citations: 3.0/5 (2 cites)

### `cheque_bounce_notice` / `payment-stopped-high-value` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['from', 'to', 'instrument', 'demand', 'deadline'])
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

### `divorce_petition` / `hma-cruelty-desertion` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'marriage', 'grounds', 'prayer', 'verification'])
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
- structure: 5.0/5 (found: ['cause_title', 'jurisdiction', 'facts', 'allegations', 'prayer'])
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

### `caveat_petition` / `caveat-against-ex-parte-injunction` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['section', 'caveator', 'apprehended', 'notice_request', 'ninety_days'])
- citations: 3.0/5 (1 cites)

### `vakalatnama` / `fresh-filing-delhi-hc` — 5.0/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['court_header', 'cause_title', 'authority', 'acceptance', 'signature'])
- citations: 5.0/5 (0 cites)

### `amendment_of_pleadings` / `post-trial-due-diligence-amendment` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'section', 'proposed_amendments', 'reason', 'prayer'])
- citations: 3.0/5 (2 cites)

### `compromise_petition` / `criminal-non-compoundable-gian-singh` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'statutory_basis', 'settlement_terms', 'prayer', 'verification'])
- citations: 3.0/5 (1 cites)

### `probate_petition` / `uncontested-hindu-will-bombay-hc` — 4.33/5
- validator: 5.0/5
- structure: 5.0/5 (found: ['cause_title', 'deceased', 'will', 'estate', 'prayer'])
- citations: 3.0/5 (1 cites)
