/**
 * P1-003 (2026-04-24, QG-UI-001/-002) — Frontend page coverage matrix.
 *
 * Walks every `page.tsx` under `apps/web/app/**` and asserts a
 * sibling `page.test.tsx` exists. The audit baseline is 13 of 43
 * pages tested; the rest are tracked in the explicit allow-list
 * below with TODO entries. Going forward, a new `page.tsx` landing
 * without an accompanying test (or an explicit waiver) fails CI.
 *
 * Detection is filesystem-based (no runtime React render needed) so
 * the matrix runs in milliseconds and a missing waiver is easy to
 * find from the failure message.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const APP_ROOT = path.resolve(__dirname);

// 2026-04-24 baseline: pages without a page.test.tsx today.
// Each entry is a route-relative path (matches the page.tsx
// filesystem location). Adding to this set requires a TODO line in
// the comment block above the entry. Removing entries (by adding
// real tests) is preferred over additions; the set is meant to
// shrink, not grow. Per audit priority list:
const ALLOWED_UNTESTED = new Set<string>([
  // Marketing pages — minimal interactivity, low test ROI today.
  // TODO 2026-04-24 add at least mobile + keyboard a11y E2E.
  "general-counsels/page.tsx",
  "guide/page.tsx",
  "law-firms/page.tsx",
  "solo-lawyers/page.tsx",
  "page.tsx", // root marketing landing
  // App pages — REAL gaps. TODO 2026-04-24 add per-page vitest.
  // AQ-003 batch-1 (2026-04-25): the 5 highest-traffic lawyer-daily
  // pages now have sibling page.test.tsx files (matters list,
  // drafting, recommendations, hearings, clients) — entries removed.
  "app/page.tsx",
  "app/admin/notifications/page.tsx",
  "app/admin/teams/page.tsx",
  "app/clients/[id]/page.tsx",
  "app/contracts/page.tsx",
  "app/contracts/[id]/page.tsx",
  "app/courts/page.tsx",
  "app/intake/page.tsx",
  "app/matters/[id]/page.tsx",
  "app/matters/[id]/billing/page.tsx",
  "app/matters/[id]/communications/page.tsx",
  "app/matters/[id]/documents/page.tsx",
  "app/matters/[id]/drafts/page.tsx",
  "app/matters/[id]/drafts/[draftId]/page.tsx",
  "app/matters/[id]/hearings/page.tsx",
  "app/matters/[id]/outside-counsel/page.tsx",
  "app/matters/[id]/recommendations/page.tsx",
  "app/portfolio/page.tsx",
  "app/calendar/page.tsx",
  // sign-in is tested via SignInForm.test.tsx + NewWorkspaceForm.test.tsx
  "sign-in/page.tsx",
  // Additional gaps surfaced 2026-04-24 baseline:
  // (drafting / hearings / recommendations entries dropped 2026-04-25
  // by AQ-003 batch-1.)
  "app/admin/email-templates/page.tsx",
  "app/courts/judges/[judge_id]/page.tsx",
  "app/courts/[id]/page.tsx",
  "app/matters/[id]/audit/page.tsx",
  "app/matters/[id]/documents/[attachment_id]/view/page.tsx",
  "app/matters/[id]/drafts/new/page.tsx",
  "app/outside-counsel/page.tsx",
  // Phase C-2 (2026-04-24): the matter detail page lives at
  // /portal/matters/[id] and has its own page.test.tsx alongside.
  // No waiver needed; included here so the matrix's drift check
  // isn't surprised when the page lands.
]);

function* findPages(dir: string): Generator<string> {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* findPages(full);
    } else if (entry.name === "page.tsx") {
      yield full;
    }
  }
}

describe("P1-003 page coverage matrix", () => {
  it("every page.tsx has a sibling page.test.tsx (or explicit waiver)", () => {
    const missing: string[] = [];
    for (const page of findPages(APP_ROOT)) {
      const testFile = page.replace(/page\.tsx$/, "page.test.tsx");
      if (fs.existsSync(testFile)) continue;
      const relative = path
        .relative(APP_ROOT, page)
        .split(path.sep)
        .join("/");
      if (ALLOWED_UNTESTED.has(relative)) continue;
      missing.push(relative);
    }
    expect(
      missing,
      `pages without a sibling page.test.tsx (add a test or a waiver in ALLOWED_UNTESTED):\n  ${missing.join("\n  ")}`,
    ).toEqual([]);
  });

  it("ALLOWED_UNTESTED entries all point to real page.tsx files", () => {
    // Defensive: drift in either direction (the page is renamed but
    // the waiver isn't, or the page is deleted but the waiver
    // lingers) leaves a useless waiver behind. Surface it.
    const stale: string[] = [];
    for (const relative of ALLOWED_UNTESTED) {
      const abs = path.join(APP_ROOT, relative);
      if (!fs.existsSync(abs)) {
        stale.push(relative);
      }
    }
    expect(
      stale,
      `ALLOWED_UNTESTED entries pointing to non-existent files (delete the waiver):\n  ${stale.join("\n  ")}`,
    ).toEqual([]);
  });
});
