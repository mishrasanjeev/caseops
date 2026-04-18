/**
 * Legal dates are calendar dates. They do NOT carry a time or a
 * timezone — a hearing listed on 2026-05-02 is on May 2, period, no
 * matter what timezone the reviewing lawyer happens to be in.
 *
 * Naive `new Date("2026-05-02")` is interpreted by JS as UTC
 * midnight. In any non-UTC timezone, `toLocaleDateString()` then
 * renders the *previous* calendar day — so a filing date that is
 * 2026-05-02 in the SQL `Date` column becomes "May 01, 2026" on
 * screens viewed in UTC-negative timezones. This is a legal-product
 * ship-stopper: cause-list dates, listing dates, and contract
 * effective dates MUST display as the day the database stores.
 *
 * `formatLegalDate` parses the YYYY-MM-DD components and constructs
 * a local-midnight Date so the local formatter renders the right day.
 * Use it for every SQL `Date` field rendered on the UI.
 *
 * For timestamps (SQL `timestamptz`, ISO strings with Z) the normal
 * `new Date(iso).toLocaleString()` path is correct — the offset is
 * semantically meaningful there.
 */

const ISO_DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export type LegalDateInput = string | Date | null | undefined;

/** Default options for legal calendar rendering (e.g. "May 02, 2026"). */
const DEFAULT_OPTIONS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "short",
  day: "2-digit",
};

/**
 * Format a SQL `Date` (YYYY-MM-DD) safely against timezone offsets.
 * Returns "—" for nullish values so callers can drop the conditional.
 */
export function formatLegalDate(
  value: LegalDateInput,
  options: Intl.DateTimeFormatOptions = DEFAULT_OPTIONS,
  locale?: string,
): string {
  if (value == null) return "—";
  const date = toLocalCalendarDate(value);
  if (!date) return "—";
  return date.toLocaleDateString(locale, options);
}

/**
 * Parse a YYYY-MM-DD string into a local-midnight Date so
 * `toLocaleDateString` renders the stored calendar day. Returns
 * `null` on unparseable input.
 */
export function toLocalCalendarDate(value: LegalDateInput): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  const match = ISO_DATE_ONLY.exec(value);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    const d = new Date(year, month, day);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  // Fall back to the native parser for timestamptz / ISO strings with
  // a time component — those carry a timezone and need UTC handling.
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
