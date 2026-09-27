import { expect, type APIResponse } from "@playwright/test";

export const noPaidProviderHeaders = {
  "X-CaseOps-Automated-Test": "no-paid-providers",
} as const;

/**
 * Opt-in for automated verification of a provider search that must be observed
 * in production. The API answers it from a checked-in verification fixture's
 * stored lookup only when the 18:00 IST scheduled job retrieved it within the
 * last 24 hours, the hashes verify and no later answer superseded it; otherwise
 * it refuses with a typed `replay.status` and makes no provider request. Human
 * requests are never replayed.
 */
export const verifiedFreshReplayHeaders = {
  ...noPaidProviderHeaders,
  "X-CaseOps-Provider-Replay": "verified-fresh",
} as const;

export type VerifiedFreshReplay = {
  status: "served";
  fixture_key: string;
  provider_call_performed: false;
  evidence_captured_at: string;
  evidence_age_seconds: number;
  max_age_seconds: number;
  snapshot_sha256: string;
};

const DAY_MS = 86_400_000;
// Runner and API clocks may disagree slightly; the API enforces the exact bound.
const CLOCK_SKEW_MS = 120_000;

/** Require a replayed answer and prove its evidence is fresh on this runner's clock too. */
export async function expectVerifiedFreshReplay<T extends object>(
  response: APIResponse,
  label: string,
): Promise<T & { replay: VerifiedFreshReplay }> {
  const text = await response.text();
  expect(response.status(), `${label}: ${text}`).toBe(200);
  const body = JSON.parse(text) as T & { replay?: VerifiedFreshReplay | null };
  const replay = body.replay;
  expect(replay, `${label}: no replay metadata: ${text}`).toBeTruthy();
  expect(replay!.status, `${label}: ${text}`).toBe("served");
  expect(replay!.provider_call_performed).toBe(false);
  expect(replay!.max_age_seconds).toBe(DAY_MS / 1000);
  expect(replay!.evidence_age_seconds).toBeGreaterThanOrEqual(0);
  expect(replay!.evidence_age_seconds).toBeLessThanOrEqual(DAY_MS / 1000);
  expect(replay!.snapshot_sha256).toMatch(/^[0-9a-f]{64}$/);
  const age = Date.now() - Date.parse(replay!.evidence_captured_at);
  expect(age, `${label}: evidence captured at ${replay!.evidence_captured_at}`).toBeLessThanOrEqual(
    DAY_MS + CLOCK_SKEW_MS,
  );
  return body as T & { replay: VerifiedFreshReplay };
}

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
