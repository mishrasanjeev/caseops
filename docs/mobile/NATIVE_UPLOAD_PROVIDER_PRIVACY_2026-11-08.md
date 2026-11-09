# Native upload processing privacy

The Android and iOS upload interface does not ask for permission to send
extracted document text to an outside AI provider. The current production
document worker is configured for Voyage AI embeddings. A separate local
reproduction used only invented text and an offline provider probe: an
ordinary native upload reached the embedding provider entry point. No
production customer content or external inference was used in that test.

New files uploaded through an authenticated native session are scanned and
indexed by text inside CaseOps. The original bytes and lexical chunks remain
available under existing Matter authorization. The source records its
local-only processing policy, which also applies to browser retry and reindex.
The document worker skips external embeddings and automatic AI extraction for
those files. An older record's existing policy is unchanged. Deploy the updated
API and document worker before releasing the native builds.

MOB-39-NATIVE-PRIVACY-01: an ordinary authorized native upload, browser retry,
and browser reindex must keep the same file and local text chunks without
entering the configured embedding provider. An independent ordinary web
upload must still enter the offline test provider. Verify stored job policy.

MOB-39-NATIVE-PRIVACY-02: rehearse the real migration on SQLite and PostgreSQL.
Verify that records written before migration and by an old writer afterward
retain their default; explicitly protected records remain protected after the
restore-forward downgrade refusal. Verify schema and row equality.

MOB-39-NATIVE-PRIVACY-03: verify the same flow on the actual store candidate,
including the native permission disclosure and provider isolation. Any later
feature that sends native upload text outside CaseOps needs a separate
affirmative consent flow and verification.
