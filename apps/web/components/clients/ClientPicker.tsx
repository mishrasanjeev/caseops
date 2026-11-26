"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useId, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { apiErrorMessage } from "@/lib/api/config";
import { listClients, type ClientRecord } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { cn } from "@/lib/cn";

/**
 * Choose one existing client to link to a Matter.
 *
 * GET /api/clients/ returns every client in the tenant in one response (it
 * has no paging; `next_cursor` is always null), so the search below covers
 * the whole client book, not a first page. Only active clients are offered:
 * the link API refuses an archived client (409 `matter_client_inactive`), and
 * the picker never offers a value the API refuses. `disabledReason` lists a
 * client the caller's write would refuse (for example one already linked),
 * disabled, with the reason.
 *
 * Same record-picker pattern as MatterPicker: a search box over a native
 * select so phones get the native sheet, with the full caption of the chosen
 * client shown under the field.
 */
export type ClientPickerProps = {
  value: string;
  onChange: (clientId: string, client: ClientRecord | null) => void;
  id?: string;
  label?: string;
  disabledReason?: (client: ClientRecord) => string | null;
  emptyOptionLabel?: string;
  maxOptions?: number;
  disabled?: boolean;
  enabled?: boolean;
  className?: string;
};

export function clientCaption(client: Pick<ClientRecord, "name" | "client_type" | "city">): string {
  return [client.name, client.client_type, client.city].filter(Boolean).join(" · ");
}

function searchText(client: ClientRecord): string {
  return [
    client.name,
    client.primary_contact_name,
    client.primary_contact_email,
    client.pan,
    client.gstin,
    client.city,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function ClientPicker({
  value,
  onChange,
  id,
  label = "Client",
  disabledReason,
  emptyOptionLabel,
  maxOptions = 50,
  disabled,
  enabled = true,
  className,
}: ClientPickerProps) {
  const generatedId = useId();
  const selectId = id ?? `client-picker-${generatedId.replace(/:/g, "")}`;
  const searchId = `${selectId}-search`;
  const statusId = `${selectId}-status`;
  const canCreateClient = useCapability("clients:create");
  const [search, setSearch] = useState("");

  const clients = useQuery({
    queryKey: ["clients", "list"],
    queryFn: () => listClients(),
    enabled,
  });
  const all = useMemo(() => clients.data?.clients ?? [], [clients.data]);
  const active = useMemo(() => all.filter((client) => client.is_active), [all]);
  const archivedCount = all.length - active.length;
  const needle = search.trim().toLowerCase();
  const matches = needle ? active.filter((client) => searchText(client).includes(needle)) : active;
  const shown = matches.slice(0, maxOptions);
  const selected = value ? active.find((client) => client.id === value) : undefined;
  const rows = selected && !shown.some((client) => client.id === selected.id) ? [selected, ...shown] : shown;
  const options = [
    emptyOptionLabel
      ? { value: "", label: emptyOptionLabel, disabled: false }
      : { value: "", label: clients.isPending ? "Loading clients…" : "Select a client", disabled: true },
    ...rows.map((client) => {
      const reason = disabledReason?.(client) ?? null;
      return {
        value: client.id,
        label: reason ? `${clientCaption(client)} — ${reason}` : clientCaption(client),
        disabled: Boolean(reason) && client.id !== value,
      };
    }),
  ];
  const archivedNote =
    archivedCount > 0
      ? ` ${archivedCount} archived ${archivedCount === 1 ? "client is" : "clients are"} not listed; restore one to link it.`
      : "";

  let statusText: string;
  if (clients.isPending) statusText = "Loading clients…";
  else if (active.length === 0) statusText = `No active clients yet.${archivedNote}`;
  else if (matches.length === 0) statusText = `No active client matches “${search.trim()}”.${archivedNote}`;
  else if (matches.length > shown.length)
    statusText = `Showing ${shown.length} of ${matches.length} matching clients — refine the search.${archivedNote}`;
  else
    statusText = `${matches.length} ${matches.length === 1 ? "client" : "clients"}${needle ? ` matching “${search.trim()}”` : ""}.${archivedNote}`;

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)} data-testid="client-picker">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={searchId}>Search clients</Label>
        <Input
          id={searchId}
          type="search"
          value={search}
          disabled={disabled}
          autoComplete="off"
          placeholder="Name, contact, PAN, GSTIN or city"
          aria-controls={selectId}
          onChange={(event) => setSearch(event.target.value)}
          onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
            // Enter filters; it never submits the surrounding form.
            if (event.key === "Enter") event.preventDefault();
          }}
        />
      </div>
      <RecordSelect
        id={selectId}
        label={label}
        value={value}
        options={options}
        disabled={disabled || clients.isPending || clients.isError}
        aria-describedby={statusId}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next, active.find((client) => client.id === next) ?? null);
        }}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] disabled:cursor-not-allowed disabled:opacity-60"
      />
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
        {clients.isError ? (
          <>
            <span id={statusId} role="alert" className="min-w-0 break-words text-[var(--color-danger-500)]">
              Clients could not be loaded: {apiErrorMessage(clients.error, "Request failed.")}
            </span>
            <Button type="button" size="sm" variant="outline" onClick={() => clients.refetch()}>
              Retry
            </Button>
          </>
        ) : (
          <>
            <span id={statusId} role="status" className="min-w-0 break-words">
              {statusText}
            </span>
            {!clients.isPending && active.length === 0 && canCreateClient ? (
              <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href="/app/clients">
                Add a client
              </Link>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
