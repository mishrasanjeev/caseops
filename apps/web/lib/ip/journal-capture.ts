/**
 * Manual capture of one official trademark-journal entry (BUG-014).
 *
 * The intake form used to send raw JSON textareas and a class parser that
 * dropped "Class 45" without a word, so the API answered with a 422 that named
 * no field and an empty "{}" was accepted as evidence. This module turns the
 * lawyer's typed form into the API payload, or into errors keyed by the id of
 * the field that needs attention. It never drops a token and never sends an
 * entry without captured evidence.
 */
import type {
  IpJournalCapturedEvidence,
  IpJournalPublicationScope,
  ingestIpJournal,
} from "@/lib/api/endpoints";
import { parseNiceClasses } from "@/lib/ip/nice-classes";

export type JournalPublicationKind = "advertisement" | "correction" | "readvertisement";
export type JournalSourceStatus = "available" | "unavailable" | "stale";

export type JournalCaptureForm = {
  applicationId: string;
  journalNumber: string;
  journalDate: string;
  kind: JournalPublicationKind;
  applicationNumber: string;
  markText: string;
  deviceReference: string;
  proprietor: string;
  classNumbers: string;
  /** Goods/services typed per class number, one item per line. */
  goods: Record<string, string>;
  scopeKind: "full" | "partial";
  scopeClasses: number[];
  sourceUrl: string;
  sourcePage: string;
  sourceStatus: JournalSourceStatus;
  retrievedAt: string;
  extract: string;
  reference: string;
  notes: string;
  supersedes: string;
  correctionReason: string;
  cost: string;
};

export const EMPTY_JOURNAL_CAPTURE: JournalCaptureForm = {
  applicationId: "",
  journalNumber: "",
  journalDate: "",
  kind: "advertisement",
  applicationNumber: "",
  markText: "",
  deviceReference: "",
  proprietor: "",
  classNumbers: "",
  goods: {},
  scopeKind: "full",
  scopeClasses: [],
  sourceUrl: "",
  sourcePage: "",
  sourceStatus: "available",
  retrievedAt: "",
  extract: "",
  reference: "",
  notes: "",
  supersedes: "",
  correctionReason: "",
  cost: "0",
};

/** Control ids, shared by the form, its error summary and the API error map. */
export const CAPTURE_FIELDS = {
  application: "watch-application",
  journalNumber: "journal-number",
  journalDate: "journal-date",
  kind: "publication-kind",
  applicationNumber: "application-number",
  markText: "mark-text",
  deviceReference: "device-reference",
  proprietor: "proprietor",
  classes: "publication-classes",
  goods: "goods-services",
  scope: "publication-scope",
  sourceUrl: "journal-source",
  sourcePage: "source-page",
  sourceStatus: "source-status",
  retrievedAt: "retrieved-at",
  evidence: "evidence-extract",
  supersedes: "supersedes",
  correctionReason: "correction-reason",
  cost: "journal-cost",
} as const;

/** Visible labels, so a summary names the field the way the form does. */
export const CAPTURE_LABELS: Record<string, string> = {
  [CAPTURE_FIELDS.application]: "Linked trademark application",
  [CAPTURE_FIELDS.journalNumber]: "Journal number",
  [CAPTURE_FIELDS.journalDate]: "Journal date",
  [CAPTURE_FIELDS.kind]: "Publication kind",
  [CAPTURE_FIELDS.applicationNumber]: "Registry application number",
  [CAPTURE_FIELDS.markText]: "Published word mark",
  [CAPTURE_FIELDS.deviceReference]: "Published device image link",
  [CAPTURE_FIELDS.proprietor]: "Published proprietor",
  [CAPTURE_FIELDS.classes]: "Published Nice classes",
  [CAPTURE_FIELDS.goods]: "Goods and services as published",
  [CAPTURE_FIELDS.scope]: "Publication scope",
  [CAPTURE_FIELDS.sourceUrl]: "Official source URL",
  [CAPTURE_FIELDS.sourcePage]: "Source page",
  [CAPTURE_FIELDS.sourceStatus]: "Source status",
  [CAPTURE_FIELDS.retrievedAt]: "Retrieved at",
  [CAPTURE_FIELDS.evidence]: "Captured source evidence",
  [CAPTURE_FIELDS.supersedes]: "Journal entry being corrected",
  [CAPTURE_FIELDS.correctionReason]: "Correction reason",
  [CAPTURE_FIELDS.cost]: "Acquisition cost (paise)",
};

