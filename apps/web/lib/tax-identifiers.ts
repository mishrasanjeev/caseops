/**
 * ENH-001: format checks for the GSTIN and PAN an outside counsel enters as
 * the supplier on its own invoice. Mirrors `normalise_gstin` / `normalise_pan`
 * in apps/api/src/caseops_api/services/matter_billing.py, which is the source
 * of truth; apps/api/tests/test_enh001_r2_verification_and_counsel_ids.py pins
 * the messages and state codes below to the API's.
 */

export const GSTIN_STATE_CODES: readonly string[] = [
  "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
  "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
  "21", "22", "23", "24", "26", "27", "29", "30", "31", "32",
  "33", "34", "35", "36", "37", "38", "97", "99",
];

export const GSTIN_FORMAT_MESSAGE =
  "Enter a 15-character GSTIN: a 2-digit state code, the 10-character PAN, an entity number, Z and a check character (for example 07AAAFK1234Q1Z2).";
export const GSTIN_STATE_MESSAGE =
  "The GSTIN must start with a valid GST state code (01 to 38, 97 or 99).";
export const PAN_FORMAT_MESSAGE =
  "Enter a 10-character PAN: 5 letters, 4 digits and a letter (for example AAAFK1234Q).";
export const PAN_GSTIN_MISMATCH_MESSAGE = "The PAN must match characters 3 to 12 of the GSTIN.";

const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

export function compactTaxIdentifier(value: string): string {
  return value.replace(/\s+/g, "").toUpperCase();
}

/** The API's message for this GSTIN, or null when it is blank or valid. */
export function gstinError(value: string): string | null {
  const gstin = compactTaxIdentifier(value);
  if (!gstin) return null;
  if (!GSTIN_PATTERN.test(gstin)) return GSTIN_FORMAT_MESSAGE;
  if (!GSTIN_STATE_CODES.includes(gstin.slice(0, 2))) return GSTIN_STATE_MESSAGE;
  return null;
}

/** The API's message for this PAN (checked against a valid GSTIN), or null. */
export function panError(value: string, gstin: string): string | null {
  const pan = compactTaxIdentifier(value);
  if (!pan) return null;
  if (!PAN_PATTERN.test(pan)) return PAN_FORMAT_MESSAGE;
  const compactGstin = compactTaxIdentifier(gstin);
  if (compactGstin && gstinError(compactGstin) === null && compactGstin.slice(2, 12) !== pan) {
    return PAN_GSTIN_MISMATCH_MESSAGE;
  }
  return null;
}
