import type { MatterCaseResolutionResponse } from "@/lib/api/case-tracking-matter-resolution";

const quoted = (value: string | null | undefined) => (value ? ` “${value}”` : "");

/**
 * Reason-specific copy for a Matter the server could not match to a court case
 * (2026-09-27). The API names the one gap and returns the recorded values, so
 * the user is told what to correct instead of "insufficient identifiers".
 */
export function matterCaseIdentityGapMessage(
  response: Pick<MatterCaseResolutionResponse, "reason" | "case_number" | "cnr_number">,
): string {
  switch (response.reason) {
    case "invalid_cnr":
      return `The recorded CNR${quoted(response.cnr_number)} is not a valid 16-character CNR (four letters and twelve digits). Correct it on the Matter.`;
    case "unreadable_case_number":
      return `CaseOps could not read the case number${quoted(response.case_number)}. Record one case as its case type, number and year (for example WP(C) 6209/2019 or W.P.(C) No. 6209 of 2019), or record the CNR.`;
    case "case_type_required":
      return `Add the case type to the case number${quoted(response.case_number)} (for example WP(C) 6209/2019), or record the CNR. Registries reuse numbers across case types.`;
    default:
      return "Insufficient case identifiers. Add a valid CNR, or a case number with its case type, year and court, to the Matter.";
  }
}
