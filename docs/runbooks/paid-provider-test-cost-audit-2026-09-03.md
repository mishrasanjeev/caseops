# Paid provider test-cost audit — 2026-09-03

## Decision

Bulk, regular, scheduled, and release-verification tests must make zero paid
provider calls. They use deterministic local/Docker provider emulators and
stored hash-verified production evidence. Persistent QA/test tenants are
excluded from paid background polling.

## Evidence reviewed

- Input: `api-logs-2026-09-02.csv`
- SHA-256: `6cb3cb91246bd38763d235cf001d4121e0afdb1511aceace59d621e16cfbce17`
- Rows: 1,108
- Provider timestamps: 2026-05-31 21:56:21 through 2026-08-29 16:30:23
- Successful calls: 1,092; failed calls: 16; failed-call charge: ₹0.00
- Current rate source: [eCourtsIndia API pricing](https://ecourtsindia.com/api/pricing)

The charges in the CSV match the provider's pay-as-you-go rate card exactly:
search ₹0.60, case detail ₹1.50, refresh ₹0.15 per CNR, and order PDF ₹3.75.

## Ledger reconciliation

| Action | Calls | Charge |
|---|---:|---:|
| Case detail | 431 | ₹622.50 |
| Case search | 507 | ₹304.20 |
| Order PDF | 63 | ₹236.25 |
| Case refresh | 107 | ₹39.45 |
| **Total** | **1,108** | **₹1,202.40** |

## Test attribution

Production database records were read to associate provider calls with the
tenant, bookmark, scheduler, and audit event that caused them.

| Classification | Charge | Basis |
|---|---:|---|
| `caseops-qa` release canary and its scheduled refresh | ₹450.90 | ₹447.75 direct fixture activity plus 21 scheduled CNR refreshes at ₹0.15 |
| `legal` tester tenant | ₹299.70 | ₹258.00 mapped case/PDF calls, ₹22.20 non-CNR test searches, and ₹19.50 background refresh |
| Other explicitly test-named tenants | ₹1.80 | `test-legal` and `ct-probe-*` search calls |
| **Confirmed test spend** | **₹752.40** | **62.58% of all charges** |
| Unclassified | ₹1.50 | One deleted/older `DLND020047882015` record lacks durable tenant evidence |
| Operational company workload | ₹448.50 | Mapped non-test tenant activity |

The defensible loss caused by testing is **₹752.40**. If the single unclassified
call was also a test, the upper estimate is **₹753.90**. The full ₹1,202.40 is
not called a test loss because ₹448.50 has operational tenant evidence.

## Permanent controls

1. Every Playwright configuration sends the no-paid-provider request marker.
2. eCourtsIndia and Indian Kanoon reject marked requests before transport or
   billing accounting.
3. Production scheduler configuration excludes `caseops-qa`,
   `caseops-ip-qa`, `test-legal`, and the tester workspace `legal`.
4. Release smoke never creates a fixture, refreshes a case, or downloads a paid
   PDF. Missing verified cache is a controlled failure.
5. Real integration checks, if ever required, are isolated, explicitly
   budgeted, and are not bulk or recurring tests.

## Zero-cost live connectivity check

The authenticated partner court-structure endpoint
`GET /api/partner/causelist/court-structure/states` returned HTTP 200 with 38
records on 2026-09-03. The provider documents this metadata endpoint as free;
no search, detail, refresh, cause-list search, or PDF endpoint was called.
