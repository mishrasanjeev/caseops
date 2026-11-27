import { describe, expect, it } from "vitest";

import type { RenditionSummary } from "@/lib/api/endpoints";
import {
  isRenditionActive,
  isRenditionEligible,
  latestRendition,
  ocrOnlyLanguagesPhrase,
  pageReasonLabel,
  pageSourceLabel,
  pageStatusLabel,
  providerReasonLabel,
  renditionStatusLabel,
  renditionStatusTone,
  translationFlagLabel,
  translationTargets,
} from "@/lib/renditions";

const STATUSES: RenditionSummary["status"][] = [
  "queued",
  "inspecting",
  "ocr_processing",
  "ocr_completed",
  "translation_processing",
  "translation_completed",
  "review_required",
  "failed",
];

describe("rendition labels", () => {
  it("gives every status a word label and treats only in-flight statuses as active", () => {
    expect(STATUSES.map((status) => renditionStatusLabel({ status, kind: "ocr" }))).toEqual([
      "OCR queued",
      "Inspecting pages",
      "OCR processing",
      "OCR completed",
      "Translation processing",
      "Translation completed",
      "Review required",
      "OCR failed",
    ]);
    expect(renditionStatusLabel({ status: "queued", kind: "translation" })).toBe("Translation queued");
    expect(renditionStatusLabel({ status: "failed", kind: "translation" })).toBe("Translation failed");
    expect(STATUSES.filter((status) => isRenditionActive({ status }))).toEqual([
      "queued",
      "inspecting",
      "ocr_processing",
      "translation_processing",
    ]);
    expect(renditionStatusTone("failed")).toBe("danger");
    expect(renditionStatusTone("review_required")).toBe("warning");
    expect(renditionStatusTone("translation_completed")).toBe("success");
  });

  it("accepts only PDF, PNG, JPG and JPEG with a matching or generic content type", () => {
    expect(isRenditionEligible({ original_filename: "a.pdf", content_type: "application/pdf" })).toBe(true);
    expect(isRenditionEligible({ original_filename: "a.JPEG", content_type: "image/jpeg" })).toBe(true);
    expect(isRenditionEligible({ original_filename: "a.jpg", content_type: null })).toBe(true);
    expect(isRenditionEligible({ original_filename: "a.png", content_type: "application/octet-stream" })).toBe(true);
    expect(isRenditionEligible({ original_filename: "a.png", content_type: "application/pdf" })).toBe(false);
    expect(isRenditionEligible({ original_filename: "a.docx", content_type: null })).toBe(false);
    expect(isRenditionEligible({ original_filename: "no-extension", content_type: "application/pdf" })).toBe(false);
    expect(isRenditionEligible({ filename: "stored.pdf" })).toBe(true);
  });

  it("maps page reasons, provider errors and translation flags to plain words", () => {
    expect(pageReasonLabel("empty_page")).toBe("No text found");
    expect(pageReasonLabel("short_text")).toBe("Very little text");
    expect(pageReasonLabel("low_confidence")).toBe("Low OCR confidence");
    expect(pageReasonLabel("provider_page_missing")).toBe("OCR returned nothing for this page");
    expect(pageReasonLabel("provider_rate_limited")).toBe("OCR service error: rate limit reached");
    expect(pageReasonLabel("provider_something_new")).toBe("OCR service error: something new");
    expect(pageReasonLabel("ocr_provider_cost_not_verified")).toBe("OCR service paused until pricing is verified");
    expect(pageReasonLabel("number_added")).toBe("Number added");
    expect(pageReasonLabel("brand_new_reason")).toBe("Brand new reason");
    expect(translationFlagLabel("citation_abbreviation_changed")).toBe("Citation abbreviation changed");
    expect(translationFlagLabel("source_page_unreadable")).toBe("Source page unreadable");
    expect(providerReasonLabel(null)).toBe("This service is not available right now.");
    expect(providerReasonLabel("something_else")).toBe("This service is not available right now.");
    expect(pageSourceLabel("native")).toBe("Text layer");
    expect(pageSourceLabel("none")).toBe("Not read");
    expect(pageStatusLabel("review")).toBe("Needs review");
  });

  it("filters translation targets by source and picks the newest version for a row", () => {
    const providers = {
      ocr_provider_available: true,
      ocr_unavailable_reason: null,
      translation_available: true,
      translation_unavailable_reason: null,
      third_party_processing_permitted: true,
      ocr_languages: ["en", "hi", "mr"] as Array<"en" | "hi" | "mr">,
      translation_pairs: [
        { source: "hi" as const, target: "en" as const },
        { source: "en" as const, target: "mr" as const },
      ],
    };
    expect(translationTargets(providers, "hi")).toEqual(["en"]);
    expect(translationTargets(providers, "mr")).toEqual([]);
    expect(translationTargets(providers, "")).toEqual([]);
    expect(translationTargets(undefined, "hi")).toEqual([]);

    const older = { id: "o", kind: "ocr", created_at: "2026-11-23T09:00:00Z" } as RenditionSummary;
    const newer = { id: "t", kind: "translation", created_at: "2026-11-23T09:01:00Z" } as RenditionSummary;
    expect(latestRendition([older, newer])?.id).toBe("t");
    expect(latestRendition([newer, older])?.id).toBe("t");
    expect(latestRendition([])).toBeNull();
  });

  it("names the OCR languages no translation pair uses, in list order", () => {
    const base = {
      ocr_provider_available: true,
      ocr_unavailable_reason: null,
      translation_available: true,
      translation_unavailable_reason: null,
      third_party_processing_permitted: true,
    };
    const pairs = [
      { source: "hi" as const, target: "en" as const },
      { source: "en" as const, target: "hi" as const },
    ];
    const phrase = (ocr_languages: Array<"en" | "hi" | "od" | "ur" | "as">) =>
      ocrOnlyLanguagesPhrase({ ...base, ocr_languages, translation_pairs: pairs });
    expect(phrase(["en", "hi"])).toBe("");
    expect(phrase(["en", "hi", "ur"])).toBe("Urdu");
    expect(phrase(["en", "hi", "as", "od"])).toBe("Odia and Assamese");
    expect(phrase(["en", "hi", "od", "ur", "as"])).toBe("Odia, Urdu and Assamese");
    expect(ocrOnlyLanguagesPhrase(undefined)).toBe("");
  });
});
