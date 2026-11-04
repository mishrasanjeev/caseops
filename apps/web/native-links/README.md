# Production native-link input

`production.json` in this directory is the one public, immutable native-link
configuration for production (schema: `docs/mobile/NATIVE_LINK_CONFIGURATION.md`).
The committed input is Android-only (no `ios` section): package
`ai.caseops.mobile`, the upload-key certificate digest and the callback
`https://caseops.ai/native/oauth/callback`. Add the `ios` section once the Apple
application identifier prefix exists, and add the Google Play app-signing digest
before distributing through Play. Keep the bytes exact: released apps embed this
file's SHA-256.

When the file is committed, `scripts/deploy-prod.sh` validates it with the
shared reader, enables API native issuance with the
`caseops-native-signing-secret` Secret Manager secret, registers its redirect
URI and points the web runtime at the copy in the image, which serves
`/.well-known/assetlinks.json` and `/.well-known/apple-app-site-association`.
Removing the file disables native sign-in on the next release.
