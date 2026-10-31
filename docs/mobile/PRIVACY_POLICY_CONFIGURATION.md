# Public app privacy-policy reference

No owner-approved app privacy-policy URL has been supplied. The existing
publisher contact remains available. The lead/demo privacy page is not an app
privacy-policy substitute, and this implementation creates or publishes no
policy page, mailbox, approval or store-compliance claim.

An owner can provide an immutable public JSON descriptor using
`CASEOPS_MOBILE_PRIVACY_POLICY_FILE` and
`CASEOPS_MOBILE_PRIVACY_POLICY_SHA256`. Both values are required together.
The file must be an absolute canonical, owned, regular single-link file no
larger than 16 KiB. The reader opens once, consumes at most 16 KiB plus one
detection byte, verifies SHA-256 from that descriptor, and rechecks its complete
leaf metadata and canonical ancestor identities before returning the retained
bytes. Windows named-device portability is separate from Windows ACL proof.

The exact descriptor keys are:

| Field | Contract |
|---|---|
| `schemaVersion` | Integer `1` |
| `kind` | `caseops-mobile-privacy-policy` |
| `nativeLinkConfigSha256` | Digest of the admitted owner-provided native-link configuration |
| `url` | Owner-provided canonical HTTPS URL on that configuration's approved web origin |
| `version` | Owner-provided 1–64 character ASCII identifier, starting with a letter or digit and containing letters, digits, dots, underscores or hyphens |

The policy URL must also match `EXPO_PUBLIC_WEB_ORIGIN`. Credentials, ports,
queries, fragments, whitespace and URL normalization are refused. Nothing is
appended to it. A production or store configuration fails if the reference is
absent or invalid. Explicit QA and development builds may carry
no `extra.privacyPolicy` field, which displays an honest unconfigured state.
The build reader returns `null` for that state; it is omitted from the public
Expo projection because the SDK can normalize nested null values into objects.

The normalized public projection is exactly `{url, version, sha256}` in
`extra.privacyPolicy`. The digest identifies the descriptor bytes; it is not a
digest of the page or evidence of content review, ownership, availability,
publication or legal compliance. The build plugin projects the same values to:

| Platform | Compiled keys |
|---|---|
| iOS Info.plist | `CaseOpsPrivacyPolicyURL`, `CaseOpsPrivacyPolicyVersion`, `CaseOpsPrivacyPolicySHA256` |
| Android application metadata | `ai.caseops.mobile.PRIVACY_POLICY_URL`, `ai.caseops.mobile.PRIVACY_POLICY_VERSION`, `ai.caseops.mobile.PRIVACY_POLICY_SHA256` |

The plugin removes only its own stale keys when QA is unconfigured and
preserves unrelated metadata. Actual IPA/AAB postflight must compare the
compiled values with the retained descriptor; a config projection is not a
compiled-artifact result.

Account → Privacy and help offers the configured link only after an explicit
user action. It opens the exact public URL through the system browser without
account, workspace, document or session data. A synchronous lease prevents
rapid or retained callbacks from launching twice. The opening acknowledgement
has a separate ten-second bound. A rejection, synchronous error or timeout is
reported as unknown, never automatically retried; late completion and disposed
callbacks cannot publish another result. A successful browser acknowledgement
does not establish that the page loaded. Physical accessibility, browser and
compiled-metadata acceptance remain pending the rebuilt platform artifacts.
