# Production verifier correction, 27 August 2026

## Observed release

Canonical production revision `d7c7835b077054206d497822426a54e1aeb3c5f4`
passed migration, scheduler reconciliation, the 512 MiB database-index health
gate, exact API/web identity, latest-only traffic, and public health checks.
API and web served immutable current-revision images.

Production verification run `33077807418` reported 87 passed, 5 skipped, and
two release-gate failures. Neither failure was a database timeout:

- the IPLF-025B browser journey opened the selected docket on `Access and
  links` and therefore could not see the hearing form;
- the IPLF-027B A0 check could not find its historical deterministic fixture,
  whose preparation is hard-bound to retired predecessor `3177f017...`.

The hearing failure reproduced from this workstation against the exact live
release. The page state showed the requested docket and a selected access tab,
which isolated the defect from API latency, scheduler delivery, and database
query work.

## Permanent correction

Candidate `f7c672e822ff18b1e4dad46ca1f77c30b82b7d50` establishes an explicit IP
docket work-area URL contract and makes the archived A0 transition check a
manual opt-in. The historical A0 spec, fixed origins, exact-release assertion,
and evidence are retained; the generic verifier simply stops treating an
unrecreatable one-time transition fixture as current release health.

Focused local proof is recorded in
`docs/ip-implementation/evidence/m6/IPLF-061B/local-2026-08-27.md`. Full local
API, web, Docker, PostgreSQL/index, hosted CI, deployment, and complete
production verification remain required before this correction is a released
fix.
