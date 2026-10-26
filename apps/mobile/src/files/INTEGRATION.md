# Native Matter Files Integration

Component scope: J03/M02, J04/M03 and J20/M22, US-005/007 and US-MOB-03/04/06/08;
MOB-10/21..26, FT-009..015, NFT-009/013/014 and SEC-003..006. This is a
list/upload integration, not native acceptance or closure of these scenarios.
No shared application, repository, auth, transport, package or build file is edited.
Parent owns the PRD/ledger, root integration and standard test inventory changes.

## Parent Contract

`application/screens/FilesScreen.tsx` exports `FilesScreen` and `FilesScreenProps`:

```tsx
<FilesScreen
  request={request}
  companyId={identity.company.id}
  userId={identity.user.id}
  sessionKey={signInGenerationKey}
  matterId={currentMatterId}
  capabilities={identity.capabilities}
  selectedFile={selection}
  onChooseFile={chooseFileAtRoot}
  onClearSelectedFile={clearSelectionAtRoot}
/>
```

This is unframed content for Matter's Files section inside its existing scroll
surface, not another navigation shell. Unmount it when leaving that section.
Use a stable authenticated `request` function and a non-secret `sessionKey`
unique to the current sign-in generation, including re-login as the same user.
Never use an access/refresh token as a React key.

`files/contracts.ts` exports:

```ts
type MatterFileAsset = Readonly<{
  uri: string;
  name: string;
  mimeType?: string;
  size?: number;
}>;
type MatterFileSelection = Readonly<{
  companyId: string;
  userId: string;
  matterId: string;
  sessionKey: string;
  expectedLifecycleVersion: number;
  asset: MatterFileAsset;
}>;
```

`files/native.ts` exports `pickFile(): Promise<MatterFileAsset | null>`,
`cleanupPickedFile(asset): void`, and `purgeMatterFileTemps(): void`.
`pickFile` requests a single system selection and no base64. On iOS it uses
`copyToCacheDirectory: true`, because raw provider URLs are not guaranteed to
remain readable after the native picker callback. The app owns only direct
files in its exact `Library/Caches/DocumentPicker` directory, validates the
completed cache copy's metadata against the existing global upload cap, and
purges the redundant OS Inbox import. Android keeps
`copyToCacheDirectory: false` and its provider URI.

The SDK cache copy and OS import happen before JavaScript size enforcement;
they are not claimed to obey the bounded staging byte budget. Oversized,
unavailable or incomplete cache copies are immediately cleaned. Before any
upload, staging independently revalidates the authoritative workspace policy,
byte limit, lifecycle, exact size and SHA-256 under its existing deadline.
Selected SDK copies and orphan imports are removed on clear, cancellation,
error, background, discarded/late picker results, logout and cold startup.
Provider originals remain untouched. No camera, media-library or contact
permission is requested.

`FilesScreenProps.onChooseFile(expectedLifecycleVersion: number): void` receives
the CURRENT loaded workspace's `matter.lifecycle_version` at the explicit Choose
command, before the picker backgrounds the app. Root must preserve only opaque
`{ companyId, userId, membershipId, sessionKey, matterId, expectedLifecycleVersion }`
for that pending picker intent when the picker backgrounds the app. Keep the
deliberate private-screen purge.
Run the picker at root, perform normal foreground authentication revalidation,
compare all intent identities, remount the exact Files route, then provide the
asset with the SAME original `sessionKey` and `expectedLifecycleVersion` in the
selection. Never adopt the remounted workspace's newer version. Root checks
membership identity as well; FilesScope itself carries company/user/session/Matter.
Do not retain a Matter DTO or start upload from the picker promise.
Drop/clear selection on account mismatch, sign-out, cancellation and navigation
away. Do not restore/reupload it after process death. Handle picker rejection
at root with safe error copy. Never log selected URIs or filenames.

