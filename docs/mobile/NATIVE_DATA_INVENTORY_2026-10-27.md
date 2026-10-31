# Native data and SDK preparation inventory — 2026-10-27

Source scope: canonical `48f201ef056666cd0540bf442f63fb382e4bce40`,
mobile fingerprint `12b4714603de924da17035fb9036864bc6c31f9f6912b4b38bc81010ceb693f9`,
118 inputs, plus this isolated preparation draft. This is a source inventory,
not a final store privacy declaration, production traffic audit, legal policy,
or claim that the native application implements every web workflow.

The later development branch based on `8928c0db` adds the fixed publisher-enquiry
draft described below. Its unbuilt changes have no native acceptance claim yet;
the dated SDK/binary observations retain their own source scope.

## Actual narrow application data paths

| Data/path | Source evidence | Scope and remaining fact |
|---|---|---|
| User name/email/ID, company name/slug/ID, membership ID/role, capability names | `src/auth/types.ts:1–15`; AccountScreen identity/workspace display | Normal authorized account/workspace data, not anonymous data. Production processing/recipient/retention facts remain operational review inputs. |
| Access grant, refresh credential and session ID | `src/auth/session.ts`; `src/auth/secure-store.ts:5–18,43–47` | Access grant is session-memory state. Refresh/session ID are written via SecureStore with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`. A cache installation marker invalidates retained credentials when missing. OS-backed storage does not establish every backup/uninstall/forensic lifecycle. |
| Matter title/code/status/lifecycle, client/court names, legal case identifiers, descriptions/hearings; work/calendar; notes/drafts/activity | `src/domain/contracts.ts:90–150,238–340`; `repository.ts` | Read projections and the exposed bounded note mutation, not complete web editing/export parity. Note mutation carries the observed parent lifecycle version. Saved server notes survive local viewer cleanup. |
| Original filename, MIME/type, bytes, size/SHA, processing/extraction status, uploader and retained document metadata | `src/files/contracts.ts:11–48`; Files API/staging | Actual document content can be personal/sensitive. The device source alone cannot establish server scanning/extraction/storage/AI subprocessors, regions, purposes, lawful retention or training policy. |
| Explicit user-selected system-picker copy | `src/files/native.ts:113–157`; `private-imports.ts` | iOS uses the SDK cache-copy path, which copies before JS size checking, then validates an owned direct cache child and cleans owned cache/Inbox/staging. Android keeps its provider URI. Cleanup never authorizes deleting external/provider originals. Do not say there are no private copies. |
| Authorized reader bytes, embedded document text, page/zoom state | `src/viewer/controller.ts`, `PrivateDocumentViewer.tsx`, static runtime | Memory-scoped viewer with source/revision/lease fences, background/close purge and isolated WebView network/cache restrictions. Actual final-binary cleanup and physical-device behavior remain separate proof. A purge does not erase the original server attachment. |
| Browser sign-in/MFA and callback | `App.tsx`, `auth/handoff.ts`, native HTTPS policy | Browser/service handles sign-in/MFA; the native app admits exact one-use PKCE handoff/exchange. Browser cookies/provider-managed storage have a separate lifecycle from app-owned cache. Production association/signing/actual-device evidence remains pending. |
| Explicit publisher-enquiry email draft | `src/components/AccountHelp.tsx`; `src/domain/publisher-contact.ts` | The development UI opens the owner's published business email in the user's mail app with a fixed subject/body. No account, workspace, document or session values are added. It does not send email or record/fulfil a deletion request. The user controls any later message and information added in their separate mail app. |

## Pinned SDK purposes and declarations

The top-level installed inputs include Expo58/RN0.88, SecureStore 58.0.2,
FileSystem58.0.12, DocumentPicker58.0.4, ScreenCapture58.0.6,
WebBrowser58.0.7, Crypto58.0.7, Linking58.0.14, WebView14.0.1,
and PDF.js6.4.299 public renderer assets. The application calls screen-capture
prevention (`App.tsx:42`), explicit document selection and app-owned file I/O,
OS credential storage, cryptographic randomness/digests, browser authentication,
and the private WebView. App updates are disabled in app configuration.

The installed supplier privacy manifests inspected for this source declare:

| Supplier file | Required-reason API declarations |
|---|---|
| Expo FileSystem `ios/PrivacyInfo.xcprivacy` | FileTimestamp `0A2A.1`, `3B52.1`; DiskSpace `E174.1`, `85F4.1` |
| RN `React/Resources/PrivacyInfo.xcprivacy` | FileTimestamp `C617.1`; UserDefaults `CA92.1` |
| RN `ReactCommon/cxxreact/PrivacyInfo.xcprivacy` | FileTimestamp `C617.1` |
| RN `ReactCommon/react/timing/PrivacyInfo.xcprivacy` | SystemBootTime `35F9.1` |

Those supplier files list no collected-data types and tracking false. That is
**their declaration**, not proof the CaseOps service collects no data. An actual
archive must inventory the entire shipped framework/resource closure, aggregate
the relevant manifests, reconcile each reason with real use and inspect the
effective release SDK behavior. This bounded list is not a complete App Store
privacy report or a signed SDK-attestation inventory. No analytics package was
identified in the direct mobile dependency list; absence from that list does
not prove absence of backend, browser, OS or transitive SDK telemetry.

PDF.js public scripts, fonts/CMaps/WASM and bundled notices are pinned by the
existing194-input supplier manifest and canonical asset generator. This does
not certify the licensing/privacy inventory of the whole eventual IPA/AAB.

## Dated corrections to earlier review material

Retain the earlier `APP_PUBLISHING_REVIEW.md` and its dated source hashes. Its
camera-purpose-string row and quoted web-account-deletion guidance describe
the earlier inspected source, not current48. Current app config has no explicit
camera purpose string; the four unused overlay/media/storage Android
permissions are blocked. Actual replacement artifact projection still matters.

Canonical `8928c0db` directs account/organization data requests to the
organization administrator. The later development help panel adds actual
in-app privacy information and a publisher-enquiry mail draft, including a
request for deletion instructions. There is no verified self-service account
deletion workflow or persisted request/status implemented by that contact flow.
Device-session revocation is not account deletion. Whether the submitted native
app's actual account creation/provisioning model invokes a store deletion rule
needs its own review; do not invent compliance or expand this into a speculative
deletion feature.

The owner has since confirmed the corporate contact `sanjeev@orchestrum.in` and
the separate Site remains owner-private. An owner-confirmed contact is not
automatically an operational app-support service, privacy request workflow or
public final policy. The Site's website-only Privacy/Terms do not describe all
CaseOps app/backend processing. The development mail link is a business-enquiry
destination, not a promise of an operational app-support or privacy-rights
service. Final policy links, request handling and store applicability still
need their own corresponding implementation and review.

Prepared inputs already exist in `STORE_RELEASE_2026-10-26.md`,
`NATIVE_LINK_CONFIGURATION.md`, and the private Site's
`APP_PUBLISHING_REVIEW.md`. Still needed: real purposes/recipients/subprocessors,
hosting/processing regions, retention by category and backup/security records,
rights/request handling and exact account/organization/Matter ownership,
final-binary SDK/permissions evidence, accurate store labels/Data safety and
actual supported-device behavior. No SLA, deletion promise, AI-sharing/training
claim, encryption/compliance certification or organization identifier is
invented by this inventory.

## Camera development delta after Today `f5d95426`

The isolated camera implementation pins `expo-image-picker`58.0.10 and its
`expo-image-loader`58.0.3 dependency (both Expo MIT). A user must press **Take
photo** before the app requests camera permission. The SDK opens native camera
UI for one image; the app does not call library selection, media permissions,
microphone, album save, pending-result recovery or background capture. The app
config removes photo-library and microphone purpose strings and blocks Android
record-audio alongside the existing inherited media/storage permissions. These
are source/config projection facts; the effective signed binary still needs
independent permission and physical-device verification.

The camera creates app-private `cache/ImagePicker/<UUID>.jpg|jpeg|png` copies.
The native SDK copies/encodes before JS can enforce the50MiB cap or inspect size;
this is not a bounded native memory/copy claim. The app admits only that exact
direct-child naming scope, checks actual file size and any returned size/MIME,
retains one result, and purges other owned files. Cancel/error/oversize, explicit
clear, completed upload, logout and startup attempt owned-copy removal and keep
cleanup failure actionable. A second rejected command performs no purge of the
active capture. Provider originals and another camera app's own storage are
outside this cleanup authority. OS caches/unknown late native writes and
process-death behavior require physical proof; startup cleanup is not proof of
forensic erasure.

`exif:false` suppresses the returned JS EXIF object. It **does not remove encoded
metadata**: the pinned Android raw exporter copies the original and its
compression exporter explicitly copies EXIF. The capture and upload UI warns
that a photo can contain image metadata, including capture location. CaseOps
does not request location access, but that does not prove a third-party camera
omitted location or other personal metadata. Uploaded photo bytes use the same
explicit Matter/lifecycle, staging/hash, server upload/security and readback
flow as other attachments; capture never automatically uploads. Server content
processing, storage, recipients and retention apply to the complete image and
its encoded metadata. No clean-scan claim or store declaration follows from
these source controls.

Exact supplier licence text is retained in `apps/mobile/CAMERA_NOTICES.txt` and
the in-app Account/About camera-software panel. Native camera, permission denial,
encoded metadata, background/kill cleanup and final artifact SDK/privacy
manifest acceptance remain **unrun** for this development delta.

## Optional biometric development delta

The opt-in screen lock uses existing SecureStore 58.0.2, without another biometric
SDK. A random app installation UUID remains in the app-owned marker; bounded
device-only SecureStore policy contains installation/nonce and server user,
company, membership and session IDs. The protected marker has a separate fresh
installation service. No raw Face ID image/fingerprint/template, location,
contacts, analytics or biometric result is uploaded by this feature. OS
handling is a separate physical/vendor fact, not established by mocked tests.

The gate covers private UI and requires positive protected access plus current
server authority before reopening it. It does not replace MFA or encrypt/erase
every file/memory region. Pending camera/picker ownership follows the existing
opaque-intent contract. Sign-out removes local policy under normal revocation
semantics; removal failure remains actionable. OS keychain remnants,
backup/uninstall and enrollment invalidation are not certified. See
`BIOMETRIC_SCREEN_LOCK_2026-10-27.md`. Final store labels still require actual
artifact/SDK/operational review; source presence is not native acceptance.

## Cold Files provider harness correction, 2026-10-28

The independent Android and iOS Files inventories still contain exactly17
cases/51 phases. FILES-03 now selects the same exact TXT asset, clears it,
checks owned cleanup, selects it again and clears it again. Each selection
uses the real platform picker recipe and each click uses the existing single
protocol dispatch. A lost acknowledgement stops the sequence; no second click
or cleanup success is invented. This adds one per-case cleanup checkpoint
(14 rather than the earlier13), without adding a case or upload. Native
execution of this strengthened workflow remains unrun.

Provider staging now emits schema2 receipts from the verified host buffers.
iOS writes those buffers through exclusive0600 descriptors; Android transfers
the admitted buffers through its existing exclusive device write. Neither
stager rereads the provider destination. Each asset records `transferSha256`,
its write method and original provider metadata; it does not claim an observed
provider-content hash. Fresh picker observations must also use schema2, bind
the exact `stagingEvidence` and declare `providerOriginalsRead:false`. The old
`observedProviderHash` field is rejected. These public fields need actual
source-bound staging/OS-observation evidence, not restamped historical JSON.

Every preflight and per-case Files privacy scan defaults to metadata-only
provider verification. It still scans app-owned private copies under the
unchanged entry/file/depth/byte limits. Its schema2 result reports
`providerMetadataPreserved:true`, `providerOriginalsRead:false`,
`providerOriginalsPreserved:null` and
`providerByteVerification:'deferred-until-postflight'`. Null means the original
bytes have not yet been verified. The iOS private scan now takes two bounded,
unique root-present metadata inventories and reconciles every final path;
an incomplete/late inventory cannot become a clean zero-copy result.

Only the runners' postflight, after the full case loop and session teardown,
enables provider byte reads. That proof requires the staged metadata and exact
original sizes/SHA values, same-descriptor bounded reads, and final metadata
reconciliation after the private scan. A missing, replaced or changed original,
partial scan, timeout or unreached postflight refuses a full pass. The existing
30-minute serial and interactive budgets remain unchanged. Earlier8928/native
failures, blocked/unreached phases and schema1 receipts retain their own scope;
they do not certify the new cold-provider workflow, a new artifact, tablet or
physical-device acceptance.

## SDK patch replacement, 2026-10-28

The current source candidate pins FileSystem 58.0.13 and Linking 58.0.15 with
Expo 58.0.21, dev client 58.0.17 and UI 58.0.25. The earlier dated supplier
inventory above retains its original source scope. Exact official archive
references/MIT text are retained in `apps/mobile/vendor/sdk58-patch-20261028`.
No permission, minimum deployment target or app data-handling contract changes
are authorized by this package update. Final-binary supplier privacy manifests,
permissions and device behavior require fresh independently bound acceptance.
