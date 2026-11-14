# V1 Calendar producer integration — 2026-11-13

J20 / M22, US-MOB-01..08; remaining V1-17 native workflow preparation.
Release verdict: NO-GO. Native case credit: zero for this change.

The base producer now executes the typed three-family Calendar catalogue. It
retains actual creator, operational-Matter and link acknowledgements, performs
normal member login/MFA/identity, preserves owner access while previewing and
applying the two necessary restricted-record grants, and verifies the complete
member docket rows and Calendar feed. The 22 physical requests and 12 POSTs
consume the existing 96-request/64-write/180-second base budget. Their capacity
is reserved before the first mutation. Private preview/apply bytes use the
existing one-use gateway permit, are never reserialized, and are wiped after
use. Public journals omit the private payload and preview value.

Calendar DTO fields must resolve from the typed readback. Separate presentation
oracles can supply observed day labels and row text while preserving whole
source DTOs. The obsolete operational-deadline create route is no longer admitted.
Normal MFA acknowledgement is held in the host closure without its TOTP code;
member identity is checked against the actual final normal-auth response too.

Verification: complete apps/mobile/e2e/v1-workflows.test.mjs inventory, 178 tests,
zero failures, skips, cancellations or todo in retained run
native-release-20261111-ZzEIol4V/v1-ip-access-host-unit-07.log. The composed base
producer executes 68 synthetic protocol calls/57 POSTs and the real loopback TLS
gateway exercises the private byte bridge and single-use member summary permit.
These are offline protocol and real TLS transport checks, not PostgreSQL or
native-device acceptance. Run 04 remains retained: its exact timeout fixture
assumed 8 seconds while the composed producer correctly supplied its original
10-second per-request ceiling. Default 8-second coverage is unchanged; the
composed fixture now checks exactly 10 seconds. No production budget changed.

Still required: actual fresh governed PostgreSQL profile, entitlement-worker
positive/negative database journeys, complete normal catalogue/fixture production,
current native selector observation and all 17 cases on each platform. Existing
Android Core23/Files17 and iOS Core23 retain their own c8dd artifact/source scope.
No production review, rollout, or store approval follows from this integration.
