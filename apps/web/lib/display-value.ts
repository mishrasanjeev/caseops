/**
 * Plain-language rendering of report and publication values.
 *
 * Lawyers and clients read these cells; raw JSON (braces, quotes, snake_case
 * keys) is never shown to them (B4-ADJ-02: the client portal printed
 * `JSON.stringify` of publication rows).
 */
export function fieldLabel(key: string): string {
  const text = key.replaceAll("_", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key;
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(displayValue).join(", ") : "None";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "None";
    return entries.map(([key, item]) => `${fieldLabel(key)}: ${displayValue(item)}`).join("; ");
  }
  return String(value);
}

const INTERNAL_ID_VALUE =
  /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$/i;

/** A field that carries an internal record id or hash, never shown to a reader. */
export function isInternalIdKey(key: string): boolean {
  return key === "id" || /_ids?$/.test(key) || /_(?:sha256|hash)$/.test(key);
}

/** A UUID or hex digest: an internal identifier whatever its field is called. */
export function looksLikeInternalId(value: unknown): boolean {
  if (typeof value === "string") return INTERNAL_ID_VALUE.test(value.trim());
  return Array.isArray(value) && value.length > 0 && value.every(looksLikeInternalId);
}

/** A stored code such as `filing_in_progress` read as words ("Filing in progress"). */
export function readableCode(value: string): string {
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(value) ? fieldLabel(value) : value;
}

/** A report cell in words: stored codes read as words, never raw JSON. */
export function displayCell(value: unknown): string {
  if (typeof value === "string" && value) return readableCode(value);
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.length ? value.map((item) => readableCode(item as string)).join(", ") : "None";
  }
  return displayValue(value);
}

/** Report columns a reader may see: no internal ids or hashes, by name or by value. */
export function readableColumns(rows: readonly Record<string, unknown>[], limit: number): string[] {
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return keys
    .filter((key) => !isInternalIdKey(key) && !rows.some((row) => looksLikeInternalId(row[key])))
    .slice(0, limit);
}
