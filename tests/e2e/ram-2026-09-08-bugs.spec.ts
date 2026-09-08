import { expect, test } from "@playwright/test";
import { apiBaseUrl as localApiBaseUrl } from "./support/env";
import { noPaidProviderHeaders } from "./support/cost-controls";

const apiBaseUrl = process.env.PROD_API_BASE_URL || localApiBaseUrl;

test("API slash correction preserves the caller origin and authentication boundary", async ({ request }) => {
  const response = await request.get(`${apiBaseUrl}/api/clients`, {
    headers: noPaidProviderHeaders, maxRedirects: 0,
  });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe("/api/clients/");
  const destination = new URL(response.headers().location, apiBaseUrl);
  expect(destination.origin).toBe(new URL(apiBaseUrl).origin);
  const canonical = await request.get(destination.toString(), {
    headers: noPaidProviderHeaders, maxRedirects: 0,
  });
  expect(canonical.status()).toBe(401);
  expect((await canonical.json()).status).toBe(401);
});
