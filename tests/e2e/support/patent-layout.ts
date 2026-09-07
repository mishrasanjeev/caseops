import { expect, type Page } from "@playwright/test";

export async function assertPatentControlsFit(page: Page) {
  await expect.poll(() => page.locator("main").evaluate((main) =>
    Array.from(main.querySelectorAll("input, textarea, select, button, a")).flatMap((element) => {
      const rect = element.getBoundingClientRect();
      if (!rect.width && !rect.height) return [];
      const target = element.matches('input[type="checkbox"], input[type="radio"]')
        ? element.closest("label") ?? element : element;
      const box = target.getBoundingClientRect();
      const minimum = element.matches('textarea, select, input:not([type="checkbox"]):not([type="radio"])') ? 96 : 24;
      return rect.width <= 0 || box.width < minimum || box.left < -1 || box.right > innerWidth + 1
        ? [element.outerHTML.slice(0, 220)] : [];
    }),
  )).toEqual([]);
  await expect.poll(() => page.locator('main ul[aria-label="Recorded patent relationships"] > li, main ul[aria-label="Recorded patent parties"] > li').evaluateAll((items) =>
    items.flatMap((item) => {
      const title = item.querySelector("h3, a");
      if (!title) return ["Patent record title is missing"];
      const box = title.getBoundingClientRect();
      const minimum = Math.min(192, item.getBoundingClientRect().width);
      const overlap = Array.from(item.querySelectorAll("button")).some((button) => {
        const action = button.getBoundingClientRect();
        return box.left < action.right && box.right > action.left && box.top < action.bottom && box.bottom > action.top;
      });
      return box.width < minimum - 1 || overlap ? [title.textContent] : [];
    }),
  )).toEqual([]);
}
