import { expect, type APIResponse } from "@playwright/test";

export const noPaidProviderHeaders = {
  "X-CaseOps-Automated-Test": "no-paid-providers",
} as const;

/**
 * The API answers a blocked paid-provider call with an RFC 7807 body whose
 * machine-readable `code` sits at the top level (`problem_details.py` flattens
 * a dict `detail`). Specs must assert that exact shape through this helper; a
 * production-only branch reading `detail.code` passed nowhere before it failed
 * in production on 2026-09-27.
 */
export async function expectPaidProviderBlocked(response: APIResponse, label = "paid-provider boundary") {
  const text = await response.text();
  expect(response.status(), `${label}: ${text}`).toBe(409);
  const body = JSON.parse(text) as { code?: string; reason?: string; detail?: string };
  expect(body.code, `${label}: ${text}`).toBe("paid_provider_blocked_for_test");
  expect(body.detail ?? "", `${label}: ${text}`).toMatch(/no external request was made/i);
  return body;
}
