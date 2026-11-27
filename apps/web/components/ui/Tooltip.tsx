"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { useEffect, type FocusEvent, type ReactElement } from "react";

// True while the most recent input was a Tab key press. Focus that arrives
// any other way (a dialog's initial focus, focus restored after Escape, a
// script) must not open a tooltip: an open tooltip is the top dismissable
// layer, so it would take the next Escape away from the dialog around it.
let tabNavigation = false;
let listening = false;

function listenForTabNavigation() {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("keydown", (event) => { tabNavigation = event.key === "Tab"; }, true);
  document.addEventListener("pointerdown", () => { tabNavigation = false; }, true);
}

/**
 * Names an icon-only control and explains it on hover and keyboard focus.
 *
 * The label becomes the child's accessible name (unless the child already
 * sets `aria-label`) and the visible tooltip text, so the two cannot drift.
 * A native `title` is not enough: it never appears on keyboard focus, and
 * screen readers announce it inconsistently (Nov 27 workbook, row 10).
 * `lib/icon-only-controls.test.ts` fails any icon-only button or link that
 * is neither an `IconButton` nor wrapped in this component.
 */
export function Tooltip({
  label,
  children,
  side = "top",
  onFocus,
  ...slotProps
}: {
  label: string;
  /** Exactly one focusable element: a button or link. */
  children: ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  // A parent `asChild` trigger (DialogTrigger, DropdownMenu.Trigger) hands its
  // props and ref to this component; they must reach the button unchanged.
  [slotProp: string]: unknown;
}) {
  useEffect(listenForTabNavigation, []);
  return (
    <TooltipPrimitive.Provider delayDuration={300} skipDelayDuration={200}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger
          {...slotProps}
          asChild
          aria-label={label}
          onFocus={(event: FocusEvent<HTMLElement>) => {
            onFocus?.(event);
            // Radix skips its own open-on-focus when the event is prevented.
            if (!tabNavigation) event.preventDefault();
          }}
        >
          {children}
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            sideOffset={6}
            collisionPadding={8}
            className="z-[100] max-w-xs rounded-[var(--radius-sm)] bg-[var(--color-ink)] px-2 py-1 text-xs font-medium text-white shadow-[var(--shadow-soft)]"
          >
            {label}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
