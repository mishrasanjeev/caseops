"use client";

import { Label } from "@/components/ui/Label";

/**
 * A record choice that is never a dead end.
 *
 * Options come from the caller's copy of the write validator: an option the
 * write would reject is listed disabled with its reason, so the user sees why
 * a record cannot be chosen. When nothing can be chosen the select is disabled
 * and `emptyText` says what is missing and where in the product to create it,
 * instead of an enabled select that offers only its placeholder. Nothing is
 * ever selected on the user's behalf.
 */
export type ExplainedOption = { value: string; label: string; reason?: string | null };

export function enabledChoice(options: readonly ExplainedOption[], value: string): string {
  return options.some((option) => option.value === value && !option.reason) ? value : "";
}

export function ExplainedSelect({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
  emptyText,
  className,
  testId,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly ExplainedOption[];
  placeholder: string;
  emptyText: string;
  className: string;
  testId?: string;
}) {
  const choosable = options.filter((option) => !option.reason).length;
  const reasonId = `${id}-reason`;
  const selected = enabledChoice(options, value);
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        data-testid={testId}
        className={className}
        value={selected}
        disabled={choosable === 0}
        aria-describedby={choosable === 0 ? reasonId : undefined}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" disabled>{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={Boolean(option.reason)}>
            {option.reason ? `${option.label} — ${option.reason}` : option.label}
          </option>
        ))}
      </select>
      {choosable === 0 ? (
        <p id={reasonId} className="min-w-0 break-words text-xs text-[var(--color-mute)]">{emptyText}</p>
      ) : null}
    </div>
  );
}
