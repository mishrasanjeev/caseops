"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import { forwardRef } from "react";
import type { ComponentPropsWithoutRef, ElementRef } from "react";

import { cn } from "@/lib/cn";

export const Label = forwardRef<
  ElementRef<typeof LabelPrimitive.Root>,
  ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(function Label({ className, ...props }, ref) {
  return (
    <LabelPrimitive.Root
      ref={ref}
      className={cn(
        "text-sm font-medium leading-none text-[var(--color-ink-2)] peer-disabled:cursor-not-allowed peer-disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
});
