"use client";

import Link from "next/link";
import { useMemo } from "react";

import { Button } from "@/components/ui/Button";
import { RecordSelect, type RecordSelectOption } from "@/components/ui/RecordSelect";
import { ApiError, apiErrorMessage } from "@/lib/api/config";
import type { WorkspaceResponse } from "@/lib/api/workspace-types";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

export type IpBillingLinkType = "invoice" | "invoice_line_item" | "time_entry";

const NOUN: Record<IpBillingLinkType, { one: string; many: string }> = {
  invoice: { one: "invoice", many: "invoices" },
  invoice_line_item: { one: "invoice line", many: "invoice lines" },
  time_entry: { one: "time entry", many: "time entries" },
};

function money(minor: number | null | undefined, currency: string | null | undefined): string | null {
  if (minor === null || minor === undefined) return null;
  return `${currency ?? ""} ${(minor / 100).toFixed(2)}`.trim();
}

function caption(parts: Array<string | null | undefined>): string {
  return parts.filter(Boolean).join(" · ");
}

/**
 * The records cost reconciliation can match for this link type: the docket
 * Matter's invoices, invoice lines, or time entries (the server checks the
 * same Matter, so nothing outside it is offered).
 */
export function billingRecordOptions(
  workspace: Pick<WorkspaceResponse, "invoices" | "time_entries">,
  linkType: IpBillingLinkType,
): RecordSelectOption[] {
  if (linkType === "invoice") {
    return workspace.invoices.map((invoice) => ({
      value: invoice.id,
      label: caption([invoice.invoice_number, invoice.status, money(invoice.total_amount_minor, invoice.currency)]),
    }));
  }
  if (linkType === "invoice_line_item") {
    return workspace.invoices.flatMap((invoice) =>
      (invoice.line_items ?? []).map((line) => ({
        value: line.id,
        label: caption([invoice.invoice_number, line.description, money(line.line_total_amount_minor, invoice.currency)]),
      })),
    );
  }
  return workspace.time_entries.map((entry) => ({
    value: entry.id,
    label: caption([
      entry.work_date,
      entry.description,
      `${entry.duration_minutes} min`,
      money(entry.total_amount_minor, entry.rate_currency),
    ]),
  }));
}

/**
 * Choose the Matter billing record an IP cost is linked to, by what it is
 * (invoice number, line, or time entry), never by typing its id.
 */
export function IpBillingRecordSelect({
  id,
  label,
  matterId,
  linkType,
  value,
  onChange,
}: {
  id: string;
  label: string;
  matterId: string;
  linkType: IpBillingLinkType;
  value: string;
  onChange: (recordId: string) => void;
}) {
  const workspace = useMatterWorkspace(matterId);
  const noun = NOUN[linkType];
  const records = useMemo(
    () => (workspace.data ? billingRecordOptions(workspace.data, linkType) : []),
    [workspace.data, linkType],
  );
  const forbidden = workspace.error instanceof ApiError && (workspace.error.status === 403 || workspace.error.status === 404);
  // A link recorded earlier stays visible even if the record left the Matter.
  const unknownValue = Boolean(value) && workspace.isSuccess && !records.some((option) => option.value === value);
  const options: RecordSelectOption[] = [
    { value: "", label: workspace.isPending ? `Loading ${noun.many}…` : `Choose the ${noun.one}`, disabled: true },
    ...(unknownValue ? [{ value, label: `The recorded ${noun.one} is no longer in this Matter`, disabled: true }] : []),
    ...records,
  ];
  const statusId = `${id}-status`;

  let status: React.ReactNode = null;
  if (workspace.isPending) status = `Loading the Matter's ${noun.many}…`;
  else if (forbidden) status = `Your role cannot read this Matter's billing, so the cost cannot be linked to a ${noun.one} here. Choose No billing link, or ask a Matter billing member.`;
  else if (workspace.isSuccess && records.length === 0) {
    status = (
      <>
        This Matter has no {noun.many} yet.{" "}
        <Link className="font-semibold text-[var(--color-brand-700)] underline" href={`/app/matters/${matterId}/billing`}>
          Open the Matter&apos;s billing
        </Link>{" "}
        to record one, or choose No billing link.
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <RecordSelect
        id={id}
        label={label}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:opacity-60"
        value={value}
        options={options}
        disabled={!workspace.isSuccess || records.length === 0}
        aria-describedby={status || workspace.isError ? statusId : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {status ? (
        <p id={statusId} role="status" className="break-words text-xs text-[var(--color-mute)]">{status}</p>
      ) : workspace.isError ? (
        <div id={statusId} role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[var(--color-danger-text)]">
          <span className="min-w-0 break-words">{apiErrorMessage(workspace.error, `Could not load the Matter's ${noun.many}.`)}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => void workspace.refetch()}>Try again</Button>
        </div>
      ) : null}
    </div>
  );
}
