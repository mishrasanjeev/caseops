/**
 * Reminder offsets typed as free text ("48, 24", "48h, 2d", "1 week").
 *
 * Every token either becomes a whole number of hours or produces an error
 * naming it; nothing typed is silently dropped (B4-ADJ-19: "48h" used to
 * vanish through a Number.isInteger filter, so the hearing was scheduled
 * with fewer reminders than the lawyer asked for). The default bounds mirror
 * IpHearingReminderPolicyRequest (0 to 8760 hours, unique, at most 12); other
 * reminder forms pass their own API bounds.
 */
export const REMINDER_OFFSET_FORMAT_HINT =
  "Separate offsets with commas. Use hours (48 or 48h), days (2d) or weeks (1w).";

const UNIT_HOURS: Record<string, number> = {
  "": 1, h: 1, hr: 1, hrs: 1, hour: 1, hours: 1,
  d: 24, day: 24, days: 24,
  w: 168, wk: 168, week: 168, weeks: 168,
};

export type ReminderOffsetsResult =
  | { ok: true; hours: number[] }
  | { ok: false; error: string };

export function parseReminderOffsetsHours(
  input: string,
  { maxHours = 8760, maxCount = 12 }: { maxHours?: number; maxCount?: number } = {},
): ReminderOffsetsResult {
  const tokens = input.split(/[,;\n]+/).map((token) => token.trim()).filter((token) => token.length > 0);
  if (!tokens.length) return { ok: false, error: `Enter at least one reminder offset. ${REMINDER_OFFSET_FORMAT_HINT}` };
  const hours: number[] = [];
  for (const token of tokens) {
    const match = /^(\d+)\s*([a-z]*)$/i.exec(token);
    const factor = match ? UNIT_HOURS[match[2].toLowerCase()] : undefined;
    if (!match || factor === undefined) {
      return { ok: false, error: `"${token}" is not a reminder offset. ${REMINDER_OFFSET_FORMAT_HINT}` };
    }
    const value = Number(match[1]) * factor;
    if (value > maxHours) {
      return { ok: false, error: `"${token}" is ${value} hours; the most allowed is ${maxHours} hours.` };
    }
    if (hours.includes(value)) {
      return { ok: false, error: `"${token}" repeats an offset of ${value} hours already entered.` };
    }
    hours.push(value);
  }
  if (hours.length > maxCount) {
    return { ok: false, error: `Enter at most ${maxCount} reminder offsets; ${hours.length} were entered.` };
  }
  return { ok: true, hours };
}
