# Phase C — Client + outside-counsel portals

Date: 2026-04-24
Status: Kickoff — PRD addendum drafted; scope decisions blocking implementation listed below.
Closes: BUG-026 (no client portal), BUG-027 (no outside-counsel portal).
Reuses Phase B primitives (calendar, communications, AutoMail, KYC, billing).

## 1. Why Phase C now

Phase B closed the internal-side foundations (J08 calendar, J12 client lifecycle,
M11 communications + AutoMail + KYC). The next external-facing surface that
unlocks revenue is the **portal layer**: letting two non-firm personas log in
with strictly scoped access and self-serve the same primitives.

Without portals:

- BUG-026: lawyers must email clients status updates one-off, breaking the
  "system of record" claim for client-facing communication.
- BUG-027: external counsel work product (briefs, opinions, billings) lives
  on disconnected email + Dropbox flows, defeating the matter graph.

The two portals share ~80% of their code: same auth shell, same scoping
primitive, same matter-context view, same comms inbox. Building them as one
shared scaffold (with two role variants) is the right architectural call —
**not two parallel codebases.**

## 2. Decisions blocking implementation (USER REVIEW NEEDED)

These are the four crisp choices Phase C cannot start cleanly without. Each
has a recommendation; pick or push back.

### D1. Persona model

**Recommendation:** A new `PortalUser` table, separate from `Membership`. No
role inheritance, no shared auth surface. Portal users belong to a `Company`
(the law firm's tenant) but never have a `Membership` row. They are scoped
to one or more `Matter`s via a new `MatterPortalGrant` table.

**Why:** Prevents the most dangerous bug class — a portal user accidentally
inheriting an internal capability via shared role lookup. Two distinct tables
means a typo in `require_capability` cannot leak.

**Alternative:** Add a `MembershipKind` discriminator on the existing
`Membership` table. Cheaper to build, riskier — any new capability defaults
to "all memberships" unless the author explicitly excludes portal kinds.

### D2. Auth model

**Recommendation:** Email magic-link sign-in for portal users (no password).
Sessions are HttpOnly cookies, scoped to `/portal/*`, separate from the
internal `/app/*` cookie (different name). Magic link expires in 30 minutes;
sessions live 7 days; per-portal-user "revoke all sessions" admin action.

**Why:** Clients and external counsel will not remember a fifth password.
Magic link is the modern standard for low-friction external access. Keeping
the cookie scope distinct prevents any cross-contamination with internal
sessions if the same browser hits both surfaces.

**Alternative:** OAuth via Google + Microsoft — better for enterprise outside
counsel, worse for a typical Indian client without a Google Workspace.

### D3. Routing and domain

**Recommendation:** `caseops.ai/portal/*` (same domain as the marketing +
internal app), with the portal's UI shell visually branded as the firm
(firm's logo, firm's colours read from `Company`). Single domain keeps the
deploy simple, single TLS cert, single CSP.

**Why:** Branding the portal as the firm matters for trust; routing under a
known domain matters for spam-filter-friendly magic links. White-labeling
beyond logo + accent colour is out of scope for V1.

**Alternative:** `portal.caseops.ai` subdomain. Cleaner separation, more
infra (extra DNS + cert + Cloud Run service). Defer to V2 if firms ask.

### D4. Pricing + seats

**Recommendation:** Portal seats are **free for V1** — bundled with the firm's
existing plan, capped at 50 client portal users + 25 outside-counsel users
per workspace. This makes portals an obvious "yes" for every existing tenant
without a new pricing negotiation.

**Why:** Phase C is about retention and matter-graph completeness, not direct
revenue. Once usage stabilises, V2 can introduce paid tiers.

**Alternative:** Per-seat pricing from day one (₹99/seat/month). Slows
adoption, complicates the M11 KYC flow (KYC submitter can't always be the
billing payer).

## 3. Recommended phased build (after decisions land)

```
Phase C-1  shared portal scaffold              ~5 days
           - PortalUser table + magic-link auth
           - /portal/* router + Topbar + Logout
           - Company branding hooks (logo + accent)

Phase C-2  client portal (BUG-026)             ~5 days
           - matter view (read-only) + Comms inbox + KYC submit
           - "Reply to firm" → posts to internal Communications log
           - Calendar widget for hearings (read-only ICS subscribe)

Phase C-3  outside-counsel portal (BUG-027)    ~6 days
           - assigned-matters view + work-product upload
           - "Submit invoice" → posts to internal Billing inbox
           - Time-entry form → matter time log

Phase C-4  admin surface                        ~3 days
           - Invite portal users, revoke, audit trail
           - Per-grant scope (which matters, which actions)
           - Email-template variants for portal invites

Phase C-5  hardening + Playwright sweep        ~2 days
           - Tenant + scope isolation tests
           - Magic-link replay protection test
           - Prod smoke for both portals
```

Total: ~3 weeks of focused work, single engineer.

## 4. Out of scope for Phase C

- Mobile app (portal is responsive web only)
- White-label beyond logo + accent
- Real-time messaging (portal Comms is async, polled, not WebSocket)
- Per-seat billing
- Payment-link payments inside the portal (deferred to Phase D)
- Document e-signature (deferred to Phase D)

## 5. PRD addendum landing

The PRD addendum (P8 + P9 personas, J17 + J18 journeys, MOD-TS-014/015/016)
will land in `docs/PRD_CLAUDE_CODE_2026-04-23.md` once D1–D4 are confirmed.
Drafting it before alignment risks rewriting it after a single decision flip.

## 6. What is NOT in this kickoff doc

- Code. No portal code lands until D1–D4 are decided.
- Migration. No new tables until the persona model is locked.
- Marketing copy. No "Portals are coming" announcement until V1 is in prod.
