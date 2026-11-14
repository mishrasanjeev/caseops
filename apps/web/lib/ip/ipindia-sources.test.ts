import { describe, expect, it } from "vitest";

import { IPINDIA_REVIEWED_ON, IPINDIA_SOURCES, searchIpIndiaSources } from "./ipindia-sources";

describe("reviewed IP India reference catalogue", () => {
  it("keeps complete bounded inventory and unique source identities", () => {
    expect(IPINDIA_REVIEWED_ON).toBe("2026-11-14");
    expect(IPINDIA_SOURCES).toHaveLength(7);
    expect(new Set(IPINDIA_SOURCES.map((row) => row.id)).size).toBe(7);
    expect(searchIpIndiaSources(" ")).toHaveLength(7);
  });
  it.each(IPINDIA_SOURCES)("keeps $id on exact official HTTPS hosts without credentials or query leakage", (row) => {
    for (const value of [row.url, row.discoveredFrom]) {
      const url = new URL(value);
      expect(url.protocol).toBe("https:");
      expect(["www.ipindia.gov.in", "ipindia.gov.in", "iprsearch.ipindia.gov.in", "tmrsearch.ipindia.gov.in", "search.ipindia.gov.in"]).toContain(url.hostname);
      expect(url.username + url.password + url.port + url.search + url.hash).toBe("");
    }
  });
  it("searches transcribed Form 2 content, not only link titles", () => {
    expect(searchIpIndiaSources(" NATIONALITY  applicant ").map((row) => row.id)).toEqual(["patent-form-2"]);
    expect(searchIpIndiaSources("provisional claims", "form").map((row) => row.id)).toEqual(["patent-form-2"]);
    expect(searchIpIndiaSources("150", "rule").map((row) => row.id)).toEqual(["patent-rule-13"]);
  });
  it("keeps form numbers typed by domain rather than conflating Patent and Design Form 1", () => {
    expect(searchIpIndiaSources("design form 1", "form").map((row) => row.id)).toEqual(["design-forms"]);
    expect(searchIpIndiaSources("TM-O", "form").map((row) => row.id)).toEqual(["trademark-forms"]);
  });
  it("does not claim register results on empty, unknown or injection-shaped searches", () => {
    expect(searchIpIndiaSources("nonexistent-registered-mark-999")).toEqual([]);
    expect(searchIpIndiaSources("<script>alert(1)</script>")).toEqual([]);
    expect(searchIpIndiaSources("TM-A", "register")).toEqual([]);
    expect(searchIpIndiaSources("", "register")).toHaveLength(3);
  });
  it("pins only bytes actually acquired and retains provisional/complete boundaries", () => {
    const form = IPINDIA_SOURCES.find((row) => row.id === "patent-form-2")!;
    expect(form.sha256).toBe("b2329c5274d5e7d7f4dc15b2a77233275f0c2bc53873a64466561bbade13fca9");
    expect(form.fields).toHaveLength(7);
    expect(form.summary).toContain("claims are not applicable to a provisional specification");
    expect(IPINDIA_SOURCES.filter((row) => row.sha256)).toEqual([form]);
  });
});
