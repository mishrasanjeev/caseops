# Explicit Matter photo capture

This development change starts at Today `f5d95426`. It adds an explicit **Take
photo** action in Files. Camera access is optional; **Choose file** remains the
permission-denial and unsupported-device fallback. Capturing or accepting a
photo never starts an upload. The user sees the parent Matter and must press
**Upload file** separately. Existing capability, current workspace/storage,
observed lifecycle, staging, SHA-256, server security and persisted readback
checks remain in that path. Processing status is not a clean-scan receipt.

The shared synchronous picker lease covers file/camera selection before any
permission or SDK await. A second command is rejected before cleanup. Sign-out
invalidates an in-flight selection; a late photo is removed instead of assigned
to another session. Before starting a selection, App checks the live principal,
membership, session generation, foreground state and upload capability. Normal
server revalidation still governs return from native UI. Native process death
and background behavior remain physical acceptance tasks.

Upload, clear, choose and leave also read the live picker state and the revision
captured with that rendered selection. Their synchronous lease starts before
cleanup/publication can reenter a retained callback. An old callback cannot
upload a retained Android provider URI during capture, clear a new selection,
or confirm a later leave alert. Leave dispatch latches until unmount. Rendered
disabled controls are presentation, not the authority for these commands.

## Supplier admission

The installed Expo 58.0.19 bundled module map specifies ImagePicker `~58.0.10`.
This change pins `expo-image-picker` **58.0.10** and its resolved
`expo-image-loader` **58.0.3**, both MIT with Expo's 2015-present attribution.

| Exact npm source | SHA-256 | Size |
|---|---|---|
| `https://registry.npmjs.org/expo-image-picker/-/expo-image-picker-58.0.10.tgz` | `fb2735d70109a9ab346f2eeb9fc5d530fafd25c83dd01a24634012815e268ab7` |283543B |
| `https://registry.npmjs.org/expo-image-loader/-/expo-image-loader-58.0.3.tgz` | `db6a66b93b0af49f1787907b888fc62aa1e6ad0cbd2eab8b23c49aea8348bbc4` |23021B |

The lock retains each registry SHA-512 integrity. Both tarballs were verified
before isolated installation. All 127 installed package files match the held
tarball contents; npm renames ImageLoader's`android/.gitignore` to`.npmignore`
with byte-identical content. The whole mobile lock and installed npm advisory
audits returned zero known vulnerabilities at this dated check. Eight declared
native Maven coordinates also returned no known OSV findings. These are dated
observations, not a shipping artifact dependency closure or future advisory
waiver. Gradle's complete resolved graph, native licences and final platform
artifacts remain independently required.

The full Expo MIT text and declared Glide/Android Image Cropper native notices
are retained in `CAMERA_NOTICES.txt`, native supplier provenance under
`apps/mobile/vendor/camera-sdk58`, and an Account/About software-licences panel. The
existing JS exception registry and public-web notice inventory are unchanged.

## Native source behavior and privacy

The pinned iOS SDK uses`UIImagePickerController`for camera images. Android uses
`ACTION_IMAGE_CAPTURE`with an app-private output URI, grants the selected camera
activity temporary URI access, and deletes its original SDK output in`finally`.
Both platforms export accepted images into their own`cache/ImagePicker `folder
with UUID filenames. CaseOps accepts only a direct UUID`jpg|jpeg|png`child,
checks the actual size/MIME and retains one copy. Known SDK copies are purged
on cancellation/error/oversize, explicit clear, completed upload, sign-out and
startup. Removal is verified and failure stays actionable. Provider originals
and an external camera application's own files are never deletion targets.

Native capture/copy/encoding happens before JS size checking. The50MiB upload
cap does not bound SDK allocation or native pre-copy work. SDK-managed OS
temporary files, unknown late writes after a lost native result, process death
and forensic erasure need actual device investigation. No pending SDK result is
recovered into a new session without the original intent.

Images only, no editing, base64 or library APIs are requested. App config
declares camera access, removes iOS photo-library/microphone purpose strings and
blocks Android recording audio plus inherited media/storage permissions.
The SDK's`exif:false`option only suppresses JS metadata. Android's raw exporter
copies original bytes; its compression exporter copies EXIF too. CaseOps does
not remove encoded metadata and makes no zero-location claim. The visible
capture/upload disclosure lets the user decide whether to upload that photo.

References: [Expo SDK58 ImagePicker](https://docs.expo.dev/versions/v58.0.0/sdk/imagepicker/),
the exact tarballs above (`ImagePickerModule.swift`, `MediaHandler.swift`,
`ImageUtils.swift`, Android`CameraContract.kt`,`ImagePickerModule.kt`,
`ImagePickerUtils.kt`, both image exporters and the config plugin), and the
installed ExpoModulesCore UUID path generators. Native source explains intended
behavior; it does not certify a built application's effective behavior.

## Acceptance still needed

The automated composition covers permission denial, picker fallback, rapid
commands, sign-out/late completion, cancellation, actual private-file size,
malformed/foreign URI refusal, exact-byte upload/readback, lifecycle/capability
denial, server rejection, unknown response/no replay and owned cleanup. Real
Files JSX controls are exercised with native hosts replaced. Camera hardware,
effective APK/iOS permissions, physical OS denial/recovery, encoded metadata,
background/kill cleanup and accessibility/layout are unrun until matching
independently bound native artifacts and device journeys execute.
