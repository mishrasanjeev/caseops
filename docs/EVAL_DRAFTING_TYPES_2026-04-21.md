# Sprint R8 — per-template drafting eval (live Haiku)

- model: `claude-haiku-4-5-20251001`
- total scenarios: 16
- **overall pass rate: 16/16 (100%)**
- estimated LLM cost: **$0.1060** USD

## Per-type pass rate

| Template type | Passed | Warnings | Skipped (pydantic) | Errored (LLM) |
| --- | --- | --- | --- | --- |
| `affidavit` | 1/1 (100%) | 0 | 0 | 0 |
| `anticipatory_bail` | 3/3 (100%) | 0 | 0 | 0 |
| `bail` | 3/3 (100%) | 0 | 0 | 0 |
| `cheque_bounce_notice` | 3/3 (100%) | 0 | 0 | 0 |
| `civil_suit` | 3/3 (100%) | 0 | 0 | 0 |
| `criminal_complaint` | 1/1 (100%) | 0 | 0 | 0 |
| `divorce_petition` | 1/1 (100%) | 0 | 0 | 0 |
| `property_dispute_notice` | 1/1 (100%) | 0 | 0 | 0 |

## Rule-miss histogram

_No validator findings fired — every draft passed cleanly._

## Per-scenario status

| Type | Key | Status | Error findings | Warnings |
| --- | --- | --- | --- | --- |
| `bail` | `bnss-303-simple-theft` | PASS | — | — |
| `bail` | `ndps-prolonged-custody` | PASS | — | — |
| `bail` | `498a-economic-offence` | PASS | — | — |
| `cheque_bounce_notice` | `standard-insufficient-funds` | PASS | — | — |
| `cheque_bounce_notice` | `payment-stopped-high-value` | PASS | — | — |
| `cheque_bounce_notice` | `account-closed-small` | PASS | — | — |
| `anticipatory_bail` | `economic-offence-business-dispute` | PASS | — | — |
| `anticipatory_bail` | `matrimonial-no-fir` | PASS | — | — |
| `anticipatory_bail` | `cheque-dishonour-summons` | PASS | — | — |
| `civil_suit` | `recovery-of-money-commercial` | PASS | — | — |
| `civil_suit` | `specific-performance-real-estate` | PASS | — | — |
| `civil_suit` | `permanent-injunction-easement` | PASS | — | — |
| `divorce_petition` | `hma-cruelty-desertion` | PASS | — | — |
| `property_dispute_notice` | `encroachment-flat` | PASS | — | — |
| `affidavit` | `standard-evidentiary` | PASS | — | — |
| `criminal_complaint` | `bns-cheating-forgery` | PASS | — | — |

Generated drafts and full findings are in `docs/eval_artifacts/drafting_types_2026_04_21.json`.
