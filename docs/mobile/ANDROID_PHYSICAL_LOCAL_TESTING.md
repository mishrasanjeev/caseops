# Android USB validation

PRD: J20/M22, US-MOB-01..08. This is a local QA transport recipe. It does not establish native acceptance or a distribution build.

The existing emulator profiles remain unchanged. An explicitly selected USB phone uses ADB port 5042, Appium at http://127.0.0.1:4729, and UiAutomator2 system port 8206. Device serials belong in private runtime evidence, never in Git.

Use `--android-transport-mode usb-reverse` with `local-bootstrap.py`. The saved configuration contains `CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE=usb-reverse`; its API and web origins must be distinct HTTPS origins on 127.0.0.1. The normal local ports are 8443 and 3443. The immutable configuration snapshot, backend receipt, extension seed and Android export request must agree on the selected mode. Omitting it preserves the emulator defaults.

A running test session must independently prove:

- The exact USB device, authorized ADB server and private server-key ownership, with no conflicting listener or device selection.
- Reverse mappings for only the owned API and web ports. Record the previous mappings, refuse conflicting mappings and remove only mappings created by this test session.
- A fresh source-bound QA APK for `ai.caseops.mobile.dev.localacceptance`, matching the current API, web, CA and build receipts. Prove an absent or previously owned QA installation before installing. Keep production app data untouched.
- The returned Appium session identifies that same device, package, OS and complete transport tuple. Keep `ADB_SERVER_SOCKET=tcp:127.0.0.1:5042` and the explicit mode in the test environment.

The phone path uses its normal shell UID and `run-as` for the debuggable QA package. It never enables root. Private observations are limited to that package's internal and external app directories; synthetic provider fixtures use an exclusively owned folder under Downloads. Preserve descriptor-bound staging bytes, all scan limits, provider originals and final inventory reconciliation.

Before accepting an absent private copy, exercise a known missing path and an inaccessible path with the actual device's scoped observer. Only an exact reviewed missing-file diagnostic may mean absence. Permission, I/O, transport and malformed responses remain failures.

Keep physical workflow evidence separate from the required 16 KB emulator acceptance. A physical run does not certify a 16 KB emulator run, even when the phone itself uses 16 KB pages. Preserve the complete 83-case / 249-phase inventory, artifact and backend identities, failed attempts and every unexecuted boundary. Camera, biometric and signed HTTPS-link checks need their own actual hardware/signing evidence.

For distribution requirements, use `STORE_PACKAGING_DRAFT.md` and `STORE_PACKAGING_EXECUTION.md`. A local QA APK is not a Play Store submission artifact.
