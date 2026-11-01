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
