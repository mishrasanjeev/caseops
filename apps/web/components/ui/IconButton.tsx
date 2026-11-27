"use client";

import type { ComponentProps, ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";

type ButtonProps = ComponentProps<typeof Button>;
// Distribute over the button and link variants so neither loses its own props.
type WithoutName<T> = T extends unknown ? Omit<T, "children" | "aria-label" | "title"> : never;

/**
 * A `Button` (or link, with `href`) whose only visible content is an icon.
 *
 * `label` is required by the type and is both the accessible name and the
 * tooltip shown on hover and keyboard focus. `aria-label` and `title` are
 * not accepted, so a second, drifting name cannot be supplied.
 */
export type IconButtonProps = WithoutName<ButtonProps> & {
  label: string;
  // JSX never checks unknown hyphenated attributes, so refuse this one by name.
  "aria-label"?: never;
  children: ReactNode;
  tooltipSide?: "top" | "right" | "bottom" | "left";
};

export function IconButton({ label, children, tooltipSide, ...props }: IconButtonProps) {
  return (
    <Tooltip label={label} side={tooltipSide}>
      <Button {...(props as ButtonProps)}>{children}</Button>
    </Tooltip>
  );
}
