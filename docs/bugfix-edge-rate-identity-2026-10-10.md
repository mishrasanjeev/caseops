# Purpose-Only Edge Rate Identity

## Status And Scope

Bug verdict: **Inconclusive** for production. Enterprise gap status:
**Partially implemented**. This independent candidate starts at
`99297e17b00dd51178e21baf596ba2ebfd92c5f7`; it does not authorize deployment or
close the current release NO-GO. Main owns integration and fresh acceptance.

PRD trace: canonical `docs/PRD_CODEX_2026-04-23.md`, `US-001` authentication
and `J19 / M21 / SEC-031` public/privacy boundaries; existing authentication
rate controls in `docs/WORK_TO_BE_DONE.md` section 2.6. User story: a public
caller cannot evade a process-local demo/authentication limit by changing
untrusted forwarding headers, while distinct verified edge clients retain
independent buckets. This identity grants **no** authentication, tenant,
capability, provider or billing authority.

## Reproduction And Authority

Three retained pre-repair native calls fail with successful setup/teardown:
raw XFF changes the rate key, six rotating demo claims all receive 200, and
five rotating invalid login claims all receive 401 rather than the configured
threshold. These are local reproductions, not production abuse probes.

The applicable global external Application Load Balancer documentation says
XFF is appended without validating the caller's existing prefix. Backend
custom request headers overwrite incoming headers of the same name; URL-map
header transformations can take precedence. Primary references:

- https://docs.cloud.google.com/load-balancing/docs/https#x-forwarded-for_header
- https://docs.cloud.google.com/load-balancing/docs/https/custom-headers-global
- https://docs.cloud.google.com/compute/docs/reference/rest/v1/backendServices/patch

The official **Create custom headers in backend services** page above was
last updated **2026-10-06 UTC**, independently rechecked on 2026-10-10.
Its variable table defines `client_ip_address`; its header behavior specifies
case-insensitive same-name overwrite; its URL-map section gives URL-map
transformations precedence; its limitations cap each backend's custom request
headers at 8 KB/16 headers before expansion. These documented contracts do not
replace the pending controlled GET overwrite and exact-serving readiness proof.

The reviewed metadata shows an `EXTERNAL_MANAGED`, HTTPS-only frontend and
exact serverless API/Web backend/NEG bindings. This is not proof of an
already installed dedicated edge contract. No production requests, leads,
authentication floods, provider calls or cloud mutations were run here.

## Protocol

The guarded reconciler installs two purpose-only backend request headers:
`X-CaseOps-Edge-Client-IP:{client_ip_address}` and
`X-CaseOps-Edge-Attestation:<dedicated random 256-bit token>`. The token is
stored in `caseops-rate-identity-edge-token` with immutable numeric version
references on both services. It is never a browser key or an auth/readiness
secret. Compute configuration/audit readers and authorized runtime-secret
readers are explicitly privileged platform principals: they can forge this
limited rate/scheme authority. This protocol does not protect against those
principals, compromised runtimes, or signing-key disclosure.

API compares the attestation in constant time and strictly validates bounded
IPv4/IPv6. Web verifies that same incoming edge contract before signing
`caseops-rate-v1\nMETHOD\nPATH\nCANONICAL_IP\nTIMESTAMP` with HMAC-SHA256.
The API accepts a signed claim only for demo POST or stateless readiness GET,
without query/encoded-path aliases, at most 30 seconds old or 5 seconds ahead.
The signed browser identity takes precedence over the API edge's Web egress
identity. IPv4-mapped IPv6 canonicalizes to IPv4 in both runtimes.

Caller-supplied XFF, X-Real-IP and X-Forwarded-Proto are never authorities.
Duplicate, malformed, oversized, incomplete, expired or mismatched dedicated
claims fail closed. Web never signs caller-supplied forwarding claims and
never forwards cookies, authorization or the edge token to API. The existing
no-paid marker remains authoritative. Production-required demo admission
rejects unsigned direct entry before persistence. Other unsigned requests use
the actual socket peer; limits remain **per-process**, not global 5/hour.

## Scheme And Adjacent Consumers

Production Uvicorn uses `--no-proxy-headers`; arbitrary raw headers cannot
mutate the ASGI peer or scheme. Narrow middleware sets HTTPS only for verified
purpose authority and the deployment-proved HTTPS edge setting. It does not
change `scope.client` or slash redirect behavior.

