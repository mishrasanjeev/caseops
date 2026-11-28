// Labels and rules for Matter Documents "OCR & Translate" versions.
// Every status, reason and flag the API can return has a plain-language
// label here so the UI never shows a raw code to a lawyer.
import type {
  RenditionLanguage,
  RenditionProviderReadiness,
  RenditionSummary,
} from "@/lib/api/endpoints";

export const RENDITION_LANGUAGES: Array<{ value: RenditionLanguage; label: string }> = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "mr", label: "Marathi" },
];

export function languageLabel(code: string | null | undefined): string {
  return RENDITION_LANGUAGES.find((item) => item.value === code)?.label ?? (code ?? "");
}

const ELIGIBLE_TYPES: Record<string, string[]> = {
  pdf: ["application/pdf"],
  png: ["image/png"],
  jpg: ["image/jpeg", "image/jpg", "image/pjpeg"],
  jpeg: ["image/jpeg", "image/jpg", "image/pjpeg"],
};

/** Mirrors the API's format check: PDF, PNG, JPG and JPEG only. */
export function isRenditionEligible(attachment: {
  original_filename?: string | null;
  filename?: string | null;
  content_type?: string | null;
}): boolean {
  const name = attachment.original_filename ?? attachment.filename ?? "";
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  const accepted = ELIGIBLE_TYPES[name.slice(dot + 1).toLowerCase()];
  if (!accepted) return false;
  const declared = (attachment.content_type ?? "").split(";")[0].trim().toLowerCase();
  return !declared || declared === "application/octet-stream" || accepted.includes(declared);
}

export const ACTIVE_RENDITION_STATUSES: ReadonlySet<RenditionSummary["status"]> = new Set([
  "queued",
  "inspecting",
  "ocr_processing",
  "translation_processing",
]);

export function isRenditionActive(rendition: Pick<RenditionSummary, "status">): boolean {
  return ACTIVE_RENDITION_STATUSES.has(rendition.status);
}

export function renditionKindLabel(kind: RenditionSummary["kind"]): string {
  return kind === "translation" ? "Translation" : "OCR";
}

export function renditionStatusLabel(
  rendition: Pick<RenditionSummary, "status" | "kind">,
): string {
  const kind = renditionKindLabel(rendition.kind);
  switch (rendition.status) {
    case "queued":
      return `${kind} queued`;
    case "inspecting":
      return "Inspecting pages";
    case "ocr_processing":
      return "OCR processing";
    case "ocr_completed":
      return "OCR completed";
    case "translation_processing":
      return "Translation processing";
    case "translation_completed":
      return "Translation completed";
    case "review_required":
      return "Review required";
    case "failed":
      return `${kind} failed`;
  }
}

export type RenditionTone = "neutral" | "brand" | "success" | "warning" | "danger";

export function renditionStatusTone(status: RenditionSummary["status"]): RenditionTone {
  if (status === "failed") return "danger";
  if (status === "review_required") return "warning";
  if (status === "ocr_completed" || status === "translation_completed") return "success";
  return "brand";
}

export function reviewStatusLabel(rendition: RenditionSummary): string {
  if (rendition.review_status === "needs_correction") return "Needs correction";
  if (rendition.review_status === "reviewed") return "Reviewed";
  return "Not reviewed";
}

/** The rendition to summarise on a document row: the most recent one. */
export function latestRendition(
  renditions: RenditionSummary[],
): RenditionSummary | null {
  let latest: RenditionSummary | null = null;
  for (const item of renditions) {
    if (
      !latest ||
      item.created_at > latest.created_at ||
      (item.created_at === latest.created_at && item.kind === "translation")
    ) {
      latest = item;
    }
  }
  return latest;
}

const PROVIDER_REASONS: Record<string, string> = {
  provider_disabled: "This service is turned off for the workspace.",
  credentials_missing: "This service is not configured yet.",
  cost_not_verified: "This service is paused until its pricing is verified.",
  third_party_processing_not_permitted:
    "This document is restricted to processing inside CaseOps, so it cannot be sent to an outside service.",
};

export function providerReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "This service is not available right now.";
  return PROVIDER_REASONS[reason] ?? "This service is not available right now.";
}

/** Translation targets the API supports for a source language. */
export function translationTargets(
  providers: RenditionProviderReadiness | undefined,
  source: RenditionLanguage | "",
): RenditionLanguage[] {
  if (!providers || !source) return [];
  return providers.translation_pairs
    .filter((pair) => pair.source === source)
    .map((pair) => pair.target);
}

