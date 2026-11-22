/**
 * Assisted official trade mark search (IPLF-052D, UJ-07 / UJ-31).
 *
 * CaseOps never runs these searches. It opens the official page in a new
 * tab, says exactly what to enter, and the lawyer completes the site's own
 * verification (CAPTCHA or OTP). IP India result pages come back as an
 * upload; TMview is a pre-search aid only and is never imported.
 */

export type OfficialSearchKind =
  | "ipindia_estatus"
  | "ipindia_eregister"
  | "ipindia_public_search"
  | "tmview";

export type ImportableSearchKind = Exclude<OfficialSearchKind, "tmview">;

export type OfficialSearchQuery = {
  applicationNumber: string;
  wordMark: string;
  niceClass: string;
};

type SearchDefinition = {
  label: string;
  site: string;
  by: "number" | "mark";
  importable: boolean;
};

export const OFFICIAL_SEARCHES: Record<OfficialSearchKind, SearchDefinition> = {
  ipindia_estatus: {
    label: "Status by application number",
    site: "IP India e-status",
    by: "number",
    importable: true,
  },
  ipindia_eregister: {
    label: "Register entry by application number",
    site: "IP India e-register",
    by: "number",
    importable: true,
  },
  ipindia_public_search: {
    label: "Word mark and class",
    site: "IP India public search",
    by: "mark",
    importable: true,
  },
  tmview: {
    label: "Pre-search in TMview",
    site: "TMview (EUIPO)",
    by: "mark",
    importable: false,
  },
};

export const OFFICIAL_SEARCH_ORDER: OfficialSearchKind[] = [
  "ipindia_estatus",
  "ipindia_eregister",
  "ipindia_public_search",
  "tmview",
];

const IPINDIA_URLS: Record<ImportableSearchKind, string> = {
  ipindia_estatus: "https://tmrsearch.ipindia.gov.in/estatus",
  ipindia_eregister: "https://tmrsearch.ipindia.gov.in/eregister/",
  ipindia_public_search: "https://tmrsearch.ipindia.gov.in/tmrpublicsearch/",
};

/**
 * TMview deep link. The query parameters follow TMview's own result route;
 * they are a convenience only, so the steps always repeat what to enter in
 * case TMview opens without them.
 */
export function tmviewSearchUrl(query: Pick<OfficialSearchQuery, "wordMark">): string {
  const params = new URLSearchParams({
    page: "1",
    pageSize: "30",
    criteria: "C",
    basicSearch: query.wordMark.trim(),
    offices: "IN",
  });
  return `https://www.tmdn.org/tmview/#/tmview/results?${params.toString()}`;
}

export function officialSearchUrl(kind: OfficialSearchKind, query: OfficialSearchQuery): string {
  return kind === "tmview" ? tmviewSearchUrl(query) : IPINDIA_URLS[kind];
}

export function normalizedApplicationNumber(value: string): string {
  return value.replace(/\s+/g, "");
}

/** A plain-language problem with the query, or null when it can be used. */
export function queryProblem(kind: OfficialSearchKind, query: OfficialSearchQuery): string | null {
  if (OFFICIAL_SEARCHES[kind].by === "number") {
    const number = normalizedApplicationNumber(query.applicationNumber);
    if (!number) return "Enter the application number.";
    if (!/^\d{1,8}$/.test(number)) return "An IP India application number is digits only.";
    return null;
  }
  if (!query.wordMark.trim()) return "Enter the word mark.";
  const niceClass = Number(query.niceClass);
  if (!query.niceClass.trim() || !Number.isInteger(niceClass) || niceClass < 1 || niceClass > 45) {
    return "Choose a class from 1 to 45.";
  }
  return null;
}

export type EntryStep = { label: string; value?: string };

/** What to enter on the official site, in order. */
export function entrySteps(kind: OfficialSearchKind, query: OfficialSearchQuery): EntryStep[] {
  const number = normalizedApplicationNumber(query.applicationNumber);
  const mark = query.wordMark.trim();
  const niceClass = query.niceClass.trim();
  switch (kind) {
    case "ipindia_estatus":
      return [
        { label: "Choose the option to search by application (national) number" },
        { label: "Application number", value: number },
        { label: "Complete IP India's verification (CAPTCHA or OTP) yourself" },
        { label: "Open the result, then save the page" },
      ];
    case "ipindia_eregister":
      return [
        { label: "Open the trade mark e-register" },
        { label: "Application number", value: number },
        { label: "Complete IP India's verification (CAPTCHA) yourself" },
        { label: "Open the register entry, then save the page" },
      ];
    case "ipindia_public_search":
      return [
        { label: "Search type: Wordmark" },
        { label: "Word mark", value: mark },
        { label: "Class", value: niceClass },
        { label: "Complete IP India's verification (CAPTCHA) yourself" },
        { label: "Open the one record you need from the results, then save that page" },
      ];
    case "tmview":
      return [
        { label: "Trade mark name", value: mark },
        { label: "Office", value: "IN (India)" },
        { label: "Nice class", value: niceClass },
        { label: "Note the date TMview shows for India's last data update" },
      ];
  }
}

export function uploadMetadata(kind: ImportableSearchKind, query: OfficialSearchQuery) {
  return OFFICIAL_SEARCHES[kind].by === "number"
    ? { source_kind: kind, application_number: normalizedApplicationNumber(query.applicationNumber) }
    : { source_kind: kind, word_mark: query.wordMark.trim(), nice_class: Number(query.niceClass) };
}

export const OFFICIAL_FIELD_LABELS: Record<string, string> = {
  application_number: "Application number",
  mark: "Mark",
  class_numbers: "Class",
  status: "Status",
  proprietor: "Proprietor (as published)",
  filing_date: "Date of application",
  valid_upto: "Valid upto",
  journal_reference: "Journal",
  page: "Page",
};

export const REVIEW_REASON_TEXT: Record<string, string> = {
  not_found: "Not found on the page.",
  unrecognised_application_number: "The value is not an application number CaseOps can read.",
  unrecognised_class: "The class is not a number CaseOps can read.",
  class_out_of_range: "The class is outside 1 to 45.",
  unrecognised_date: "The date is not in a format CaseOps can read with certainty.",
  unrecognised_journal_reference: "The journal reference could not be read with certainty.",
  value_too_long: "The value is longer than CaseOps keeps.",
  conflicting_values: "The page shows more than one value for this field.",
  differs_from_search: "The page does not match what you searched for.",
  results_list_not_single_record:
    "This is a list of results. Open the one record you need and save that page.",
  verification_page_not_result:
    "This is IP India's verification page, not a result. Complete the verification and save the result.",
  page_too_large_to_read_completely: "The page was too large to read completely.",
  pdf_has_no_text: "The PDF has no text to read. Use Print to PDF from the browser, not a scan.",
};

export function reviewReasonText(reason: string): string {
  return REVIEW_REASON_TEXT[reason] ?? "Needs review.";
}

/** Display text for a read field; never markup. */
export function fieldText(field: string, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (field === "class_numbers" && Array.isArray(value)) return value.join(", ");
  if (field === "journal_reference" && typeof value === "object") {
    const journal = value as { journal_number?: string; journal_date?: string };
    return [journal.journal_number ? `No. ${journal.journal_number}` : null, journal.journal_date]
      .filter(Boolean)
      .join(", ");
  }
  return String(value);
}
