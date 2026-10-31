# Native client compatibility

The API publishes an additive, unauthenticated, non-cacheable policy at
`GET /api/auth/native/compatibility?platform=ios|android&client_version=1.0.0`.
Its protocol version is 1. The response identifies the requested platform and
client version, the optional minimum supported version, and `supported` or
`update_required`. This is compatibility metadata; it grants no authentication,
tenant access, device attestation or service-readiness guarantee.

`CASEOPS_NATIVE_MINIMUM_ANDROID_VERSION` and
`CASEOPS_NATIVE_MINIMUM_IOS_VERSION` independently default to unset. Versions
have exactly three ASCII integer components, each 0–999999999, without leading
zeroes, suffixes, surrounding whitespace or implicit coercion. Comparison is
numeric: 1.10.0 is newer than 1.2.0. Invalid operator configuration refuses
startup rather than silently changing the policy.

When a platform's floor is set, business requests using a valid native access
grant must carry exactly one `X-CaseOps-Client-Version` header meeting that
floor. The platform comes from the validated device-session row, which was
originally client-reported at sign-in; it is not a device attestation. Header
values do not replace current identity, membership, revocation, expiry or MFA
checks. Missing, malformed, duplicate or older versions receive HTTP 426 with
code `native_client_update_required`, platform and the configured floor; the
submitted version is not reflected in the error.

An older client can still read `/api/auth/security`, list/revoke its authorized
device sessions, and use the existing strict token-body refresh/logout
endpoints. These operations retain their normal authentication and realm
checks. The policy does not revoke a valid session or consume its refresh
credential when a business request is rejected. Browser authority is unchanged.
Removing a floor restores the same otherwise-valid native session.

Deploy the additive API and leave both floors unset before distributing a
client that consumes this policy and sends its actual build version on JSON
and byte requests. Set a floor only after the replacement build is available
to the affected users. A floor is an operational compatibility control, not a
security repair or proof that a particular store build is installed. Missing or
unreadable policy responses must not be presented as `supported`. A rejected
mutation must never be automatically replayed after an update or retry.

This source contract does not certify a native binary, device lifecycle,
physical biometric behavior or store availability. Each platform's actual
binary, source fingerprint, backend revision and native inventory remain
independent release gates.
