# Private Native Document Viewer

Source-only implementation dated 25 October 2026. J04/M03 and J20/M22;
US-007/025/042, US-MOB-03/06/08, FT-013..015/039, MOB-21/26,
SEC-003/004/006 and MASVS storage/privacy. This is not Android or iOS native
acceptance, a full J04 annotation/search implementation, or release readiness.
Parent owns shared PRD/ledgers, package/lock, network/session, application
wiring, native builds and Appium inventory. Existing node-forge audit findings
remain open; a direct renderer-package advisory check does not waive them.

Initial raw `evidence-*` files and synthetic screenshots named below are preserved
outside Git at `$HOME/.cache/caseops-mobile/viewer-initial-20261025`.
New renderer tests write unique evidence under
`$HOME/.cache/caseops-mobile/viewer-renderer/`, never into the source snapshot.

## Exact Dependencies

- Mobile runtime: `react-native-webview` **14.0.1**, matching the inspected
  `expo` 58.0.19 `bundledNativeModules.json` and official SDK documentation.
- Mobile build-time devDependency: `pdfjs-dist` **6.4.299**.
- No `expo-asset`, blob-util, react-native-pdf, sharing or browser dependency.

Primary evidence:
[Expo WebView](https://docs.expo.dev/versions/v58.0.0/sdk/webview/),
[Mozilla stable release](https://github.com/mozilla/pdf.js/releases/tag/v6.4.299),
[2026 scripting advisory](https://github.com/advisories/GHSA-hq66-cqwq-w95j)
(patched in 6.2.108), and
[2024 eval advisory](https://github.com/advisories/GHSA-wgrm-67xf-hhpq).
`evidence-advisories.json` retains the dated official npm bulk query for the two
exact pins, which returned no direct advisories. This is not a full transitive,
native-system-WebView or future-vulnerability certification.

The preparer consumes only the exact installed package by default:

```powershell
node scripts/mobile/prepare-viewer-assets.mjs
node scripts/mobile/prepare-viewer-assets.mjs --check
```

It requires exact main/worker/license hashes and an aggregate hash over all 194
public inputs: two legacy ES modules, 168 CMaps, 14 standard fonts and licenses.
`generated/manifest.json` pins every byte count/SHA-256;
`generated/LICENSES.txt` retains the shipped notices. The generated TS embeds
public bytes directly, so no Metro asset rule, expo-asset cache, runtime CDN,
local HTTP server, private file or custom scheme is needed. Public inputs total
5,482,731 bytes before base64. Do not format the generated TS.

The initial preparation used explicit `--from-registry`, which retrieves only
the reviewed public npm archive, verifies its pinned SHA-512 and complete input
closure, and writes the same deterministic public outputs without installation.
Normal prepare/check is offline. This does not update web's older PDF.js pin.
Do not remove this devDependency before the release's asset check.

## Parent Interface

```tsx
import { PrivateDocumentViewer } from "./viewer/PrivateDocumentViewer";
import { attachmentViewerSource } from "./viewer/contracts";
import type { ViewerPorts } from "./viewer/contracts";

// Use stable function/object identities and a non-secret per-login sessionKey.
const source = attachmentViewerSource(
  { companyId, userId, sessionKey, matterId },
  attachment,
);
const ports: ViewerPorts = {
  requestBytes: session.requestBytes,
  revalidate: revalidateCurrentAttachment,
  sha256: digestBytes,
  subscribeInvalidation: subscribePrivateSourceInvalidation,
};

<PrivateDocumentViewer
  source={source}
  ports={ports}
  onClose={returnToFiles}
  initialPosition={memoryOnlyPosition}
  onPositionChange={rememberPositionInMemory}
/>;
```

Bind `session.requestBytes` if it is not an arrow method. Never capture a token
in the ports, pass a URL to the renderer, persist the position/source in disk
storage, or reuse a sessionKey across sign-outs. `ViewerPosition` contains
`{sourceKey, page, zoom}` and is honored only for the exact company/user/login/
Matter/attachment/hash/size/name/MIME identity. Parent must clear remembered
positions on logout/account change and purge events. DOCX/text positions are
explicitly labeled text segments, not invented original pages.

`ViewerSource` is the readonly `FilesScope` plus `attachmentId`, `filename`,
`contentType`, `sizeBytes`, `sha256`. `attachmentViewerSource` consumes the real
`MatterFile` fields and rejects a different parent. No source target, version,
scan result or hearing-pack generation endpoint is invented.

`ViewerPorts` requires:

```ts
requestBytes(path, {
  signal?: AbortSignal,
  maxBytes: number,
  rangeProbe?: boolean,
}): Promise<{
  bytes: Uint8Array;
  contentType: string;
  status: number;
  contentRange: string | null;
  cacheControl: string | null;
}>;
revalidate(source, { signal }): Promise<ViewerSource>;
sha256(bytes: Uint8Array): Promise<string>;
subscribeInvalidation(listener): () => void;
```

`revalidate` must perform a fresh session-owned authorized workspace read and
resolve the exact attachment from that Matter's `attachments`, not return the
input/cached metadata. Recheck tenant, user and login generation as well as the
source fields. Absence, 401/403/404, malformed data or mismatch must reject.
Use the existing retained-read permission gate: a disposed Matter can remain
readable; viewer access does not authorize upload or reopening.

The controller performs an original-download range probe itself on every lease
check. Require `206`, exactly one byte, `Content-Range: bytes 0-0/{sizeBytes}`,
the expected MIME and `Cache-Control: no-store`. Full original downloads require
`200`, exact MIME/length, no-store and the attachment's SHA-256 before rendering.
The request owner must bound a native stream before buffering, finish the body
inside its deadline, abort on auth-generation changes, omit cookies, reject
redirects, include the no-paid marker, make no retries and never return URLs.
Global RN fetch without streaming is not an equivalent port implementation.

**Integrated source change, not yet a serving-image claim:** the Matter download
route now emits `nosniff`, `Cache-Control: private, no-store, max-age=0` and
`Pragma: no-cache`, including its one-byte range responses. The backend owner's
PostgreSQL HTTP coverage passed; the final API image and actual native lease
must still prove these headers. The viewer blocks missing no-store; the adapter
never supplies a fabricated cache policy. DOCX remains unwired until its separate
bounded preview transport and response policy are proven.

Subscribe and emit `background`, `logout`, `revoked`, `source-changed` or
`closed` immediately when known. Root must continue unmounting all private UI
on background/logout and using its existing `usePreventScreenCapture` fence.
The component adds an AppState purge but never relaxes FLAG_SECURE/capture
protections for screenshots or tests. No automatic foreground reopening occurs.

### Optional DOCX

Without an explicit `requestDocxPreview` port, DOCX is truthfully unsupported.
The real API exists: `GET /api/matters/{matter}/attachments/{attachment}/preview`
returns `attachment_id`, `filename`, `content_type`, `paragraphs`, `table_rows`.
It reuses download's Matter-visibility gate and validates the OOXML archive.
The optional port is separate from requestBytes' canonical-download allowlist:

```ts
requestDocxPreview(path, {signal, maxBytes}): Promise<{
  value: unknown;
  cacheControl: string | null;
}>;
```

Only wire it with the same auth/no-redirect/no-cookie/no-paid/no-store policy and
a 1 MiB pre-parse body cap. The controller requires no-store, validates the real
DTO and combined 500,000-character bound, then displays native inert Text with
an explicit extracted-text limitation. Tables are linearized after paragraphs;
original layout/images/page order are not claimed. The DTO has no independent
original-byte hash or completeness flag; no preview fidelity/completeness claim
is made. Never use a generic unbounded JSON helper to make this optional path
appear supported.

## Rendering And Lease Bounds

- PDF, PNG and JPEG: real PDF.js canvas/image rendering inside one isolated
  in-memory WebView, never a whole website, OS viewer or QuickLook handoff.
- UTF-8 TXT: native nonselectable Text; embedded NUL/invalid UTF-8 is rejected.
- Original bytes cap: **20 MiB**. Text/preview JSON cap: **1 MiB**;
  combined text cap: **500,000 characters**; text segments: 10,000 code units.
- PDF cap: **1,000 pages**, one rendered page at a time. Canvas cap:
  **8,000,000 pixels** and 16,384 pixels per dimension. Image header dimensions
  are checked before image decoding; cap **16,000,000 pixels**. JPEG header
  scan is capped at 4,096 segments. Page text cap: 100,000 characters.
- Zoom steps: 50/75/100/125/150/200 percent. Pixel limits can reject a higher
  zoom/oversized page visibly. Controls retain 44pt iOS/48dp Android targets.
- Native access/fetch deadline: **15 seconds**. Renderer admission/page deadline:
  **15 seconds**. Transfer chunks: **48 KiB**, one native chunk per exact ACK;
  inbound native event cap: 1,024 characters, exact admitted schemas only.
- Access lease: **15 seconds from the start of the metadata check**, not from
  its completion. Metadata and range checks occur before and after full bytes.
  At expiry, the controller denies further content copies, removes the reader,
  awaits the host's React removal-commit acknowledgement, then renews metadata
  and range checks. Native tests must prove the actual display removal ordering.
- During renewal the original verified bytes remain in controller memory only,
  unavailable to the renderer; on denial/error/purge they are zeroed. Successful
  renewal rerenders those verified bytes without redownloading the full file.
- PDF WebView has its own expiry timer. Late access/transport/hash results are
  generation-fenced and their owned byte arrays are zeroed. There is no retry,
  offline opening, durable cache, recovery queue or automatic mutation.

**Revocation is bounded/polled, not immediate.** A remote grant change not
delivered through invalidation may remain visible until the 15-second lease
expires while JS/native scheduling is functioning. Suspension, OS process death,
UI-thread delay and screen/app-switcher behavior require native proof. JS strings,
engine-internal parser buffers, bitmaps and WebView/native memory are released
by unmount/process cleanup, not claimed to be forensically zeroized. Only owned
Uint8Arrays are explicitly overwritten. Root capture/backup/restore/reinstall
fences remain mandatory, separate acceptance work.

The HTML contains only public renderer assets and a random, non-secret instance
nonce. Private bytes move through a bounded base64 postMessage protocol, not HTML,
URLs, files, injected JavaScript or an authentication bridge. Nonce-only script
CSP rejects eval; network/fonts/workers/frames/objects/forms are denied. Embedded
PDF JavaScript, scripting manager, XFA and interactive annotations/links are not
enabled. WebAssembly decoders are disabled; documents requiring unavailable
decoders or unsupported features can fail visibly. Password-protected PDFs,
unsupported/corrupt files, bounds and renderer crashes never trigger download,
print, share, remote resource, third-party viewer or external navigation fallback.
PDF embedded text is real, bounded page text; scanned PDFs do not invent OCR.

WebView uses incognito/no cache/no DOM storage/no cookies/no file access/no
debugging/no text interaction/no link previews. `originWhitelist=['*']` is
intentional: v14's JS wrapper can otherwise call `Linking` for unmatched URLs.
The separate navigation callback admits only the initial `about:blank`/other
top-level load. All other navigation, popup and download callbacks deny/purge.
Parent must prove the native engine never hands these events to another app.

## Selectors And Acceptance

`private-document-viewer`, `viewer-close`, `viewer-filename`, `viewer-toolbar`,
`viewer-position`, `viewer-previous`, `viewer-next`, `viewer-zoom`,
`viewer-zoom-in`, `viewer-zoom-out`, `viewer-isolated-renderer`,
`viewer-text-reader`, `viewer-text`, `viewer-docx-limitation`, and
`viewer-{idle|loading|renewing|blocked|unsupported|closed}`.
WebView document IDs: `content`, `page`, `page-text`, `status`.

There is no audited source-open control because `MatterFile` has no canonical
source-action target. Existing hearing packs can be viewed only after parent
resolves an actual authorized stored attachment with this contract. MOB-21's
hearing-pack/source-redirect portions remain open; no generation or invented
attachment/source-action URL is provided.

Explicit six-file verification command from `apps/mobile`:

```powershell
node --experimental-transform-types --test src/viewer/assets.test.ts src/viewer/contracts.test.ts src/viewer/controller.test.ts src/viewer/integration-contract.test.ts src/viewer/renderer.test.ts src/viewer/security.test.ts
```

The renderer test uses the repository's existing Playwright/Chromium installation,
an in-memory document and denied network routes. It starts no HTTP server, Metro,
emulator or provider. It fails rather than skips if Chromium is unavailable.
Parent must include all six files in standard discovery and its exact source
snapshot/build closure. Parent-owned package test selection now includes
`src/viewer/*.test.ts`; verify the resolved complete inventory after freeze.

The initial complete run is preserved in `evidence-test-first.tap`: 38 pass,
one fail. The failed assertion ran `Function` through privileged DevTools
evaluation, which bypassed eval CSP. The replacement probe executes a later
page-origin task and asserts eval is blocked and the attempted marker is absent.
`evidence-test-second.tap` retains the complete replacement: 39 pass, zero
fail/skip/cancel/todo. `evidence-test-final.tap` adds the effect-replay regression:
**40 passed**, zero fail/skip/cancel/todo across all six explicit files:
assets 2, contracts 6, controller 22, integration 3, renderer 3, security 4.

Renderer proof is real two-page synthetic PDF pixels/text/page navigation/zoom,
inert PDF JavaScript and URI action, real PNG pixels, expiry clearing, CSP
network/eval rejection and no transport. It is not Android/iOS WebView proof.
Public synthetic screenshots are retained in `evidence/`; none contains tenant
content. First typecheck exposed missing native dependency plus a Blob type issue
(corrected). `evidence-typecheck-pending.txt` retains the later missing-WebView
module/type errors before the parent's install. No declarations are fabricated
to hide that dependency.

After the parent installed the exact packages, WebView 14.0.1's declaration
defaulted `P` to `undefined`, making `WebViewProps & P` become `never` in strict
TypeScript. The component and ref explicitly use `WebView<unknown>`, retaining
all upstream prop checking with no cast or policy change. The replacement
full-app `--noUnusedLocals --noUnusedParameters` check reported no viewer errors;
its sole remaining error was parent-owned `src/network/http.test.ts:300`
(conditional Content-Length header typing). That incomplete full-app result is
retained separately, not described as a green typecheck. Installed-package asset
`--check` passed. The four prior node-forge findings remain open.

Remaining release gates: exact-SHA standalone Android build and complete Appium
viewer journeys, iOS build/source compatibility and Simulator/VoiceOver proof;
native page pixels and TalkBack/VoiceOver reading; navigation/share/long-press
denial; real source/access races and HTTP no-store/range proofs; background,
logout, app-switcher/capture, WebView cache/backup/reinstall/kill behavior; bounds
on supported target devices; full dependency audit with existing findings still
open; parent review of integration/security, source freeze and release inventory.
No Metro/policy workaround, production/provider/emulator operation, worktree,
commit, push or package/buildconfig edit was performed by this viewer task.
