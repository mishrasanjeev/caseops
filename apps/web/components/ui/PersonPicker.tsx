"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/Input";
import { listCompanyUsers, type CompanyUserRecord } from "@/lib/api/endpoints";
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
  className?: string;
};

export function personLabel(user: CompanyUserRecord): string {
  // Email is part of every option, rather than a fallback, so two colleagues
  // with the same name or role are always distinguishable.
  return `${user.full_name} — ${user.email}`;
}

function unavailableSelectionLabel(
  membershipId: string,
  user: CompanyUserRecord | undefined,
): string {
  if (user) {
    return `${personLabel(user)} — current; unavailable for new assignments`;
  }
  return `Current selection ${membershipId} — unavailable for new assignments`;
}

export function PersonPicker({
  id,
  value,
  onChange,
  excludeMembershipIds = [],
  placeholder = "Select a colleague…",
  disabled = false,
  className,
}: PersonPickerProps) {
  const [filter, setFilter] = useState("");

  const companyUsers = useQuery({
    queryKey: ["company-users"],
    queryFn: () => listCompanyUsers(),
  });

  const excluded = useMemo(
    () => new Set(excludeMembershipIds.filter(Boolean)),
    [excludeMembershipIds],
  );
  const selectableUsers = useMemo(() => {
    return (companyUsers.data?.users ?? [])
      .filter(
        (user) =>
          user.membership_active &&
          user.user_active &&
          !excluded.has(user.membership_id),
      )
      .sort(
        (a, b) =>
          a.full_name.localeCompare(b.full_name) || a.email.localeCompare(b.email),
      );
  }, [companyUsers.data?.users, excluded]);

  const options = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return selectableUsers;
    return selectableUsers.filter((user) =>
      [user.full_name, user.email, user.role].some((field) =>
        field.toLowerCase().includes(needle),
      ),
    );
  }, [filter, selectableUsers]);

  // Keep a valid selection visible when only the text filter hides it.
  const selected = selectableUsers.find((user) => user.membership_id === value);
  const selectedIsFilterHidden = Boolean(
    filter.trim() && selected && !options.some((user) => user.membership_id === value),
  );
  const selectedDirectoryUser = (companyUsers.data?.users ?? []).find(
    (user) => user.membership_id === value,
  );
  const selectionIsExplicitlyExcluded = Boolean(value && excluded.has(value));
  const preserveUnavailableSelection = Boolean(
    value && !selectionIsExplicitlyExcluded && !selected,
  );

  useEffect(() => {
    // An explicit exclusion is a caller-owned invariant (for example, backup
    // cannot equal primary), so it is the only directory state that may clear
    // a controlled value automatically. Missing or inactive entries can be a
    // valid historical relationship and are preserved until the user changes
    // the selection themselves.
    if (selectionIsExplicitlyExcluded) onChange("");
  }, [onChange, selectionIsExplicitlyExcluded]);

  const showFilter = selectableUsers.length > 8;

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      {companyUsers.isError ? (
        <p className="text-sm text-[var(--color-mute)]">
          The staff list could not be loaded, so a new colleague cannot be chosen here yet.
        </p>
      ) : null}
      {showFilter ? (
        <Input
          aria-label="Filter colleagues by name"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by name or email…"
          disabled={disabled || companyUsers.isLoading}
        />
      ) : null}
      <select
        id={id}
        value={selectionIsExplicitlyExcluded ? "" : value}
        disabled={disabled || companyUsers.isLoading || companyUsers.isError}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="">
          {companyUsers.isLoading
            ? "Loading colleagues…"
            : companyUsers.isError
              ? "Staff list unavailable"
              : placeholder}
        </option>
        {preserveUnavailableSelection ? (
          <option value={value} disabled>
            {unavailableSelectionLabel(value, selectedDirectoryUser)}
          </option>
        ) : null}
        {selectedIsFilterHidden && selected ? (
          <option value={selected.membership_id}>{personLabel(selected)}</option>
        ) : null}
        {options.map((user) => (
          <option key={user.membership_id} value={user.membership_id}>
            {personLabel(user)}
          </option>
        ))}
      </select>
      {!companyUsers.isLoading && !companyUsers.isError && options.length === 0 ? (
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
  const companyUsers = useQuery({
    queryKey: ["company-users"],
    queryFn: () => listCompanyUsers(),
  });

  if (!membershipId) return <>{fallback ?? "Unassigned"}</>;
  const match = (companyUsers.data?.users ?? []).find(
    (user) => user.membership_id === membershipId,
  );
  if (!match) return <span className="break-all">{membershipId}</span>;
  return <>{personLabel(match)}</>;
}
