# IPLF-047 Trademark Pleading Legal-Fixture Pack

## Purpose and boundary

This directory contains the versioned IPLF-047 review contract for Indian
trademark opposition pleadings. The committed `v1` pack is synthetic,
anonymized engineering material. It binds every `IP-DRAFT-01..10` requirement,
every UJ-24 normal and exception path, and each supported pleading template to
executable API tests without creating a second drafting implementation.

The pack is not legal advice, an approved pleading, Registry acceptance, or
authority to file. Its legal outcomes are intentionally null and authoritative
activation is denied until qualified people review a later exact version.

## Committed sources

Each official source entry records its HTTPS URL, retrieval time, and SHA-256.
The current engineering snapshot uses the Trade Marks Rules, 2017 and Form
TM-O published by IP India. A reviewer must open the recorded source, confirm
that it is the applicable official material, and verify the downloaded bytes
against the committed hash. A changed source must produce a new pack version;
the prior version and its evidence remain immutable.

## Review roles

Approval requires three distinct named identities:

1. A proposer prepares the candidate fixtures and automation mapping.
2. A reviewer checks source provenance, factual inputs, coverage, and expected
   software behavior independently.
3. A qualified legal approver supplies and approves the expected legal outcome
   for every fixture and confirms the exact source and content hashes.

The repository-owner acceptance waiver removes named program sign-off gates;
it does not supply professional legal approval. Engineering must never fill a
reviewer or legal-approver identity on another person's behalf.

## Approval procedure

1. Copy the latest pack to a new semantic version and preserve the old file.
2. Refresh every official source, record the retrieval time and SHA-256, and
   document any change in law, form, practice, or interpretation.
3. Review positive, negative, and boundary fixtures across all five template,
   side, stage, and jurisdiction combinations.
4. Add the legal SME's expected legal outcome and any mandatory correction to
   each fixture. Update its legal-content status in the new schema/version.
5. Run the mapped pytest nodes and compare actual software behavior with each
   approved expectation. A mismatch blocks approval; do not edit the expected
   result merely to make a test pass.
6. Recompute fixture and pack hashes with `--print-hashes`. Record the exact
   calculated hash in each approval and capture proposer, reviewer, legal
   approver, source-review time, and approval time.
7. Run the authoritative gate. It must pass before any approved pack is used
   for legal UAT or an authoritative activation decision.

```powershell
python scripts/run_ip_pleading_legal_fixtures.py --print-hashes
python scripts/run_ip_pleading_legal_fixtures.py
python scripts/run_ip_pleading_legal_fixtures.py --require-approved
```

The committed candidate intentionally passes structural validation and fails
`--require-approved`. CI executes structural validation so tampering, missing
coverage, broken test references, duplicate actors, or forged hashes fail the
build. Human legal approval remains a separate, explicit evidence event.

## Change and retirement rules

- Never modify an approved fixture version in place. Publish a new semantic
  version and identify the superseded pack in its evidence.
- Keep source documents external; commit URLs and hashes, not unlicensed copies.
- Use synthetic or properly anonymized data only. Do not place client facts,
  privileged material, credentials, or personal data in the pack.
- Keep expected software behavior distinct from expected legal outcome.
- Retire a pack explicitly when law, forms, workflow, or supported templates
  change. Retirement prevents new authoritative use but does not erase history.
- Production filing remains a human-controlled action. Fixture approval does
  not enable autonomous filing or Registry mutation.
