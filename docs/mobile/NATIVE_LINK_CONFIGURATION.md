# Native HTTPS callback configuration

Status: source support; production native sign-in remains disabled and unverified.
No final domain, application identifier prefix, package/bundle ID or signing
certificate is supplied by this document. Organization enrollment and platform
association/signing remain owner prerequisites.

## One immutable public input

`CASEOPS_NATIVE_LINK_CONFIG_FILE` must name an absolute regular UTF-8 JSON file,
at most 16 KiB. `CASEOPS_NATIVE_LINK_CONFIG_SHA256` must be its exact lowercase
SHA-256. The reader opens once, rejects a symlink/non-file, validates descriptor
identity/stability, hashes and parses the bytes from that descriptor, and closes
on every path. Hash validation proves integrity, not domain or signing ownership.

The complete schema (no additional keys) is:

| Field | Required value |
| --- | --- |
| `schemaVersion` | `1` |
| `kind` | `caseops-native-links` |
| `syntheticDataOnly` | Boolean; production consumers require `false` |
| `redirectUri` | Canonical HTTPS URL, exact path `/native/oauth/callback`, no credentials, port, query, fragment or wildcard |
| `ios.bundleIdentifier` | Owner-selected registered bundle identifier |
| `ios.applicationIdentifierPrefix` | Actual application identifier prefix from the signed app/profile; do not infer or invent a Team ID |
| `android.packageName` | Owner-selected registered application ID |
| `android.signingCertificateSha256` | 1–4 unique lowercase 64-hex certificate digests from the actual app-signing identities |

Production inputs reject known reserved domains, development/acceptance IDs and
obvious placeholder signing values. Structural validation cannot establish that
an arbitrary domain, identifier or certificate belongs to the publisher.

`node scripts/mobile/prepare-native-links.mjs --config <absolute-file> --sha256
<exact-hash> --output <new-absolute-directory>` writes public projections only
outside Git. Add `--synthetic` only for inputs explicitly marked synthetic. It
copies the already-read bytes into immutable `config-evidence.json` and emits
hash-bound mobile policy, API redirect registry, AASA and Digital Asset Links
projections. It never enables API auth, signs an app, accesses production, deploys
association files or declares the platform association verified.

## Consumers and fail-closed behavior

- Mobile app configuration and web server read the same file/hash pair. The app
  embeds only the public policy/digest. The shared browser/native pure validator
  admits the exact URI; PKCE, state, code, platform and query fences remain.
- Production mobile configuration requires the complete non-synthetic input.
  Missing, partial, malformed or mismatched input fails the build. Expo CLI's
  production config mode is `__EXPO_CONFIG_MODE=production`; production export
  also selects production mode. An unconfigured development app is disabled.
- Local acceptance profiles retain their exact custom callback and isolated
  HTTPS origins. They reject mixing production link input. Web local admission
  additionally requires the existing local-acceptance build marker and explicit
  loopback HTTPS origin/port. Missing production configuration never selects
  local mode.
- HTTPS iOS sign-in requires a known iOS version at least17.4 and explicitly
  selects `preferUniversalLinks:true`. Older or unknown versions refuse before
  opening authentication; the SDK's legacy fallback is not used for HTTPS.
- The API retains its existing non-local exact HTTPS redirect registry, separate
  signing key, enablement, PKCE/MFA, single-use and revocation requirements. Apply
  the generated `CASEOPS_NATIVE_REDIRECT_URIS` projection without changing those
  controls. No enablement flags or secrets are generated.
- The inert web fallback returns static, non-cacheable, non-referring content;
  it does not reflect, exchange or redirect a code/state or open a custom scheme.
  Its sole hash-authorized script replaces the browser address with the fixed
  callback path without reading the query. Ingress/access-log query redaction
  still needs operational verification before publishing the real callback.

The source CI production exports will require real configuration once the earlier
unwaived dependency audit can pass. There is no source-only production bypass.

## Required actual readiness proof

Before deployment, independently compare the exact embedded mobile policy/hash,
web server policy/hash, API effective redirect registry and served association
bytes to the same generated input and projections. Preserve current release and
signed artifact identities. A source test or supplied public metadata is not this
proof.

For iOS, verify the actual signed application identifier and associated-domains
entitlement match AASA, the correct profile/capability exists, and HTTPS serves
the exact AASA without redirects. For Android, verify the installed package and
app-signing certificate match `assetlinks.json` (Play App Signing may use a
different key from a local upload key), and observe actual verified App Links.
Choose and test a callback host deliberately; ordinary same-domain Safari
navigation can stay in the browser.

Then run real browser MFA/consent → exact HTTPS app handoff → one PKCE exchange,
identity/readback, logout/revocation and unsafe-callback controls on both signed
platforms. Preserve TLS and all current budgets. The existing local native
receipts remain scoped to their actual custom-callback artifacts.

Official references: [Expo WebBrowser](https://docs.expo.dev/versions/latest/sdk/webbrowser/),
[Apple HTTPS callback](https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession/callback/https(host:path:)),
[Apple associated domains](https://developer.apple.com/documentation/xcode/supporting-associated-domains),
[Apple universal-link diagnostics](https://developer.apple.com/documentation/technotes/tn3155-debugging-universal-links),
[Android association files](https://developer.android.com/training/app-links/configure-assetlinks).
