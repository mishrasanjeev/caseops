/**
 * Provider-gating for Playwright tests (AQ-006, 2026-04-25).
 *
 * Some E2E tests need real third-party credentials (Pine Labs, SendGrid,
 * etc.). On a developer laptop or a normal PR run we don't want them
 * to fail just because the credential is missing. On a release run we
 * absolutely want them to fail — silently skipping a payment-link test
 * because the key wasn't provisioned is exactly the "we shipped because
 * no test broke" pattern Codex's no-manual-tester replacement standard
 * forbids.
 *
 * Pattern:
 *
 *   import { requireProviderCredentialOrSkip } from "./support/provider-gating";
 *
 *   test.describe("Pine Labs payment link (provider-gated)", () => {
 *     requireProviderCredentialOrSkip(test, {
 *       provider: "Pine Labs",
 *       envVar: "CASEOPS_PINE_LABS_API_KEY",
 *     });
 *     test("...", async ({ page }) => { ... });
 *   });
 *
 * Behavior:
 *
 * - `CASEOPS_RELEASE_MODE !== "true"` (the default for laptops + normal
 *   PR runs): credential missing → test.skip with the documented reason.
 *   Same as `test.skip(!hasKey, "…")` we had before.
 * - `CASEOPS_RELEASE_MODE === "true"`: credential missing → throws at
 *   describe-time with a clear "set CASEOPS_PINE_LABS_API_KEY before
 *   running release E2E" message. The test fails loudly.
 *
 * The release-mode flag is intentionally kept out of the default
 * Playwright config — release CI sets it explicitly, normal CI does
 * not. See the workflow definition + release runbook for wiring.
 */
import type { TestType } from "@playwright/test";

/* eslint-disable @typescript-eslint/no-explicit-any */
type AnyTest = TestType<any, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface ProviderGate {
  /** Human-readable provider name for the skip / fail message. */
  provider: string;
  /** The env var that must be non-empty for the gated test to run. */
  envVar: string;
  /**
   * Optional secondary env vars all of which must also be present.
   * Useful when a provider needs a key + secret + webhook secret + ...
   */
  alsoRequire?: string[];
}

/**
 * Decide for one provider gate whether the calling test.describe()
 * should skip (default) or fail (release mode). Call inside a
 * `test.describe(...)` block before any `test(...)` blocks.
 */
export function requireProviderCredentialOrSkip(
  test: AnyTest,
  gate: ProviderGate,
): void {
  const releaseMode = process.env.CASEOPS_RELEASE_MODE === "true";
  const required = [gate.envVar, ...(gate.alsoRequire ?? [])];
  const missing = required.filter((name) => !process.env[name]);

  if (missing.length === 0) {
    return;
  }
  const reason = `${gate.provider} credential(s) missing: ${missing.join(", ")}`;

  if (releaseMode) {
    // Throw at describe-load time. Playwright will surface this as a
    // test failure for every test in the describe block, which is
    // exactly the loud failure release sign-off needs.
    throw new Error(
      `[CASEOPS_RELEASE_MODE=true] ${reason}. ` +
        `Provision the missing env var(s) before running release E2E.`,
    );
  }

  test.skip(true, `${reason}; provider-gated for UAT/release sign-off only.`);
}
