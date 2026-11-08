import { ContractError, string } from "./contracts.ts";

export const CURSOR_HISTORY_LIMIT = 100;

// An opaque server continuation: bounded, non-blank and free of control
// characters. Its content is never interpreted on the device.
export function continuationCursor(value: unknown, field: string): string {
  const result = string(value, field, 8000);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError(field);
  return result;
}

// A cursor history is a sliding window of the most recent page cursors, oldest
// first. Only the first page has a null cursor, so null can only lead the
// window. A repeat within the window is a cycle and must be refused; the window
// bounds retained state, not how far a list can be read.
export function advanceCursorHistory(
  history: readonly (string | null)[],
  next: string,
  field: string,
): (string | null)[] {
  continuationCursor(next, field);
  if (
    !history.length ||
    history.length > CURSOR_HISTORY_LIMIT ||
    history.slice(1).includes(null) ||
    history.includes(next)
  )
    throw new ContractError(field);
  return [...history.slice(-(CURSOR_HISTORY_LIMIT - 1)), next];
}
