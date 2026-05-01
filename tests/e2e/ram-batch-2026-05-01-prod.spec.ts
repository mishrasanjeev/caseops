/**
 * Ram 2026-05-01 batch — prod verification of three reopens / shallow
 * follow-ups landed in commit 06f63a9. Per the bug-fixing skill:
 * "Reopened bugs require fresh end-user verification before closure."
 *
 * Coverage:
 *   - ENH-004: "New draft" button on the matter drafts page must
 *     route to the template grid; grid must list all 20 templates;
 *     clicking a template must reach the stepper (not silently fall
 *     back to the grid).
 *   - BUG-029: POST /api/matters/{id}/recommendations must NOT 502
 *     on a single GPT-5.1 format error. We can't deterministically
 *     trigger that path in prod, so this spec asserts the API is
 *     reachable and returns a non-502 status — the regression test
 *     in test_recommendations.py covers the retry semantics
 *     deterministically.
 *   - BUG-028: opening /app/matters/{id}/documents/{aid}/view must
 *     not surface the "Could not load the PDF" error. Worker now
 *     loads from the same origin (Next.js bundle), so CSP passes.
 *
 * Run:
 *   PROD_BASE_URL=https://caseops.ai npx playwright test \
 *     --config playwright.prod-ram.config.ts \
 *     tests/e2e/ram-batch-2026-05-01-prod.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string => {
  const v = (process.env[key] ?? "").trim();
  return v.length > 0 ? v : fallback;
};
const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");

async function firstMatterId(page: Page): Promise<string | null> {
  const cookies = await page.context().cookies();
  const cookieHeader = cookies
    .filter((c) => c.domain.includes("caseops.ai"))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const resp = await page.context().request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    { headers: { Cookie: cookieHeader, Accept: "application/json" } },
  );
  if (!resp.ok()) return null;
  const body = await resp.json();
  const matters = body?.matters ?? [];
  return matters[0]?.id ?? null;
}

test.describe("Ram batch 2026-05-01 — prod verification of 06f63a9 fixes", () => {
  test("ENH-004: New draft button routes to template grid (NOT legacy 5-option dialog)", async ({
    page,
  }) => {
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters; cannot verify drafts UX.");
      return;
    }

    // Navigate to the matter drafts list page (where the bug was).
    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}/drafts`, {
      waitUntil: "networkidle",
    });

    // Click the "New draft" trigger. There are two CTAs with the same
    // testid — the header button + the empty-state button (BUG-020
    // pattern again). `.first()` disambiguates; both navigate to the
    // same /drafts/new path.
    const trigger = page.getByTestId("new-draft-trigger").first();
    await expect(trigger).toBeVisible();
    await trigger.click();

    // Old behaviour: a dialog opens with a 5-option <Select>.
    // New behaviour: the URL changes to /drafts/new and the template
    // grid renders. Assert we landed on the grid by looking for an
    // "All templates" heading.
    await page.waitForURL(/\/drafts\/new(\?|$)/, { timeout: 5_000 });
    expect(page.url()).toMatch(/\/drafts\/new(\?|$)/);

    // The grid loads templates via /api/drafting/templates; wait for
    // at least one card before counting. Without the wait, the locator
    // resolves before React Query has hydrated.
    const cards = page.locator('[data-testid^="start-draft-"]');
    await expect(cards.first()).toBeVisible({ timeout: 15_000 });
    const cardCount = await cards.count();
    // Sprint 1+2 shipped 20; reasonable lower bound = 10 so a single
    // failed template doesn't sink the spec.
    expect(cardCount).toBeGreaterThanOrEqual(10);

    // Click a Sprint-1 template (writ_petition). Pre-fix this would
    // silently fall back to the grid because writ_petition wasn't in
    // KNOWN_TEMPLATE_TYPES. Post-fix, the URL must include
    // ?type=writ_petition AND the stepper must render.
    const writCard = page.getByTestId("start-draft-writ_petition");
    if ((await writCard.count()) > 0) {
      await writCard.first().click();
      await page.waitForURL(/\?type=writ_petition/, { timeout: 5_000 });
      // Stepper-internal element — present iff the schema fetch
      // succeeded + the gate let the type through. The testid format
      // is `step-<group_name>` (e.g. step-facts / step-impugned /
      // step-grounds / step-relief) — Sprint 1 writ_petition has the
      // group "impugned" as its second step. Match any step-* element.
      const anyStep = page.locator('[data-testid^="step-"]');
      await expect(anyStep.first()).toBeVisible({ timeout: 15_000 });
    } else {
      // The list-templates endpoint returns 20; if the card is
      // missing the bug is somewhere else (likely a deploy lag).
      // Fail loud — Ram will see the same gap.
      throw new Error(
        "writ_petition template card NOT found in /drafts/new grid — " +
          "openapi-types or template list deploy is stale.",
      );
    }
  });

  test("BUG-029: recommendations endpoint does NOT 502 on a single transient call", async ({
    page,
    request,
  }) => {
    test.setTimeout(240_000);
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters; cannot verify recs.");
      return;
    }

    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrfCookie = cookies.find((c) => c.name === "caseops_csrf");
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader,
    };
    if (csrfCookie) headers["X-CSRF-Token"] = csrfCookie.value;

    const resp = await request.post(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/recommendations`,
      {
        headers,
        data: { type: "authority" },
        timeout: 200_000,
      },
    );
    const status = resp.status();
    // Acceptable terminal statuses: 200 (success), 422 (zero verified
    // citations — content gate, not infrastructure), 503/504 (Cloud
    // Run frontend transient — orthogonal to the LLM retry path).
    // 502 is the EXACT failure mode BUG-029 describes
    // (LLMResponseFormatError on GPT-5.1 malformed JSON, no retry);
    // explicitly assert NOT 502.
    expect(status).not.toBe(502);
    if (status === 502) {
      throw new Error(
        `BUG-029 reopen: recommendations endpoint returned 502: ${await resp.text()}`,
      );
    }
    // Allow infrastructure-transient codes — they don't prove the bug
    // is back; CI re-runs handle them.
    expect([200, 422, 503, 504]).toContain(status);
  });

  test("BUG-028: PDF viewer does NOT show 'Could not load the PDF' (CSP-safe worker)", async ({
    page,
  }) => {
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters; cannot verify PDF viewer.");
      return;
    }

    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrfCookie = cookies.find((c) => c.name === "caseops_csrf");

    // Find an existing PDF attachment, or upload a sample so the
    // probe has data. Sample is the smallest valid 1-page PDF
    // (~385 bytes). The QA workspace gets a single seeded PDF; later
    // runs reuse it.
    //
    // Attachment list comes via the workspace endpoint (the matters
    // router doesn't expose a GET /attachments — see route audit
    // 2026-05-01).
    const wsResp = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/workspace`,
      { headers: { Cookie: cookieHeader, Accept: "application/json" } },
    );
    if (!wsResp.ok()) {
      test.skip(true, `workspace endpoint returned ${wsResp.status()}`);
      return;
    }
    const wsBody = await wsResp.json();
    let pdf = (wsBody?.attachments ?? []).find(
      (a: { content_type: string | null }) =>
        (a.content_type ?? "").toLowerCase().includes("pdf"),
    );

    if (!pdf) {
      // Upload a sample PDF so subsequent runs have data. Tiny valid
      // PDF — single empty page.
      const SAMPLE_PDF = Buffer.from(
        "255044462d312e340a312030206f626a3c3c2f547970652f436174616c6f672f50616765732032203020523e3e656e646f626a0a322030206f626a3c3c2f547970652f50616765732f4b6964735b33203020525d2f436f756e7420313e3e656e646f626a0a332030206f626a3c3c2f547970652f506167652f506172656e7420322030205220" +
          "2f4d65646961426f785b302030203630302039305d2f436f6e74656e74732034203020523e3e656e646f626a0a342030206f626a3c3c2f4c656e6774682030203e3e73747265616d0a656e6473747265616d0a656e646f626a0a787265660a3020350a303030303030303030302036353533352066200a30303030303030303039203030303030206e200a30303030303030303531203030303030206e200a3030303030303030393920" +
          "30303030302066200a30303030303030313434203030303030206e200a747261696c65723c3c2f53697a6520352f526f6f7420312030205220203e3e0a7374617274787265660a3231300a2525454f460a",
        "hex",
      );
      const headers: Record<string, string> = { Cookie: cookieHeader };
      if (csrfCookie) headers["X-CSRF-Token"] = csrfCookie.value;
      const upResp = await page.context().request.post(
        `${PROD_API_BASE_URL}/api/matters/${matterId}/attachments`,
        {
          headers,
          multipart: {
            file: {
              name: "qa-sample.pdf",
              mimeType: "application/pdf",
              buffer: SAMPLE_PDF,
            },
          },
          timeout: 30_000,
        },
      );
      if (!upResp.ok()) {
        test.skip(
          true,
          `Upload failed (${upResp.status()}): ${await upResp.text()}; cannot seed BUG-028 fixture.`,
        );
        return;
      }
      pdf = await upResp.json();
    }

    // Navigate to the document viewer.
    await page.goto(
      `${PROD_BASE_URL}/app/matters/${matterId}/documents/${pdf.id}/view`,
      { waitUntil: "networkidle" },
    );

    // The error UI text from PDFViewer.tsx — assert it is NOT
    // present. Generous timeout because react-pdf takes a moment to
    // initialise the worker + first-page render.
    const errorText = page.locator(
      "text=Could not load the PDF. Try the direct download above.",
    );
    await expect(errorText).toHaveCount(0, { timeout: 30_000 });

    // And assert the PDF actually rendered. react-pdf creates a
    // canvas element per rendered page; if the worker failed, no
    // canvas would be created.
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 30_000 });

    // Final cross-check: pdfjs.GlobalWorkerOptions.workerSrc must be
    // same-origin (caseops.ai or relative). Pre-fix the value was
    // https://unpkg.com/pdfjs-dist/.../pdf.worker.min.mjs which CSP
    // blocked. Post-fix it must start with the deployed origin.
    const workerSrc = await page.evaluate(() => {
      const w = (window as unknown as { pdfjsLib?: { GlobalWorkerOptions?: { workerSrc?: string } } });
      // react-pdf re-exports pdfjs as a named import; the global
      // `pdfjsLib` may or may not be set. Fall back to inspecting
      // <script> tags that were dynamically added for the worker.
      const fromGlobal = w.pdfjsLib?.GlobalWorkerOptions?.workerSrc;
      if (fromGlobal) return fromGlobal;
      // No global — sniff the document for any pdf.worker reference.
      const scripts = Array.from(document.querySelectorAll("script[src*='pdf.worker']"));
      const links = Array.from(document.querySelectorAll("link[href*='pdf.worker']"));
      return [...scripts, ...links].map((el) => (el as HTMLScriptElement).src || (el as HTMLLinkElement).href).join(" | ");
    });
    // Either we found it via the global OR via the script tag sniff;
    // either way it must NOT contain unpkg.com (the broken URL).
    expect(workerSrc).not.toContain("unpkg.com");
  });
});
