import type { IpPortfolioRow } from "@/lib/api/endpoints";

/**
 * The portfolio Status a lawyer reads (B4-ADJ-11), mirroring the API's
 * `portfolio_status_text` so the screen and the CSV export agree.
 *
 * The headline is the application's filing phase. When a portfolio import's
 * source says more than that phase (a Registered mark imports in the filed
 * phase; wording the import does not recognise imports as draft), the source
 * wording leads instead, marked unverified, so neither reads as Draft. The
 * docket's own state (`draft` / `ready` particulars, on hold, closed) is a
 * separate, labelled record status, never the headline.
 */
type StatusRow = Pick<IpPortfolioRow, "filing_phase" | "docket_status" | "source_declared_status" | "source_status_text">;

const IMPORT_PHASE_RANK: Record<string, number> = { draft: 0, pre_filing: 1, filed: 2 };
const PHASE_LABELS: Record<string, string> = { draft: "Draft", pre_filing: "Pre-filing", filed: "Filed" };

export function phaseLabel(phase: string): string {
  const words = phase.replaceAll("_", " ");
  return PHASE_LABELS[phase] ?? `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

export function sourceStatusIsAhead(row: StatusRow): boolean {
  const phaseRank = IMPORT_PHASE_RANK[row.filing_phase];
  if (!row.source_status_text || phaseRank === undefined) return false;
  const declared = row.source_declared_status;
  return !declared || (IMPORT_PHASE_RANK[declared] ?? 3) > phaseRank;
}

export function portfolioStatus(row: StatusRow): { label: string; unverified: boolean } {
  if (sourceStatusIsAhead(row)) return { label: `${row.source_status_text} (source, unverified)`, unverified: true };
  return { label: phaseLabel(row.filing_phase), unverified: false };
}

const RECORD_STATUS_LABELS: Record<string, string> = {
  draft: "Record: particulars draft",
  ready: "Record: particulars ready",
  on_hold: "Record: on hold",
  closed: "Record: closed",
};

/** The docket's own state, always labelled so it never reads as the mark's status. */
export function recordStatusLabel(status: string): string {
  return RECORD_STATUS_LABELS[status] ?? `Record: ${status.replaceAll("_", " ")}`;
}

/** Visible portfolio columns as export columns; Status exports with its record status. */
export function exportColumns<T extends string>(columns: readonly T[]): (T | "record_status")[] {
  return columns.flatMap((column) => (column === "status" ? [column, "record_status" as const] : [column]));
}