function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * The languages the server accepts, stated in words, so a short list reads as
 * the supported set rather than a broken dropdown (Ram BUG-005, 2026-11-26).
 * Built only from the readiness payload: it can never name a language the
 * server would reject, and grows with it.
 */
export function supportedLanguagesSummary(
  providers: RenditionProviderReadiness | undefined,
): { ocr: string; translation: string | null } | null {
  if (!providers || providers.ocr_languages.length === 0) return null;
  const ocr = `OCR reads documents in ${joinLabels(providers.ocr_languages.map(languageLabel))}.`;
  if (!providers.translation_available || providers.translation_pairs.length === 0) {
    return { ocr, translation: null };
  }
  const seen = new Set<string>();
  const phrases: string[] = [];
  for (const pair of providers.translation_pairs) {
    const key = [pair.source, pair.target].sort().join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    const both = providers.translation_pairs.some(
      (other) => other.source === pair.target && other.target === pair.source,
    );
    phrases.push(
      both
        ? `${languageLabel(pair.source)} ↔ ${languageLabel(pair.target)}`
        : `${languageLabel(pair.source)} → ${languageLabel(pair.target)}`,
    );
  }
  return { ocr, translation: `Translation: ${phrases.join(", ")}.` };
}

const PAGE_REASONS: Record<string, string> = {
  empty_page: "No text found",
  short_text: "Very little text",
  low_confidence: "Low OCR confidence",
  unreadable_characters: "Unreadable characters",
  provider_page_missing: "OCR returned nothing for this page",
  provider_rejected: "OCR service rejected this page",
  provider_failed: "OCR service failed on this page",
  provider_submit_uncertain:
    "An earlier OCR request was interrupted and may have been charged; retry to send it again",
  inspect_no_text_layer: "Scanned page with no text layer",
  inspect_unreliable_text_layer: "Text layer unreliable",
  inspect_legacy_font_encoding_suspected: "Text layer uses a legacy font encoding",
  paid_provider_blocked_for_test: "Paid OCR disabled for automated verification",
  third_party_processing_not_permitted:
    "Document restricted to processing inside CaseOps",
  ocr_provider_provider_disabled: "OCR service is turned off",
  ocr_provider_credentials_missing: "OCR service is not configured",
  ocr_provider_cost_not_verified: "OCR service paused until pricing is verified",
  source_page_unreadable: "Source page unreadable",
  source_needs_review: "Source needs review",
};

const PROVIDER_ERRORS: Record<string, string> = {
  invalid_request: "request rejected",
  auth: "credentials rejected",
  billing: "billing blocked the request",
  not_found: "job not found",
  not_ready: "job not finished",
  file_too_large: "file too large",
  invalid_file: "file unreadable",
  rate_limited: "rate limit reached",
  unavailable: "service unavailable",
  timeout: "no answer in time",
  network: "service unreachable",
  bad_response: "unexpected response",
  bad_output: "unreadable output",
  download_failed: "output could not be downloaded",
  output_too_large: "output too large",
  unsupported_language: "language not supported",
};

function humanise(code: string): string {
  const text = code.replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : code;
}

export function pageReasonLabel(reason: string): string {
  const known = PAGE_REASONS[reason] ?? TRANSLATION_FLAGS[reason];
  if (known) return known;
  if (reason.startsWith("provider_")) {
    const code = reason.slice("provider_".length);
    return `OCR service error: ${PROVIDER_ERRORS[code] ?? humanise(code).toLowerCase()}`;
  }
  return humanise(reason);
}

const TRANSLATION_FLAGS: Record<string, string> = {
  number_missing: "Number missing",
  number_added: "Number added",
  identifier_changed: "Identifier changed",
  citation_abbreviation_changed: "Citation abbreviation changed",
  possible_omission: "Possible omission",
  unclear_source: "Source unclear",
  source_needs_review: "Source needs review",
  source_page_unreadable: "Source page unreadable",
};

export function translationFlagLabel(flag: string): string {
  return TRANSLATION_FLAGS[flag] ?? humanise(flag);
}

export function pageSourceLabel(source: string): string {
  if (source === "native") return "Text layer";
  if (source === "ocr") return "OCR";
  return "Not read";
}

export function pageStatusLabel(status: string): string {
  if (status === "ok") return "Read";
  if (status === "review") return "Needs review";
  if (status === "failed") return "Unread";
  if (status === "pending") return "Not read yet";
  return humanise(status);
}
