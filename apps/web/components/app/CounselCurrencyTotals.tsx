import type { ReactNode } from "react";

import { formatMoneyMinor } from "@/lib/billing-format";

export function formatCounselAmount(value: number | null, currency: string): string {
  if (value === null) return "Unavailable";
  return /^[A-Z]{3}$/.test(currency) ? formatMoneyMinor(value, currency, 2) : `${value} minor units`;
}

export function sumCounselAmounts<Row>(rows: readonly Row[], value: (row: Row) => number | null | undefined): number | null {
  let sum = 0;
  for (const row of rows) {
    const amount = value(row);
    if (amount == null) return null;
    sum += amount;
  }
  return sum;
}

export function CounselCurrencyTotals<Row extends { currency: string }>({
  rows,
  renderAmount,
  empty = "No amounts recorded",
}: {
  rows: readonly Row[];
  renderAmount: (group: readonly Row[], currency: string) => ReactNode;
  empty?: string;
}) {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const code = row.currency.trim().toUpperCase();
    const group = groups.get(code);
    if (group) group.push(row);
    else groups.set(code, [row]);
  }
  if (groups.size === 0) return empty;

  return (
    <dl className="mt-1 space-y-1 text-sm">
      {[...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([currency, group]) => (
        <div key={currency} className="flex flex-wrap gap-x-2">
          <dt className="font-medium">{currency || "Unknown currency"}</dt>
          <dd>{renderAmount(group, currency)}</dd>
        </div>
      ))}
    </dl>
  );
}