Call `purgeMatterFileTemps()` on cold startup before private screens and on
sign-out after unmounting private screens. Handle cleanup errors visibly; do not
claim successful purge. The pinned iOS picker uses `asCopy: true`: disabling
Expo's extra cache copy still imports a file into the app's temporary
`tmp/{bundleIdentifier}-Inbox`. A native select/clear probe reproduced retention
there. Cleanup now covers that exact app-private Inbox and
`Paths.cache/caseops-matter-files-v1`; it never purges all cache/tmp or an external
provider. Selected-file cleanup admits only a direct local file in this app's
Inbox or an exact owned staging filename. Cold-start/sign-out purge removes
orphan imports, including process-death leftovers. A new picker first requires
successful cleanup. Late-result cleanup failures remain visible after logout;
unrelated late provider rejections stay silent. Provider originals are preserved.
This source fix requires a rebuilt binary and native post-action evidence.

The controller rejects mismatched session/parent/account identities and a picker
version differing from the current loaded workspace before preparation. It then
rechecks fresh access/lifecycle before preparation and again before the sole POST;
the selection's original version, not a refreshed replacement, is sent.
No selected asset is automatically submitted. It stages/hashes an app-private temporary copy only
during that command with byte-capped 1 MiB async reads/writes, cleans
completion/cancel/error paths and discards late
preparation/access responses after unmount. It aborts in-flight upload on
unmount; abort is not a server rollback. It keeps no disk queue or private file
metadata ledger. A 120-second preparation admission deadline rejects expired
results; an OS copy already running cannot be forcibly interrupted by JS and
is cleaned when it returns or by next-startup purge.

## Exact Server Contracts

- `GET /api/matters/{matter_id}/workspace`: `matter`, `attachments` (not
  `documents`), `storage_governance`. Validates exact parent and company,
  required source hash/size/processing fields, duplicate IDs and malformed DTOs.
  A bounded 1,000-file client inventory fails explicitly if exceeded; no hidden
  truncation or guessed continuation. Rows are progressively displayed 25 at a time.
- `POST /api/matters/{matter_id}/attachments`: multipart `file` plus
  `expected_lifecycle_version` as a decimal nonnegative integer, returning
  `MatterAttachmentRecord`; capability `documents:upload`. No guessed JSON body,
  scan endpoint, staging ID, idempotency key, source version or legal metadata.
  Server sanitizes the filename. Returned parent/hash/size and a new attachment
  identity are checked, then the same source is confirmed in workspace reload.
  `api.upload(file, expectedLifecycleVersion, signal)` and
  `nativeMultipart(part, expectedLifecycleVersion)` require the observed version.
  Server form field is optional for legacy web clients, required for a validated
  native credential (`SessionContext.native_session_id`, never a header), and
  compared under the authoritative Matter lock before I/O and again after
  scan/storage. Missing native version or malformed/negative input returns 422;
  stale versions, including close/explicit-reopen, return 409. No response shape,
  endpoint namespace, migration or web metadata form field changes.
- `JsonTransport` already forwards React Native FormData unchanged and sets
  Content-Type only for string bodies. No shared network change is required
  for upload. Boundary/auth/no-paid/no-store/deadline/no-retry policy is retained.
- Client file types mirror `services/file_security.py`: PDF, DOCX, DOC, TXT,
  PNG, JPG/JPEG. Cap is the minimum of server-configured maximum, remaining
  quota and file-security's 50 MiB cap. Actual copied size and SHA-256 are read
  using installed Expo FileSystem 58.0.11. Server still validates bytes/types
  and runs its configured ClamAV policy before admission.
- `processing_status` is exactly pending/indexed/needs_ocr/failed, not malware
  state. No response exposes a scan result, and local server policy can skip
  scanning. UI never presents clean or Available based on processing/HTTP 200.
- HTTP 400/401/403/404/409/413/415/422/429 with known rejected outcome are
  refusals. Lost/malformed acknowledgement, unexpected response and all 5xx
  (including scanner outage) are conservatively Unknown. No automatic retry,
  resubmit, paid call, generation, reindex or recovery mutation exists. Reload
  is read-only. Acknowledged-but-unconfirmed is not persistence success.

