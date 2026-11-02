"use client";

import { useNiceClassCatalogue } from "@/components/ip/NiceClassPicker";
import type { IpTrademarkParticularVersion } from "@/lib/api/endpoints";

type ClassRow = IpTrademarkParticularVersion["classes_json"][number];

/**
 * A docket's class rows, each with the heading of the Nice edition that row
 * recorded (BUG-002). The heading comes from that edition, not the one in
 * force, so a 2026 row keeps its heading after NCL 13-2027 enters into force.
 * A row recorded before editions were stamped says so instead of borrowing a
 * heading from another edition.
 */
export function IpDocketClassScope({ classes }: { classes: ClassRow[] }) {
  return (
    <ul className="mt-2 flex min-w-0 flex-col gap-2">
      {classes.map((row) => (
        <ClassScopeRow key={row.class_number} row={row} />
      ))}
    </ul>
  );
}

function ClassScopeRow({ row }: { row: ClassRow }) {
  const catalogue = useNiceClassCatalogue(row.nice_edition ?? null);
  const heading = catalogue.data?.classes.find((entry) => entry.number === row.class_number)?.heading;
  return (
    <li
      className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3 text-sm"
      data-testid={`ip-docket-class-${row.class_number}`}
    >
      <strong>Class {row.class_number}</strong>
      {heading ? (
        <span className="break-words text-[var(--color-mute)]">
          {" — "}
          {heading}
        </span>
      ) : null}
      <span className="mt-1 block break-words">{row.specification}</span>
      <span className="mt-1 block text-xs text-[var(--color-mute)]">
        {row.nice_edition ? `Nice edition ${row.nice_edition}` : "Nice edition not recorded"}
        {row.nice_edition && catalogue.isError ? " · the class heading could not load" : null}
      </span>
    </li>
  );
}
