import { describe, expect, it } from "vitest";

import { microsoft365ClientIdError, microsoft365TenantIdError } from "@/lib/microsoft365-setup";

// Same vectors as apps/api/tests/test_microsoft365_setup_guidance_20261127.py:
// the inline error must appear exactly when the server would answer 422.
describe("Microsoft 365 setup inline validation (Nov 27 row 8)", () => {
  it.each(["common", "organizations", "Consumers"])("explains the sign-in mode %s", (value) => {
    expect(microsoft365TenantIdError(value)).toMatch(/sign-in mode/);
  });

  it.each(["graph-tenant-id", "72f988bf-86f1-41af-91ab", "https://login.microsoftonline.com/x"])(
    "rejects %s with the GUID guidance",
    (value) => {
      expect(microsoft365TenantIdError(value)).toMatch(/GUID/);
    },
  );

  it.each([
    "72f988bf-86f1-41af-91ab-2d7cd011db47",
    "72F988BF-86F1-41AF-91AB-2D7CD011DB47",
    "nova-legal.onmicrosoft.com",
    "novalegal.in",
    "",
  ])("accepts %s", (value) => {
    expect(microsoft365TenantIdError(value)).toBeNull();
  });

  it("requires a GUID application (client) ID", () => {
    expect(microsoft365ClientIdError("graph-client-id")).toMatch(/Application \(client\) ID/);
    expect(microsoft365ClientIdError("0b6f2a4e-1c3d-4e5f-8a9b-0c1d2e3f4a5b")).toBeNull();
  });
});
