import type { Page } from "@playwright/test";

/**
 * Product-wide form layout guard (2026-09-26, BUG-034).
 *
 * A field squeezed by a grid or flex parent can keep its DOM node while losing
 * its usable width; the Tasks form did exactly that when two cards shared the
 * xl viewport. Report every visible text-like control that is too narrow to
 * use, every native select narrower than its own selected option, every pair
 * of sibling fields that overlap, every field label whose text is clipped, and
 * every control that escapes the viewport outside a horizontal scroller. The
 * caller asserts an empty list after the page has settled; never poll this
 * towards empty, because a loading state has no fields at all.
 *
 * Skipped on purpose: `aria-hidden` controls and the visually-hidden native
 * fallbacks that custom dropdowns keep for form submission (1px, absolute).
 */
export async function collectFormLayoutOffenders(page: Page): Promise<string[]> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    // Entrance transitions move cards from off-screen; measure only at rest.
    await Promise.allSettled(document.getAnimations().map((animation) => animation.finished));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  return page.locator("main").evaluate((main) => {
    const describe = (element: Element) => {
      const input = element as HTMLInputElement;
      const label =
        element.closest("label")?.textContent?.trim() ||
        (element.id && main.querySelector(`label[for="${CSS.escape(element.id)}"]`)?.textContent?.trim()) ||
        element.getAttribute("aria-label") ||
        input.placeholder ||
        input.name ||
        element.id ||
        "";
      const rect = element.getBoundingClientRect();
      return (
        `${element.tagName.toLowerCase()}${input.type ? `[type=${input.type}]` : ""} "${label.slice(0, 60)}"` +
        ` at x=${Math.round(rect.left)} w=${Math.round(rect.width)}`
      );
    };
    const visible = (element: Element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (style.visibility === "hidden" || style.display === "none" || rect.width <= 0 || rect.height <= 0) {
        return false;
      }
      if (element.getAttribute("aria-hidden") === "true") return false;
      // Visually-hidden pattern: a 1px absolutely positioned or clipped control.
      if ((rect.width <= 2 || rect.height <= 2) && (style.position === "absolute" || style.clipPath !== "none" || style.opacity === "0")) {
        return false;
      }
      return true;
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
    const canvas = document.createElement("canvas").getContext("2d");
    const selectMinimumWidth = (select: HTMLSelectElement) => {
      const style = getComputedStyle(select);
      const text = select.options[select.selectedIndex]?.text ?? "";
      let textWidth = 0;
      if (canvas) {
        canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        textWidth = canvas.measureText(text).width;
      }
      const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      // Selected option, padding and the native disclosure arrow must all fit.
      return Math.max(48, textWidth + padding + 24);
    };
    const offenders: string[] = [];
    const controls = Array.from(
      main.querySelectorAll(
        'select, textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="file"]):not([type="range"]):not([type="color"])',
      ),
    ).filter(visible);
    for (const control of controls) {
      const box = control.getBoundingClientRect();
      if (control.tagName === "SELECT") {
        const minimum = selectMinimumWidth(control as HTMLSelectElement);
        if (box.width < minimum - 1) offenders.push(`select narrower than its option (${Math.round(box.width)} < ${Math.round(minimum)}px): ${describe(control)}`);
      } else if (box.width < 96) {
        offenders.push(`narrow control ${Math.round(box.width)}px: ${describe(control)}`);
      }
      if ((box.left < -1 || box.right > innerWidth + 1) && !insideHorizontalScroller(control)) {
        offenders.push(`control outside viewport (innerWidth=${innerWidth}): ${describe(control)}`);
      }
    }
    // Field wrappers: a <label> that owns one visible control.
    const fields = Array.from(main.querySelectorAll("label")).filter((label) => {
      const control = label.querySelector("input, select, textarea");
      return control !== null && visible(label) && visible(control);
    });
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
