# Public Enquiries And Isolated Leads

## Scope And Status

Partially implemented. This branch extends the existing durable public demo
admission, not a new CRM or a repair of missing admission. Local focused proof,
integration with the certified QR main, complete release gates and exact-serving
verification remain required. No production lead, provider send, retention
activation or historical mail replay is authorized by this document.

PRD mapping: public admission J19/M21/US-063, FT-094..096, NFT-023 and SEC-031;
isolated administration J14/M14/US-040/042, FT-060/061. The seven public entry
routes already share DemoRequestForm and the durable enrollment/outbox flow:
home CTA, pricing, solo lawyers, law firms, general counsels, guide and resource.
Passwords, setup/reset links, MFA and private workspace forms are excluded.

## Application Contract

- LEAD-01: retain all proven public enquiries in the existing enrollment table.
  A bounded classification/index supports read pagination. Backfill recognizes
  demo-request status, known admission contracts and the pre-contract server UTC
  demo_requested_at marker, including later converted enquiries. Source names
  alone do not establish public admission. Migration changes classification only,
  never notification state or eligibility.
- LEAD-02: GET /api/platform-console/leads uses the existing console cookie,
  live grant and completed MFA with manager authority. Tenant Bearer credentials,
  report viewers, anonymous/challenged sessions and stale/revoked grants do not
  gain access. The read audit carries a report identifier, not submitted PII.
  Existing founder billing authority is not delegated.
- LEAD-03: /platform/leads renders the allowlisted submitted name, email, phone,
  firm/company, segment, selected plan, public entry point, role, intent, notes,
  notice version and server submission time. Signed keyset pages default to25,
  maximum100, ordered by server created_at and stable ID. There is no250-row
  truncation, unbounded count, bulk export, qualification score or CRM mutation.
- LEAD-04: only fresh admissions under the enabled owner policy receive
  notification_purpose public_lead_20261021, notification_policy
  owner_public_enquiries_v1 and notification_eligible true. These server-written
  fields are persisted before acknowledgement. Old-key replay returns the
  original result without altering its snapshot. Missing markers, legacy rows
  and admissions made while the purpose is disabled stay ineligible forever.
  Deployment and restart do not compute a date or retrofit a cohort. The server
  created_at and notification_admitted_at record admission time; no client date
  controls eligibility. A pause retains already-eligible obligations separately
  from transport readiness. Missing sender configuration does not make a new
  eligible lead disappear; it remains in the bounded outbox.
- LEAD-05: the existing reminders worker drains only public-classified rows in
  the new eligible cohort before applying its batch limit. A marked invocation
  targeting a persisted human admission leaves the complete outbox unchanged;
  it cannot claim, recover or suppress that human notification obligation.
  The HTTP route finishes its admission transaction, including replay reads,
  before scheduling delivery; dependency teardown is not its transport fence.
  Its reference-only email uses the server-owned designated enquiry recipient
  and a protected /platform/leads link, not submitted contact fields or notes.
  One private SendGrid personalization is used without CC/BCC. The durable claim
  commits before transport. A fresh read verifies purpose, cohort, no-paid marker,
  sending claim and lease; the database session closes before HTTP. Conditional
  finalization cannot overwrite a recovered/revoked claim. A known rate refusal
  may retry within the existing attempt/backoff bound; uncertain transport or an
  expired sending claim becomes outcome_unknown and is never automatically
  resent. A stored sent result is displayed as Provider accepted, not inbox
  delivery. Founder retry refuses historical, automated and unknown work.

The notification DTO preserves status, attempts, an allowlisted error code and
eligible separately. This makes a retained historical pending or failed attempt
readable without presenting it as a new notification obligation.

The existing local OAuth/console wrapper now also owns a reference-only lead
capture/drain seam. It requires the explicit E2E mode, isolated local database,
loopback origin, no cloud runtime identity, empty SendGrid key, canonical no-paid
context and an admitted synthetic run. The stored automated marker is never
cleared. An invalid local adapter cannot fall through to SendGrid. The fixture
reuses the existing listener, preserves historical/commerce rows and founder
authority, and rotates only its dedicated five-request test window, never the
global production limiter. Capture receipts explicitly say deterministic local
transport and no provider call; they do not prove a real owner's inbox.

