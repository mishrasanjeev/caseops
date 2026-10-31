"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { forwardRef } from "react";
import type { ComponentPropsWithoutRef, ElementRef } from "react";

import { cn } from "@/lib/cn";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;
export const SelectGroup = SelectPrimitive.Group;

export const SelectTrigger = forwardRef<
  ElementRef<typeof SelectPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(function SelectTrigger({ className, children, ...props }, ref) {
  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(
        "flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-[var(--color-line)] bg-white px-3 text-left text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-[var(--color-mute-2)]",
        // The selected caption is record data of any length. Keep it on one
        // line inside the 40px box instead of wrapping over neighbouring fields.
        "[&>span]:min-w-0 [&>span]:flex-1 [&>span]:truncate [&>span]:text-left",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="h-4 w-4 shrink-0 opacity-60" aria-hidden />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
});

const scrollButtonClass =
  "flex h-6 shrink-0 cursor-default items-center justify-center bg-white text-[var(--color-mute)]";

export const SelectContent = forwardRef<
  ElementRef<typeof SelectPrimitive.Content>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(function SelectContent(
  { className, children, position = "popper", sideOffset, ...props },
  ref,
) {
  const popper = position === "popper";
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        ref={ref}
        position={position}
        // The gap belongs to floating-ui so the available-height bound below
        // already accounts for the space between the trigger and the list.
        sideOffset={popper ? (sideOffset ?? 4) : sideOffset}
        className={cn(
          "relative z-50 overflow-hidden rounded-md border border-[var(--color-line)] bg-white shadow-[var(--shadow-raised)]",
          // Radix measures the room beside the trigger and publishes it as
          // CSS variables; it does not apply it. Without these bounds a long
          // list grows past the viewport and its off-screen options cannot be
          // reached while Radix holds the page scroll lock.
          popper
            ? "min-w-[var(--radix-select-trigger-width)] max-h-[min(var(--radix-select-content-available-height),22rem)] max-w-[min(var(--radix-select-content-available-width),32rem)]"
            : "min-w-[8rem]",
          className,
        )}
        {...props}
      >
        {/* Radix hides the viewport scrollbar; these are the scroll cue. */}
        <SelectPrimitive.ScrollUpButton className={scrollButtonClass}>
          <ChevronUp className="h-4 w-4" aria-hidden />
        </SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className={scrollButtonClass}>
          <ChevronDown className="h-4 w-4" aria-hidden />
        </SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
});

export const SelectItem = forwardRef<
  ElementRef<typeof SelectPrimitive.Item>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(function SelectItem({ className, children, ...props }, ref) {
  return (
    <SelectPrimitive.Item
      ref={ref}
      className={cn(
        // Labels are record captions: wrap them, including code-like strings
        // without spaces, rather than widening the list past its bound.
        "relative flex w-full min-w-0 cursor-default select-none items-start whitespace-normal rounded-sm py-1.5 pl-8 pr-2 text-sm leading-5 text-[var(--color-ink-2)] outline-none [overflow-wrap:anywhere] focus:bg-[var(--color-bg-2)] focus:text-[var(--color-ink)] data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <span className="absolute left-2 top-2 flex h-3.5 w-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="h-4 w-4" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText className="min-w-0">{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
});

/**
 * A non-selectable row for an empty option list. It is exposed as an
 * unavailable option so assistive technology reads it inside the list, but it
 * is not a Radix item: it carries no value and keyboard selection skips it.
 * Callers should still disable the trigger when nothing can be chosen.
 */
export const SelectEmpty = forwardRef<HTMLDivElement, ComponentPropsWithoutRef<"div">>(
  function SelectEmpty({ className, children, ...props }, ref) {
    return (
      <div
        ref={ref}
        role="option"
        aria-disabled="true"
        aria-selected="false"
        data-select-empty=""
        className={cn(
          "cursor-default select-none whitespace-normal px-2 py-1.5 text-sm leading-5 text-[var(--color-mute)] [overflow-wrap:anywhere]",
          className,
        )}
        {...props}
      >
        {children}
      </div>
    );
  },
);