Server references: `api/routes/matters.py`, `schemas/matters.py`,
`services/matters.py`, `services/file_security.py`, `services/virus_scan.py`.

## Open Safety And Viewer Gates

1. The lifecycle multipart fence and picker-origin session/version contract are
   implemented at source level. Parent must wire the root callback/selection
   unchanged and rebuild the API image after source freeze before native
   acceptance. Component/HTTP evidence does not certify the actual two-platform
   picker journey or close all of MOB-10/23.
2. No scan receipt is returned/persisted in this DTO. Parent needs server-owned
   clean/skipped/error evidence tied to the attachment hash before mobile can
   honestly show a real clean result. Current persisted acknowledgement is not
   that proof, and the scanner must not be weakened to satisfy mobile.
3. There is NO implemented private document viewer. Installed `File.preview`
   resolves at presentation/handoff, uses Android external ACTION_VIEW and iOS
   QuickLook; it is not a proven in-app, share-disabled, revocable two-platform
   viewer. `@expo/ui` has no installed PDF component and no PDF/WebView package
   is installed. No fake PDF images, web handoff or external file/share control
   is substituted. Source details are metadata only, not a viewer placeholder.
4. Existing authorized original bytes are
   `GET /api/matters/{matter_id}/attachments/{attachment_id}/download?inline=true`
   (PDF/images) or the same route without inline for originals. DOCX `/preview`
   provides bounded extracted paragraphs/tables, not an original-layout viewer.
   These reuse Matter visibility/access checks and retained reads; terminal
   records remain readable without authorizing upload. FileResponse now sets
   `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store, max-age=0`
   and `Pragma: no-cache` for originals, inline and range responses. An
   authenticated `Range: bytes=0-0` lease uses the SAME canonical download path
   and returns HTTP 206 with exactly one byte. No authoritative content-hash
   header is supplied; validate full bytes against the existing attachment DTO's
   `sha256_hex` and size, not the FileResponse ETag. Publisher redirects are unchanged.
5. Canonical public source opening is the authenticated, audited
   `/api/source-actions/targets/{target_type}/{target_id}/open?origin=...` redirect.
   MatterAttachmentRecord supplies no such canonical source target. Never
   fabricate one from attachment IDs, notice_source or filenames, bypass the
   audit, open private URLs externally or forward native Bearer tokens to a
   publisher. No source-opening behavior is claimed here.
6. Viewer transport belongs to the session owner: an explicit bounded bytes
   method (not generic request<T>/response.json), exact same-origin GET paths,
   size/MIME checks, full body inside the deadline, abort/generation fence,
   credentials omitted, no-store/no redirects/no-paid marker, no retry. Consume
   bytes only into a vetted private renderer/temp owner; purge on background,
   logout, access revoke and close. Never return an authenticated URL for an OS
   viewer. Parent must also prove headers, backup/cache/screen protections.