## Privacy And Retention

The October21 public notice describes reference-only SendGrid notification and
MFA-protected review. The previous notice version remains accepted for existing
browser compatibility; new forms submit2026-10-21. No submitted PII is copied
into provider error logs, email body, custom arguments or read-audit metadata.

The90-day deletion proposal is not approved by this feature. The purpose-specific
purge switch remains false in canonical API and reminders configuration.
Billing/account/commercial and audit retention boundaries remain unchanged.
The governance map records actual classification, access, provider disclosure,
provenance and unapproved retention truth; it is not legal-policy approval.

## Using The Leads View

These steps describe the candidate feature; use it only after its release is
confirmed below or in the release evidence. Ordinary tenant sign-in is separate
from the platform administration account.

1. Open `https://caseops.ai/platform/sign-in` with your invited platform account.
   Complete its password and authenticator verification. On first setup, scan
   the browser-local QR code in your authenticator and enter its six-digit code;
   never send the QR, setup key or code to support. Leads require manager access.
2. Choose **Leads**, or open `https://caseops.ai/platform/leads`. The newest
   retained public enquiries appear first. Use **Next page** and **Previous
   page** to inspect older entries, and the reload icon for a fresh read.
3. Expand **View submission** for the reference, submitted time, full name,
   email, recorded phone, firm/company, practice segment, role, intent, plan,
   entry point, privacy-notice version and notes. Missing optional fields say
   **Not provided**; the original notes are displayed as plain text.
4. New eligible submissions alert `sanjeev@orchestrum.in` with a reference and
   protected dashboard link. Existing retained enquiries remain visible but do
   not become new email obligations. Repeating the same request key does not
   create another lead or another logical notification.
5. Read **Provider accepted** as transport acceptance, not proof of inbox
   delivery. **Retry pending** is a bounded automatic retry of a known refusal
   or unavailable configuration. **Outcome unknown** means acceptance could not
   be established: preserve that evidence and do not blindly resend. Historical
   or automated rows may correctly show no new-notification eligibility.

Public business-enquiry forms share this path from home, pricing and each
persona/guide/resource demo page. Password resets, MFA setup, private workspace
forms and confidential legal data are not marketing leads. An email-link click
is not a retained enquiry or a measured conversion.

## Verification Inventory

Required native regression: retained legacy/converted/contract rows versus an
unrelated commercial enrollment; data-preserving upgrade, replay and downgrade
on fresh SQLite and PostgreSQL; column/index/foreign-key/catalog health; complete
signed pagination and bounded SQL; MFA/role/realm/revocation negatives; exact
reference-only transport payload and no transaction during HTTP; marked requests;
disabled-to-enabled old-key replay; new eligible admissions across restart;
claim races, stale finalizers, known rejection, unknown/crash no-resend; and
governance, scheduler and release contract alignment.

Fermat owns the new notification native module. Ptolemy owns the new Leads
component and local/production browser specs plus discovery changes. The existing
SEO demo module's SMTP expectations are rebased onto the current verified HTTP
transport while preserving its admission, isolation, rate and retention controls.
The SQLite/pure selection of that module, demo-admin authorization and their
rate-identity consumer passed82 identities/246 phases with38 PostgreSQL cases
explicitly deselected, including a selector regression with25 earlier non-public
cohort rows and the actual request-session replay transport boundary. The
regenerated runtime governance projection and its complete
consumer modules passed31 identities/93 phases. The complete local lead/console
capture modules passed25
identities/75 phases after retaining the test-mount and Windows unread-body
refusal failures. These are scoped development results, not complete backend or
release acceptance. Full affected modules, exact collected IDs and all phases,
including fresh PostgreSQL migration/claim/authorization proof, remain required.

Browser proof must submit through the shared public form, reload the protected
manager view, inspect retained safe details and paginate beyond the old cap at
desktop/mobile widths. Automated/no-paid submissions must never reach real mail
transport. Production renderer fixtures or readiness reads are not evidence of
a real owner enquiry or inbox delivery. No synthetic production lead is allowed.
