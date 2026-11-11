import { expect, type Locator, type Page } from "@playwright/test";

export async function openStatuteOptions(page: Page, field: "act" | "section") {
  const trigger = page.getByTestId(`matter-statute-${field}-select`);
  await expect(trigger).toHaveAccessibleName(field === "act" ? "Act" : "Section");
  await expect(trigger).toBeEnabled();
  await trigger.click();
  const list = page.getByRole("listbox");
  await expect(list).toBeVisible();
  return list;
}

export function statuteOption(list: Locator, id: string) {
  return list.locator(`[data-value="${id}"]`);
}
