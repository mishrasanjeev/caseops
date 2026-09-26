import type { Page } from "@playwright/test";

/**
 * Product-wide form layout guard (2026-09-26, BUG-034).
 *
 * A field squeezed by a grid or flex parent can keep its DOM node while losing
 * its usable width; the Tasks form did exactly that when two cards shared the
 * xl viewport. Report every visible form control that is too narrow to use,
 * every pair of sibling fields that overlap, every field label whose own text
 * is clipped, and every control that escapes the viewport outside a horizontal
 * scroller. The caller asserts an empty list after the page has settled; never
 * poll this towards empty, because a loading state has no fields at all.
 */
export async function collectFormLayoutOffenders(page: Page): Promise<string[]> {
  await page.evaluate(() => document.fonts.ready);
  return page.locator("main").evaluate((main) => {
    const describe = (element: Element) =>
      `${element.tagName.toLowerCase()}${element.getAttribute("type") ? `[type=${element.getAttribute("type")}]` : ""}` +
      ` "${(element.closest("label")?.textContent ?? element.getAttribute("aria-label") ?? element.getAttribute("name") ?? "").trim().slice(0, 60)}"`;
    const visible = (element: Element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };
    const insideHorizontalScroller = (element: Element) => {
      for (let node = element.parentElement; node && node !== main.parentElement; node = node.parentElement) {
        const overflowX = getComputedStyle(node).overflowX;
        if ((overflowX === "auto" || overflowX === "scroll") && node.scrollWidth > node.clientWidth + 1) {
          return true;
        }
      }
      return false;
    };
    const offenders: string[] = [];
    const textLike = Array.from(
      main.querySelectorAll(
        'select, textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="file"]):not([type="range"]):not([type="color"])',
      ),
    ).filter(visible);
    for (const control of textLike) {
      const box = control.getBoundingClientRect();
      if (box.width < 96) offenders.push(`narrow control ${Math.round(box.width)}px: ${describe(control)}`);
      if ((box.left < -1 || box.right > innerWidth + 1) && !insideHorizontalScroller(control)) {
        offenders.push(`control outside viewport: ${describe(control)}`);
      }
    }
    // Field wrappers: a <label> (or element with a label child) that owns one control.
    const fields = Array.from(main.querySelectorAll("label")).filter(
      (label) => visible(label) && label.querySelector("input, select, textarea"),
    );
    for (const field of fields) {
      const caption = field.querySelector(":scope > span, :scope > div:first-child");
      if (caption && caption.scrollWidth > caption.clientWidth + 1 && getComputedStyle(caption).overflow !== "hidden") {
        offenders.push(`clipped label text: ${describe(field.querySelector("input, select, textarea")!)}`);
      }
    }
    const byParent = new Map<Element, Element[]>();
    for (const field of fields) {
      const parent = field.parentElement;
      if (!parent) continue;
      byParent.set(parent, [...(byParent.get(parent) ?? []), field]);
    }
    for (const siblings of byParent.values()) {
      for (let i = 0; i < siblings.length; i += 1) {
        for (let j = i + 1; j < siblings.length; j += 1) {
          const a = siblings[i].getBoundingClientRect();
          const b = siblings[j].getBoundingClientRect();
          const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (overlapX > 2 && overlapY > 2) {
            offenders.push(
              `overlapping fields: ${describe(siblings[i].querySelector("input, select, textarea")!)} / ` +
                describe(siblings[j].querySelector("input, select, textarea")!),
            );
          }
        }
      }
    }
    return offenders;
  });
}
