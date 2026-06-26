export const MATTER_CODE_MESSAGE =
  "Use letters, numbers, and hyphens only. Spaces, underscores, slashes, and other special characters are not allowed.";

const MATTER_CODE_PATTERN = /^[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])$/;

export function normalizeMatterCodeInput(value: string): string {
  return value.trim().toUpperCase();
}

export function isValidMatterCode(value: string, maxLength = 40): boolean {
  const normalized = normalizeMatterCodeInput(value);
  return (
    normalized.length >= 2 &&
    normalized.length <= maxLength &&
    MATTER_CODE_PATTERN.test(normalized)
  );
}
