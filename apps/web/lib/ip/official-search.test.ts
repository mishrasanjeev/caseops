import { describe, expect, it } from "vitest";

import {
  entrySteps,
  fieldText,
  officialSearchUrl,
  queryProblem,
  reviewReasonText,
  tmviewSearchUrl,
  uploadMetadata,
} from "@/lib/ip/official-search";

const EMPTY = { applicationNumber: "", wordMark: "", niceClass: "" };

describe("IPLF-052D official search helpers", () => {
  it("opens only the fixed official IP India pages", () => {
    expect(officialSearchUrl("ipindia_estatus", EMPTY)).toBe("https://tmrsearch.ipindia.gov.in/estatus");
    expect(officialSearchUrl("ipindia_eregister", EMPTY)).toBe("https://tmrsearch.ipindia.gov.in/eregister/");
    expect(officialSearchUrl("ipindia_public_search", EMPTY)).toBe("https://tmrsearch.ipindia.gov.in/tmrpublicsearch/");
  });

  it("builds an encoded TMview deep link limited to India", () => {
    const url = new URL(tmviewSearchUrl({ wordMark: " ASTRA & CO " }));
    expect(url.origin).toBe("https://www.tmdn.org");
    const params = new URLSearchParams(url.hash.split("?")[1]);
    expect(params.get("basicSearch")).toBe("ASTRA & CO");
    expect(params.get("offices")).toBe("IN");
  });

  it("validates the query for each search type", () => {
    expect(queryProblem("ipindia_estatus", EMPTY)).toBe("Enter the application number.");
    expect(queryProblem("ipindia_estatus", { ...EMPTY, applicationNumber: "TM-12" })).toMatch(/digits only/);
    expect(queryProblem("ipindia_eregister", { ...EMPTY, applicationNumber: "70 12345" })).toBeNull();
    expect(queryProblem("ipindia_public_search", { ...EMPTY, wordMark: "ASTRA", niceClass: "46" })).toMatch(/1 to 45/);
    expect(queryProblem("tmview", { ...EMPTY, wordMark: "ASTRA", niceClass: "9" })).toBeNull();
  });

  it("states exactly what to enter and that the lawyer completes the verification", () => {
    const steps = entrySteps("ipindia_estatus", { ...EMPTY, applicationNumber: "70 12345" });
    expect(steps.find((step) => step.value)?.value).toBe("7012345");
    expect(steps.some((step) => /verification \(CAPTCHA or OTP\) yourself/.test(step.label))).toBe(true);
    const tmview = entrySteps("tmview", { ...EMPTY, wordMark: "ASTRA", niceClass: "9" });
    expect(tmview.map((step) => step.value).filter(Boolean)).toEqual(["ASTRA", "IN (India)", "9"]);
  });

  it("sends only the query fields the API accepts", () => {
    expect(uploadMetadata("ipindia_estatus", { ...EMPTY, applicationNumber: " 7012345 " })).toEqual({
      source_kind: "ipindia_estatus",
      application_number: "7012345",
    });
    expect(uploadMetadata("ipindia_public_search", { applicationNumber: "1", wordMark: " ASTRA ", niceClass: "9" })).toEqual({
      source_kind: "ipindia_public_search",
      word_mark: "ASTRA",
      nice_class: 9,
    });
  });

  it("renders read values and review reasons as plain text", () => {
    expect(fieldText("class_numbers", [9, 35])).toBe("9, 35");
    expect(fieldText("journal_reference", { journal_number: "2150", journal_date: "2024-05-20" })).toBe("No. 2150, 2024-05-20");
    expect(reviewReasonText("results_list_not_single_record")).toMatch(/Open the one record/);
    expect(reviewReasonText("something_new")).toBe("Needs review.");
  });
});
