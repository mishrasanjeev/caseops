// Inline mirrors of the server validators in
// apps/api/src/caseops_api/schemas/microsoft365.py. The server stays the
// source of truth (it rejects with 422); these only show the error next to
// the field before Save. microsoft365-setup.test.ts pins the same vectors as
// tests/test_microsoft365_setup_guidance_20261127.py.

const GUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const DOMAIN =
  /^(?=.{4,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$/;
const MULTI_TENANT_MODES = new Set(["common", "organizations", "consumers"]);

export function microsoft365TenantIdError(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (MULTI_TENANT_MODES.has(value.toLowerCase())) {
    return `"${value}" is a sign-in mode, not your directory. Enter the Directory (tenant) ID from your app registration's Overview page, or a verified domain such as yourfirm.onmicrosoft.com.`;
  }
  if (GUID.test(value) || DOMAIN.test(value)) return null;
  return "Enter a GUID such as 72f988bf-86f1-41af-91ab-2d7cd011db47, or a verified domain such as yourfirm.onmicrosoft.com.";
}

export function microsoft365ClientIdError(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  return GUID.test(value)
    ? null
    : "The Application (client) ID is a GUID such as 00000000-1111-2222-3333-444444444444.";
}