export function goodsFieldId(classNumber: number): string {
  return `goods-${classNumber}`;
}

/**
 * API field paths (as `apiFieldErrors` reads them) to control ids. Goods rows
 * are per class, so the map is built for the classes on the form.
 */
export function captureFieldMap(classNumbers: readonly number[]): Record<string, string> {
  const map: Record<string, string> = {
    "publications.application_id": CAPTURE_FIELDS.application,
    "publications.journal_number": CAPTURE_FIELDS.journalNumber,
    "publications.journal_date": CAPTURE_FIELDS.journalDate,
    "publications.publication_kind": CAPTURE_FIELDS.kind,
    "publications.application_number": CAPTURE_FIELDS.applicationNumber,
    "publications.mark_text": CAPTURE_FIELDS.markText,
    "publications.device_reference": CAPTURE_FIELDS.deviceReference,
    "publications.proprietor_name": CAPTURE_FIELDS.proprietor,
    "publications.class_numbers": CAPTURE_FIELDS.classes,
    "publications.goods_services": CAPTURE_FIELDS.goods,
    "publications.publication_scope": CAPTURE_FIELDS.scope,
    "publications.source_url": CAPTURE_FIELDS.sourceUrl,
    "publications.source_page": CAPTURE_FIELDS.sourcePage,
    "publications.source_status": CAPTURE_FIELDS.sourceStatus,
    "publications.source_retrieved_at": CAPTURE_FIELDS.retrievedAt,
    "publications.raw_evidence": CAPTURE_FIELDS.evidence,
    "publications.supersedes_publication_id": CAPTURE_FIELDS.supersedes,
    "publications.correction_reason": CAPTURE_FIELDS.correctionReason,
    cost_minor: CAPTURE_FIELDS.cost,
  };
  for (const number of classNumbers) {
    map[`publications.goods_services.${number}`] = goodsFieldId(number);
  }
  return map;
}

const HTTP_URL = /^https?:\/\/\S+$/i;
const MAX_EVIDENCE_TEXT = 20_000;

export function goodsItems(value: string): string[] {
  return value.split(/[\n;]/).map((item) => item.trim()).filter(Boolean);
}

export type JournalCapturePublication = Parameters<typeof ingestIpJournal>[0]["publication"];

export type JournalCaptureOutcome =
  | { ok: true; publication: JournalCapturePublication; costMinor: number }
  | { ok: false; errors: Record<string, string> };

