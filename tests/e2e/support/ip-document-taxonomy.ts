import { expect, type APIRequestContext } from "@playwright/test";

type TaxonomyEntry = { key: string; is_active: boolean };

/**
 * Asserts the tenant's IP document taxonomy came from product provisioning.
 *
 * Journeys must not load the catalogue through the admin seed endpoint
 * (guarded by apps/web/lib/e2e-document-taxonomy-seed-guard.test.ts): a
 * fresh tenant receives it when the IP
 * workspace is configured or enabled, and an existing tenant through the
 * release backfill. If provisioning breaks, the journey fails here instead of
 * silently repairing the tenant it claims to test.
 */
export async function expectProvisionedDocumentTaxonomy(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string> | undefined,
  requiredKeys: readonly string[] = ["evidence"],
): Promise<string[]> {
  const response = await api.get(`${apiBase}/api/ip/document-taxonomy`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as { entries: TaxonomyEntry[] };
  const active = body.entries.filter(entry => entry.is_active).map(entry => entry.key);
  expect(active.length, "provisioned document classifications").toBeGreaterThan(0);
  for (const key of requiredKeys) {
    expect(active, `provisioned document classification '${key}'`).toContain(key);
  }
  return active;
}