Dependency research, not permission to install: upstream `react-native-pdf`
7.0.5 is a candidate with native Fabric/PDFKit rendering, page navigation and
zoom; it requires `react-native-blob-util` and a development build. The Expo
config-plugin's published compatibility table only establishes SDK 56 with
PDF 7.0.4/plugin 14.0.0, NOT this app's Expo 58/RN 0.88. No exact compatible
dependency set was proven, so no package/build edit or compatibility claim is
made. Parent must validate/pin the complete native set before package changes.
Primary sources checked:
[upstream PDF repository](https://github.com/wonday/react-native-pdf),
[Expo-maintained config plugin](https://github.com/expo/config-plugins/tree/main/packages/react-native-pdf),
[SDK 58 FileSystem](https://docs.expo.dev/versions/v58.0.0/sdk/filesystem/),
[DocumentPicker](https://docs.expo.dev/versions/latest/sdk/document-picker/).

## Selectors And Tests

State selectors: `matter-files`, `files-inactive`, `files-loading`,
`files-restricted`, `files-error`, `files-empty`, `files-list`, `files-count`,
`files-matter-code`, `files-matter-title`, `files-matter-status`,
`files-scan-evidence`, `files-upload-restricted`, `files-cleanup-error`.
Actions: `files-choose`, `files-selection`, `files-upload`,
`files-selection-clear`, `files-selection-error`, `files-upload-cancel`,
`files-reload`, `files-more`. Outcome selector: `files-upload-{state}` where
state is preparing/uploading/persisted/acknowledged/rejected/unknown.
Per row: `files-row-{id}`, `files-name-{id}`, `files-processing-{id}`,
`files-source-{id}`, `files-source-details-{id}`, `files-hash-{id}`,
`files-viewer-unavailable-{id}`. Source detail control does not open bytes.

Run from `apps/mobile`:

```powershell
node --experimental-transform-types --test src/files/*.test.ts
npm run typecheck
```

Parent must add `src/files/*.test.ts` to the standard package test selection;
the existing script does not discover this directory. Five focused files cover
DTO/API/transport, controller, native-staging adapter logic and source/selector
contracts. They are deterministic components, not an actual native picker,
real ClamAV, real PostgreSQL race, persisted HTTP or Appium/device receipt.
MOB-21 native reading, MOB-22 real scanner/bytes, MOB-23 EICAR/outage/race,
MOB-24 OS permission/provider behavior and MOB-25/26 process-death/privacy
acceptance remain unverified. No server, emulator, Metro, production or paid
provider is started or called by these tests.

Initial focused run: 28 passed / 1 failed (wrong relative server fixture path,
ENOENT before the source assertion). This is retained as failed setup, not
product evidence.

Earlier component verification on 25 October 2026 (before this lifecycle fix):

- All five focused files ran: api 4, contracts 5, controller 15,
  integration-contract 3, staging 10 = **37 passed**, zero failed/skipped/
  cancelled/todo. These independently match the five discovered `.test.ts` paths.
- Explicit combined network/auth/domain/files selection: **158 passed**, zero
  failed/skipped/cancelled/todo. The shared workspace was being integrated by
  other agents; this is a point-in-time unit result, not frozen release proof.
- `tsc --noEmit --noUnusedLocals --noUnusedParameters` passed.
- Scope-limited Prettier formatting/check and `git diff --check` passed.
- No actual Android/iOS renderer, picker, scanner or server acceptance ran.
  No shared configuration, dependency, server/emulator/Metro lifecycle,
  production, paid-provider, commit or push operation was performed here.

## Lifecycle Fence And Private Download Proof

The scoped backend/native change on 25 October 2026 is locally verified, not
native-device or production acceptance. Base HEAD at verification was
`d5a6641ea34526e844241a637aed96dec9d2724c`; changes remain uncommitted for the
parent's integration. Parent must rebuild the API image from the final committed
source and replay the actual native journey. No Metro, production, paid-provider,
commit/push or shared Docker app-database operation was performed.

Exact changed paths owned by this fix:

- `apps/api/src/caseops_api/api/routes/matters.py`
- `apps/api/src/caseops_api/services/matters.py`
- `apps/api/tests/test_native_matter_attachment_version_20261025_postgres.py`
- `apps/mobile/src/files/api.ts`, `controller.ts`, `contracts.ts`
- `apps/mobile/src/files/api.test.ts`, `controller.test.ts`, `contracts.test.ts`
- `apps/mobile/src/files/integration-contract.test.ts`, `test-fixtures.ts`, `INTEGRATION.md`
- `apps/mobile/src/application/screens/FilesScreen.tsx` (picker callback and stale-selection guard)

Proof artifacts are under repository `outputs/upload-fence-9e42/`:

- `green-b.jsonl` and `green-b.xml`: **60 passed**, zero failed/skipped.
  The new module contributes 28 and the entire existing
  `test_matter_upload_admission_postgres.py` contributes 32. All 60 unique
  collected identities have passing setup/call/teardown and a completion event.
  `collection.jsonl` independently captures the complete matching inventory.
- The 28 new PostgreSQL HTTP cases prove stale closed and close/reopened old
  versions reject; current initial/reopened versions succeed; native omission
  rejects without a client header; browser omission and metadata stay compatible
  even with a spoofed native header; malformed/negative input has zero upload
  scan/storage/dispatch/attachment/job/activity side effects; scan and storage
  callbacks can close/reopen on separate transactions while upload holds none;
  rejected I/O admissions remove bytes. Originals/inline/range retain exact
  private no-cache headers, full-byte DTO hashes, one-byte 206 ranges, authorized
  terminal reads and denial after membership revocation. OpenAPI keeps only
  `file` required and publishes the optional nonnegative integer field.
- The 32 existing PostgreSQL cases retain quota/actor/parent lock ordering,
  transaction-free transport, access/session revocation, quota races, infected
  scanner and scanner-error rejection under both autoflush modes.
- `native-c.xml`: **41 passed**, zero failed/skipped/cancelled/todo, across the
  exact five files: API 5, contracts 5, controller 18, integration-contract 3,
  staging 10. Includes stale picker return after remount, session mismatch,
  pre-preparation and final preflight lifecycle checks, original-version
  multipart, rejected 409/no replay, unchanged no-paid transport and honest
  missing scan evidence.
- `adjacent.jsonl` and `adjacent.xml`: **31 passed** across the full existing
  `test_virus_scan.py`, `test_file_security.py`, `test_openapi_quality.py` modules.
- Scoped strict TypeScript, unused diagnostics (including FilesScreen and
  focused tests), Ruff and scoped Prettier checks pass. A whole-mobile
  typecheck passed earlier, then reported concurrent parent/root/viewer
  integration errors outside these paths. It is not certified by the scoped
  check; parent owns the complete integrated rerun.
  Explicit-entry TypeScript initially rejected its missing `--ignoreConfig`,
  then missing explicit Node type selection. The passing scoped command uses
  `--ignoreConfig --types react,node`, strict/unused checks, bundler resolution,
  ES2022 and React JSX; it includes the changed source, focused tests and screen.

Retained failures, not erased by replacement runs:

- `red.jsonl`/`red.xml`: two PostgreSQL connection-timeout setup errors from
  Docker's unpublished port on the original isolated network. The first status
  was incomplete; the retained run ultimately has failure completion, not a
  product reproduction. Only the owned container was replaced with a
  loopback-published temporary PostgreSQL.
- `red-b.jsonl`/`red-b.xml`: both old-version close/reopen HTTP reproductions
  failed before the fix because native AND browser uploads returned 200 instead
  of 409. Each full failed result is retained.
- `green-a.jsonl`/`green-a.xml`: 19 passed, six malformed-input assertion errors.
  Every failed result was inspected: the tests read RFC 7807 `detail` as a list
  instead of the canonical `errors` array. The complete 60-case replacement
  adopts the real error contract and retains all no-side-effect assertions.
- Initial updated native run: 39 passed/one failed because quota-only rejection
  occurs after preparation, while lifecycle/access rejection now occurs before
  preparation. Exact read/preparation/cleanup counts were separated, not removed;
  `native-b.xml` (40 passed) and `native-c.xml` (41 passed) are later inventories.

PostgreSQL used only the uniquely labelled temporary
`caseops-upload-fence-pg-20261025-9e42` at loopback port 55489. New HTTP cases use
the canonical separately migrated, connection-disabled empty template and one
dedicated database per case, never a copy of the shared application database.
Scanner callbacks are deterministic test adapters, not actual ClamAV receipts.
The durable scan-receipt gap and Android/iOS device acceptance remain open.
After verification, PostgreSQL reported zero remaining `caseops_http%` databases.
The exact labelled container, its anonymous volume and the unused owned network
were removed; the exact container name was independently confirmed absent.
No owned test or server session remains running.

Validated backend SHA-256 fingerprints (rebuild must include these bytes):

- Route: `f4191661edc728aac3c82226a01a5ea635c9717d5a88c07cf126904da3297217`
- Service: `50ce2a5bb208575149fdc241d30a017b05e46f34c4f4ac70865142bfc007d034`
