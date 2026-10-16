"use client";

import { forwardRef, useId, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { ComponentPropsWithoutRef } from "react";

import { Label } from "@/components/ui/Label";
import { cn } from "@/lib/cn";

export type RecordSelectOption = Readonly<{ value: string; label: string; disabled?: boolean }>;

type RecordSelectProps = Omit<ComponentPropsWithoutRef<"select">, "children" | "value" | "defaultValue" | "multiple"> & {
  label: string;
  value: string;
  options: readonly RecordSelectOption[];
  fieldClassName?: string;
};

export const RecordSelect = forwardRef<HTMLSelectElement, RecordSelectProps>(function RecordSelect(
  { id, label, value, options, fieldClassName, "aria-describedby": callerDescription, ...props }, forwardedRef,
) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const descriptionId = `${selectId}-selected-description`;
  const select = useRef<HTMLSelectElement>(null);
  const selected = value ? options.find(option => option.value === value) : undefined;
  const descriptions = (callerDescription ?? "").split(/\s+/).filter(token => token && token !== descriptionId);
  if (selected) descriptions.push(descriptionId);

  useImperativeHandle(forwardedRef, () => select.current!, []);
  useLayoutEffect(() => {
    // React otherwise selects the first option for a controlled unmatched value.
    if (select.current && select.current.value !== value) select.current.value = value;
  });

  return (
    <div className={cn("block min-w-0 space-y-1.5", fieldClassName)}>
      <Label className="block break-words leading-snug" htmlFor={selectId}>{label}</Label>
      <select {...props} id={selectId} ref={select} value={value}
        aria-describedby={descriptions.join(" ") || undefined}>
        {options.map(option => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}
      </select>
      {selected ? (
        <p id={descriptionId} data-selected-option-value={selected.value}
          className="min-w-0 whitespace-normal break-all text-sm text-[var(--color-mute)]">
          {selected.label}
        </p>
      ) : null}
    </div>
  );
});
