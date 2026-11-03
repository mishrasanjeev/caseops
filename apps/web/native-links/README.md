# Production native-link input

`production.json` in this directory is the one public, immutable native-link
configuration for production (schema: `docs/mobile/NATIVE_LINK_CONFIGURATION.md`).
It is absent until the owner supplies the Apple application identifier prefix,
so production native sign-in stays disabled.

When the file is committed, `scripts/deploy-prod.sh` validates it with the
shared reader, enables API native issuance with the
`caseops-native-signing-secret` Secret Manager secret, registers its redirect
URI and points the web runtime at the copy in the image, which serves
`/.well-known/assetlinks.json` and `/.well-known/apple-app-site-association`.
Removing the file disables native sign-in on the next release.
