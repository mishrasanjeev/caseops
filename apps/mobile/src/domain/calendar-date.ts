import { ContractError, dateOnly, shiftDay } from "./contracts.ts";

// Compose uses UTC day milliseconds; SwiftUI uses the explicit UTC environment.
export function dateOnlyToPickerDate(value: string): Date {
  const [year, month, day] = dateOnly(value).split("-").map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return date;
}

export function pickerDateToDateOnly(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime()))
    throw new ContractError("calendar picker date");
  return dateOnly(
    `${String(value.getUTCFullYear()).padStart(4, "0")}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-${String(value.getUTCDate()).padStart(2, "0")}`,
  );
}

export function adjacentCalendarDay(
  value: string,
  offset: -7 | -1 | 1 | 7,
): string | null {
  dateOnly(value);
  if (![-7, -1, 1, 7].includes(offset))
    throw new ContractError("calendar navigation");
  const date = dateOnlyToPickerDate(value);
  date.setUTCDate(date.getUTCDate() + offset);
  if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return null;
  return shiftDay(value, offset);
}
