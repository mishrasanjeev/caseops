# Native client compatibility

This client uses the version from the installed build's Expo configuration
(`app.config.ts`, including its admitted store build version), not the JavaScript
package's development version. Every JSON, multipart and attachment-byte request
carries the same owned `X-CaseOps-Client-Version`. This is compatibility metadata,
not device attestation, authentication, a capability grant or evidence of native
acceptance.

The unauthenticated, same-origin request is
`GET /api/auth/native/compatibility?platform=ios|android&client_version=…`.
The client accepts only the exact five-field protocol-1 response correlated to its
own platform and version. Numeric versions contain three ASCII components,
without leading zeroes, with each component at most 999999999. A floor and status
that disagree are rejected. Missing, malformed, offline and 404 responses remain
unavailable; a 404 does not silently activate a legacy bypass.

The service must deploy this additive endpoint before this app is distributed.
The operator can initially leave both minimum versions unset. Older clients keep
their existing server contract while a floor is unset. A configured floor applies
to server-validated native device sessions; a platform header cannot select a
different floor. Removing a floor permits an explicit client recheck without
revoking or replacing the existing session. Operator rollout and rollback must
still follow the service's own reviewed deployment contract.

Cold start and actual foreground return check policy before business access.
Enabled local biometric policy still requires its authenticated marker before
reading a refresh credential or fetching a private profile. Compatibility success
does not unlock a biometric gate. Native browser return and an owned biometric
prompt reuse the existing two-second foreground-settling bound; interactive,
HTTP, PKCE and server MFA budgets are unchanged. Background epochs and principal
changes reject late policy results.

A central HTTP 426 closes private views and work actions. JSON problems are
accepted as an update floor only when their code, platform and numeric floor match
the client. Attachment errors are cancelled without parsing their private error
body; an explicit public recheck is needed to identify the current policy. No
mutation is replayed. A late dispatched result whose authority was lost remains
unknown. A 426 alone does not clear a valid native credential, including an
explicit refresh rejection; ordinary expired, revoked and invalid-session rules
remain in effect.

The compatibility panel provides a public retry, installation guidance and
explicit sign-out. It does not display private account labels or invent store
listing links. Device revocation is also available from another signed-in device.
The server's security/status/session-list/revoke and refresh/logout exceptions
remain separate from business admission. This app does not use those exceptions
to read security data through an unproved local biometric gate. Explicit sign-out
retains its existing local purge and bounded server-revocation acknowledgement.

Offline tests compose the actual App, local lock, compatibility controller,
transport and native-session boundaries with synthetic SDK/HTTP hosts. They do not
prove installed build metadata, device transport, native focus, effective privacy,
biometric hardware or either platform's complete native inventory. Fresh binary,
backend, device and workflow acceptance remains required.
