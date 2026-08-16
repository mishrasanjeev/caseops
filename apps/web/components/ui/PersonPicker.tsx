"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Input } from "@/components/ui/Input";
import { listEmployees, type EmployeeRecord } from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

/**
 * Choose a colleague by name.
 *
 * Several workflows asked the user to type a membership UUID into a text box.
 * Nobody knows their colleague's UUID, so those controls could only be operated
 * by someone reading the database — which is to say, not by a lawyer. This is
 * the house pattern for naming a person.
 *
 * It is a filter over a native `<select>` rather than a combobox: the list is a
 * firm's staff, so it is tens of entries, not thousands, and a native listbox
 * keeps keyboard and screen-reader behaviour that a custom widget has to
 * re-earn. `.impeccable.md` requires a keyboard path for every primary action.
 */

export type PersonPickerProps = {
  id: string;
  value: string;
  onChange: (membershipId: string) => void;
  /** Omit people who cannot be a valid answer, e.g. the person being replaced. */
  excludeMembershipIds?: string[];
  /** Shown when nothing is chosen yet. */
  placeholder?: string;
  disabled?: boolean;
  /** Only active staff by default: inactive people cannot take on work. */
  includeInactive?: boolean;
  className?: string;
};

export function personLabel(employee: EmployeeRecord): string {
  const qualifier = employee.designation || employee.department || employee.email;
  return qualifier ? `${employee.full_name} — ${qualifier}` : employee.full_name;
}

export function PersonPicker({
  id,
  value,
  onChange,
  excludeMembershipIds = [],
  placeholder = "Select a colleague…",
  disabled = false,
  includeInactive = false,
  className,
}: PersonPickerProps) {
  const [filter, setFilter] = useState("");

  const employees = useQuery({
    queryKey: ["employees", "person-picker", includeInactive],
    queryFn: () => listEmployees(includeInactive ? undefined : { status: "active" }),
  });

  const options = useMemo(() => {
    const excluded = new Set(excludeMembershipIds.filter(Boolean));
    const rows = (employees.data?.employees ?? []).filter(
      (employee) => !excluded.has(employee.membership_id),
    );
    const needle = filter.trim().toLowerCase();
    const matching = needle
      ? rows.filter((employee) =>
          [employee.full_name, employee.email, employee.designation, employee.department]
            .filter(Boolean)
            .some((field) => String(field).toLowerCase().includes(needle)),
        )
      : rows;
    return [...matching].sort((a, b) => a.full_name.localeCompare(b.full_name));
  }, [employees.data, excludeMembershipIds, filter]);

  // A chosen person who is filtered out must still render, or the control would
  // silently appear to have lost the selection.
  const selected = (employees.data?.employees ?? []).find(
    (employee) => employee.membership_id === value,
  );
  const selectedIsHidden = Boolean(
    selected && !options.some((employee) => employee.membership_id === value),
  );

  if (employees.isError) {
    return (
      <p className="text-sm text-[var(--color-mute)]">
        The staff list could not be loaded, so a colleague cannot be chosen here yet.
      </p>
    );
  }

  const showFilter = (employees.data?.employees ?? []).length > 8;

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      {showFilter ? (
        <Input
          aria-label="Filter colleagues by name"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by name, role or team…"
          disabled={disabled || employees.isLoading}
        />
      ) : null}
      <select
        id={id}
        value={value}
        disabled={disabled || employees.isLoading}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="">{employees.isLoading ? "Loading colleagues…" : placeholder}</option>
        {selectedIsHidden && selected ? (
          <option value={selected.membership_id}>{personLabel(selected)}</option>
        ) : null}
        {options.map((employee) => (
          <option key={employee.membership_id} value={employee.membership_id}>
            {personLabel(employee)}
          </option>
        ))}
      </select>
      {!employees.isLoading && options.length === 0 ? (
        <p className="text-sm text-[var(--color-mute)]">
          {filter.trim()
            ? "No colleague matches that filter."
            : "No other colleague is available to choose."}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Render a membership id as the person's name.
 *
 * A bare UUID on screen tells a lawyer nothing about who holds their deadline.
 * While the staff list is loading, or if the person has since been removed, the
 * id is shown rather than a blank — an unresolved reference is still more
 * honest than an empty space where a name should be.
 */
export function PersonName({
  membershipId,
  fallback,
}: {
  membershipId: string | null | undefined;
  fallback?: string;
}) {
  const employees = useQuery({
    queryKey: ["employees", "person-picker", false],
    queryFn: () => listEmployees({ status: "active" }),
  });

  if (!membershipId) return <>{fallback ?? "Unassigned"}</>;
  const match = (employees.data?.employees ?? []).find(
    (employee) => employee.membership_id === membershipId,
  );
  if (!match) return <span className="break-all">{membershipId}</span>;
  return <>{match.full_name}</>;
}
