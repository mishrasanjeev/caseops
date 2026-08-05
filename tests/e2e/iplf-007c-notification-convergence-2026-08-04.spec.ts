import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "NotificationTrust123!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<string> {
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Notification Convergence LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Notification Operator",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  return email;
}

test("IPLF-UJ-11: self-test persists one safe in-app intent and mobile controls remain usable", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const slug = unique("iplf007c");
  const email = await bootstrap(api, slug);

  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: { company_slug: slug, email, password: PASSWORD },
  });
  expect(login.status()).toBe(200);
  const session = (await login.json()) as {
    access_token: string;
    company: unknown;
    user: unknown;
    membership: unknown;
    capabilities?: unknown;
  };
  await page.context().addCookies([
    {
      name: "caseops_session",
      value: session.access_token,
      url: apiBaseUrl,
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
  await page.addInitScript((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
  await page.setViewportSize({ width: 360, height: 800 });

  await page.goto("/app/admin/notifications");
  await expect(page.getByRole("heading", { name: "Notification delivery and recovery" })).toBeVisible();
  await expect(page.getByTestId("notification-self-test")).toBeVisible();

  const testResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/notification-preferences/test" &&
      response.request().method() === "POST",
  );
  await page.getByTestId("notification-self-test").click();
  const testResponse = await testResponsePromise;
  expect(testResponse.status()).toBe(200);
  const payload = (await testResponse.json()) as {
    intent: {
      id: string;
      channel: string;
      status: string;
      destination: string | null;
      destination_version: number;
    };
    message: string;
  };
  expect(payload.intent).toMatchObject({
    channel: "in_app",
    status: "delivered",
    destination: null,
    destination_version: 1,
  });
  expect(payload.message).toContain("without contacting an external provider");
  await expect(page.getByText(/without contacting an external provider/i)).toBeVisible();

  const adminResponse = await page.request.get(`${apiBaseUrl}/api/admin/notifications`);
  expect(adminResponse.status()).toBe(200);
  const adminPayload = (await adminResponse.json()) as {
    intents: Array<{ id: string; status: string; event_type: string }>;
    metrics: { delivered: number };
  };
  expect(adminPayload.intents).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        id: payload.intent.id,
        status: "delivered",
        event_type: "notification_test",
      }),
    ]),
  );
  expect(adminPayload.metrics.delivered).toBeGreaterThanOrEqual(1);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