Source inventory: authentication dependencies, CSRF and problem details use
only `request.url.path`; no `request.base_url` consumer exists. The single
absolute API `request.url_for` consumer is the Pine Labs webhook URL in
`api/routes/payments.py`. Native loopback tests prove verified HTTPS `url_for`
and unchanged real peer, unsigned HTTP despite forged XFP, and relative slash
redirects with encoded queries. Host-header policy is unchanged. Calendar,
Gmail and Drive OAuth callbacks use validated server-owned connector/settings
redirect URIs, not inferred forwarded origins. No OAuth runtime was changed.
Eight supported command variants explicitly disable ProxyHeaders: production
Docker CMD, Compose (including its test-only app override), `dev:api`, both
general Playwright Python variants, both app-suite OAuth-emulator variants,
and functional QA. Filters, no-paid controls and `Connection: close` remain
unchanged. A retained native Compose baseline shows Uvicorn itself rewriting
the loopback peer from raw XFF before the app sees it; source removal alone
was insufficient. Static command inventory and actual CLI socket regressions
cover the repair. Arbitrary external Uvicorn invocations are not supported
release entrypoints; the app cannot recover a peer already rewritten by an
external wrapper. Test-only programmatic servers in auth-dispatch/finalizer
proofs are not release launchers and are not modified here.

## Guarded Release Contract

Only `scripts/deploy-prod.sh` invokes `scripts/reconcile_rate_identity_edge.py`
for canonical release preparation and verification. Every mutation freshly
checks clean frozen HEAD against refreshed `origin/main`. Preparation validates
the exact HTTPS frontend/map/backend/NEG tree before secret or IAM changes,
preserves unrelated backend headers, uses fingerprinted REST patches with
token only in the in-memory body, and verifies exact readback. URL-map
overrides, alternate HTTP frontends, wrong bindings, malformed keys, header
capacity overflow and existing conflicting authority fail closed. Existing
CDN caching or backend response overrides of authority/no-store also fail
closed, without mutating those unrelated settings. Existing
keys are not implicitly rotated; rotation/partial-install repair requires a
separately coordinated reviewed procedure. No new WAF or ingress restriction
is introduced.

Post-deploy verification requires exact release/env/numeric secret references
and unoverridden image entry policy. Public API `/api/health/rate-identity`
and Web `/api/demo-readiness` GETs prove edge overwrite and signed forwarding
without a lead. Direct run.app probes cannot assert edge authority. All
readiness responses are `Cache-Control: no-store` and contain exactly
`ready`, `provenance`, `release_sha`: no IP, token, stable hash or tracking ID.
The explicit strict readiness model also documents the exact 200/403 OpenAPI
shape. Main must regenerate the complete OpenAPI/client after integration;
this task does not claim generated-client coverage.
Readiness is not a product-journey or global-rate certification.

## Verification And Remaining Gate

Committed regressions: `test_rate_identity_edge_20261009.py`,
`test_rate_identity_http_20261009.py`,
`test_deploy_rate_identity_edge_20261009.py` and Web
`lib/server/rate-identity.test.ts`, alongside complete existing rate-limit,
demo proxy/admission, health and canonical redirect files. Offline control-plane
tests intercept subprocess/REST rather than installing fake CLIs, so PATH
fallthrough cannot execute real cloud commands.

`test_rate_identity_entrypoints_20261010.py` covers eight supported launcher
variants, real native CLI peer preservation, strict readiness/OpenAPI 200/403
contracts, incomplete dedicated claims and refusal of auth/readiness-key reuse.
The existing historical `test_deploy_prod_hardening.py` exact CMD assertion
and fake canonical-deploy transport must be updated by their current owner for
the new flag and helper protocol, retaining all original guards. That shared
file and Hubble's workflow/native-report contracts are not edited or waived.
Main must retain Faraday's later deterministic/unique/prototype proxy-test
improvements when resolving the independent-base proxy-test conflict.

Native collection/results and each setup/call/teardown phase are retained in
the independent worktree's ignored
`.tmp/issues-security-20261009/edge-rate-identity/`. Failed evidence is retained:
baseline-r1; fixed-sqlite-r1's cross-runtime mapped-IPv6 failure; web-r1's
config-loader setup failure; full-api-r2's PostgreSQL published-port setup
failure with zero product calls. Replacement evidence must reconcile complete
inventories and source pins; none of those failures is rewritten as green.

Production remains unverified. Main must review/integrate this candidate,
resolve the separate admin authorization repair without exemptions, run fresh
complete Docker/CI on final main, install/readback the dedicated contract via
guarded release, verify readiness and exact serving identities, and complete
canonical release QA. No existing issue or production failure is closed by
this local candidate.