/** Turn the typed form into the ingestion payload, or into field-keyed errors. */
export function buildJournalCapture(form: JournalCaptureForm): JournalCaptureOutcome {
  const errors: Record<string, string> = {};
  const journalNumber = form.journalNumber.trim();
  const applicationNumber = form.applicationNumber.trim();
  const markText = form.markText.trim();
  const deviceReference = form.deviceReference.trim();
  const sourceUrl = form.sourceUrl.trim();
  const extract = form.extract.trim();
  const reference = form.reference.trim();
  const notes = form.notes.trim();
  const correcting = form.kind !== "advertisement";

  if (!journalNumber) errors[CAPTURE_FIELDS.journalNumber] = "Enter the journal number as printed.";
  if (!form.journalDate) errors[CAPTURE_FIELDS.journalDate] = "Enter the journal date.";
  if (!applicationNumber) {
    errors[CAPTURE_FIELDS.applicationNumber] = "Enter the application number the journal publishes.";
  }
  if (deviceReference && !HTTP_URL.test(deviceReference)) {
    errors[CAPTURE_FIELDS.deviceReference] = "Use a web link that starts with https:// or http://.";
  }
  if (!markText && !deviceReference) {
    errors[CAPTURE_FIELDS.markText] =
      "Enter the published word mark, or link the published device image below.";
  }

  const parsed = parseNiceClasses(form.classNumbers);
  if (parsed.errors.length) {
    errors[CAPTURE_FIELDS.classes] = parsed.errors.map((error) => error.message).join(" ");
  } else if (parsed.classes.length === 0) {
    errors[CAPTURE_FIELDS.classes] = "Enter at least one published Nice class, for example 45.";
  }

  const goodsServices: Record<string, string[]> = {};
  for (const number of parsed.classes) {
    const items = goodsItems(form.goods[String(number)] ?? "");
    if (items.length) goodsServices[String(number)] = items;
  }

  let publicationScope: IpJournalPublicationScope = { scope_kind: "full" };
  if (form.scopeKind === "partial") {
    const covered = form.scopeClasses.filter((number) => parsed.classes.includes(number));
    if (covered.length === 0) {
      errors[CAPTURE_FIELDS.scope] = "Choose the published classes this partial publication covers.";
    }
    publicationScope = { scope_kind: "partial", published_classes: covered };
  }

  if (!sourceUrl) {
    errors[CAPTURE_FIELDS.sourceUrl] = "Enter the official journal link you read the entry from.";
  } else if (!HTTP_URL.test(sourceUrl)) {
    errors[CAPTURE_FIELDS.sourceUrl] = "Use a web link that starts with https:// or http://.";
  }
  if (form.sourcePage.trim().length > 80) {
    errors[CAPTURE_FIELDS.sourcePage] = "Shorten the page reference to 80 characters or fewer.";
  }
  let retrievedAt: string | null = null;
  if (form.retrievedAt) {
    const parsedDate = new Date(form.retrievedAt);
    if (Number.isNaN(parsedDate.getTime())) {
      errors[CAPTURE_FIELDS.retrievedAt] = "Enter a valid retrieval date and time.";
    } else {
      retrievedAt = parsedDate.toISOString();
    }
  }

  if (!extract && !reference) {
    errors[CAPTURE_FIELDS.evidence] =
      "Capture the source evidence: paste the journal entry as published, or give a reference to the saved journal page.";
  } else if (
    extract.length > MAX_EVIDENCE_TEXT
    || reference.length > MAX_EVIDENCE_TEXT
    || notes.length > MAX_EVIDENCE_TEXT
  ) {
    errors[CAPTURE_FIELDS.evidence] =
      "Keep each evidence entry to 20,000 characters; give a reference to the saved page instead.";
  }

  if (correcting) {
    if (!form.supersedes) {
      errors[CAPTURE_FIELDS.supersedes] = "Choose the recorded journal entry this one corrects.";
    }
    if (form.correctionReason.trim().length < 5) {
      errors[CAPTURE_FIELDS.correctionReason] = "Explain the correction in at least 5 characters.";
    }
  }

  const cost = Number(form.cost.trim() || "0");
  if (!Number.isInteger(cost) || cost < 0) {
    errors[CAPTURE_FIELDS.cost] = "Enter the cost in paise as a whole number (0 if none).";
  }

  if (Object.keys(errors).length) return { ok: false, errors };

  const evidence: IpJournalCapturedEvidence = { capture_method: "manual" };
  if (extract) evidence.extract_text = extract;
  if (reference) evidence.evidence_reference = reference;
  if (notes) evidence.notes = notes;

  return {
    ok: true,
    costMinor: cost,
    publication: {
      application_id: form.applicationId || null,
      journal_number: journalNumber,
      journal_date: form.journalDate,
      publication_kind: form.kind,
      application_number: applicationNumber,
      mark_text: markText || null,
      device_reference: deviceReference || null,
      proprietor_name: form.proprietor.trim() || null,
      office: "IP India",
      jurisdiction: "IN",
      class_numbers: parsed.classes,
      goods_services: goodsServices,
      publication_scope: publicationScope,
      source_url: sourceUrl,
      source_page: form.sourcePage.trim() || null,
      source_status: form.sourceStatus,
      source_retrieved_at: retrievedAt,
      parser_version: "manual-journal-v1",
      attribution: { publisher: "IP India", capture_method: "manual" },
      raw_evidence: evidence,
      supersedes_publication_id: correcting ? form.supersedes : null,
      correction_reason: correcting ? form.correctionReason.trim() : null,
    },
  };
}
