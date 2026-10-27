# Optional biometric screen lock

Disabled by default, this device-local gate is enabled explicitly in Account.
It never replaces browser sign-in, PKCE, server MFA, refresh rotation or current
session/membership/capability checks. No endpoint or token format is added.
Sign-out removes the preference; a later sign-in does not silently opt in.

The parsed native token/refresh response's `session_id` is retained with verified
user/company/membership IDs and the in-process session generation. No JWT is
decoded and no rotating token is hashed into a stable identity. A random local
installation UUID replaces the old literal `1` marker without revoking a healthy
credential. A genuinely missing marker retains the existing reinstall credential
purge and also removes known retained lock state. One handle reads at most 65
bytes; single-flight initialization does not replay an unknown mutation. The
installation UUID is not an OS hardware identifier and is not uploaded.

Device-only SecureStore policy contains a version, pending/enabled state,
installation UUID, nonce and server principal/session IDs. A separate fresh
installation service holds the authenticated marker. All its writes/reads
require authentication and `WHEN_UNLOCKED_THIS_DEVICE_ONLY`. Existing refresh
credentials keep their original format/service. No raw biometric data is read.

Enable checks normal server authority, persists pending intent, writes a
protected marker, authenticates exact read-back and revalidates the server
again before committing enabled state. Writing alone never proves biometric
success. Interrupted setup stays locked. One synchronous lease fences every
await. Explicit sign-out invalidates the epoch, revokes/clears credentials,
then waits for native completion before resetting local policy. An unknown
native result never authorizes another prompt or replay.

For opted-in cold restore, protected authentication precedes the callback that
reads the refresh credential. Restored server user/company/membership/session
must match. Explicit sign-out may read that credential solely for revocation
without biometric success; this never reveals a profile or restores authority.
Unsupported devices can continue normal secure sign-in without opting in.

Private screens are covered/unmounted on inactive/background. Existing viewer
buffer and ordinary selection cleanup applies. An owned camera/system-picker
operation retains only its existing opaque intent/SDK copy until it settles;
it cannot automatically upload or reveal UI. This is a screen-access gate,
not extra encryption or forensic erasure of every file/memory region.

Actual background advances the epoch. A prompt's temporary inactive state
covers UI without cancelling that prompt epoch. After completion, a fixed 2 s
foreground acknowledgement is required; no browser/MFA/native-test deadline is
extended. Full binding and epoch checks fence late cleanup, prompt, refresh and
policy acknowledgements. Missing/invalidated marker, malformed/unexpectedly
missing known enabled policy, read error, cancellation and lockout stay locked.
`null` does not identify enrollment change. Generic UI offers explicit retry or
sign-out/secure sign-in. No native error body or private label is reflected.

Existing SecureStore 58.0.2 is sufficient; no biometric dependency is added.
iOS uses `biometryCurrentSet` but reads an unauthenticated alias first, hence the
dedicated service and authenticated-only writes. Own marker aliases are cleared
before fresh creation. iOS creation does not prompt, hence read-back. Android
checks `BIOMETRIC_STRONG` and authenticates a cipher `CryptoObject` with Cancel; no
device-credential fallback is requested. It maps permanently invalidated keys
to`null`without explicitly overriding platform enrollment-invalidation defaults.

Coordinator/adapter controls cover cold proof-before-refresh, legacy/reinstall,
absent keys, stale principal/session/background results, interrupted setup,
duplicate commands, cleanup races and real NativeSession refresh after sign-out.
JSX controls replace native hosts. Physical hardware/enrollment changes,
lockout/OS cancellation, background/kill, backup/uninstall, privacy, accessibility
and matching signed-binary acceptance remain **unrun**. A Simulator returning a
stored value is not biometric acceptance.
