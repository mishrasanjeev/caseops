import { expect, test } from "@playwright/test";

const legalOwner = "Orchestrum Technologies LLP";
const inventorOwner = "Sanjeev Kumar";
const ownerEmails = ["sanjeev@orchestrum.in", "mishra.sanjeev@gmail.com"];

test.describe("CaseOps product ownership", () => {
  test("the landing page states the legal owner and inventor/owner", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText(`Owned by ${legalOwner} · Inventor/Owner: ${inventorOwner}`, {
        exact: true,
      }),
    ).toBeVisible();

    const notice = page.getByRole("complementary", {
      name: "CaseOps product ownership",
    });
    await expect(notice).toContainText(`CaseOps is owned by ${legalOwner}`);
    await expect(notice).toContainText(`Inventor/Owner: ${inventorOwner}`);
    for (const email of ownerEmails) {
      await expect(notice.getByRole("link", { name: email })).toHaveAttribute(
        "href",
        `mailto:${email}`,
      );
    }
  });

  test("the ownership notice is inherited by every major route family", async ({ page }) => {
    for (const path of [
      "/pricing",
      "/law-firms",
      "/general-counsels",
      "/solo-lawyers",
      "/guide",
      "/sign-in",
      "/account/forgot-password",
      "/portal/sign-in",
      "/app",
    ]) {
      await page.goto(path);
      const notice = page.getByRole("complementary", {
        name: "CaseOps product ownership",
      });
      await expect(notice, `ownership notice on ${path}`).toContainText(legalOwner);
      await expect(notice, `inventor/owner notice on ${path}`).toContainText(inventorOwner);
    }
  });

  test("metadata, structured data, and crawler documents publish the same identity", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.locator('meta[name="product-owner"]')).toHaveAttribute(
      "content",
      legalOwner,
    );
    await expect(page.locator('meta[name="inventor-owner"]')).toHaveAttribute(
      "content",
      inventorOwner,
    );

    const documents = (await page.locator('script[type="application/ld+json"]').allTextContents())
      .map((value) => JSON.parse(value) as Record<string, unknown>);
    const organization = documents.find((value) => value["@type"] === "Organization");
    const software = documents.find((value) => value["@type"] === "SoftwareApplication");
    expect(organization?.name).toBe(legalOwner);
    expect(software?.publisher).toMatchObject({ name: legalOwner });
    expect(software?.creator).toMatchObject({ name: inventorOwner });

    for (const path of ["/llms.txt", "/llms-full.txt"]) {
      const response = await page.request.get(path);
      expect(response.status()).toBe(200);
      const body = await response.text();
      expect(body).toContain(`Product owner: ${legalOwner}`);
      expect(body).toContain(`Inventor/Owner: ${inventorOwner}`);
      for (const email of ownerEmails) expect(body).toContain(email);
    }
  });
});
