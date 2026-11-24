import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PRODUCT_GUIDE_CATALOG } from "@/lib/product-guide";

import GuidePage from "./page";

function section(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement;
}

describe("public guide current-product content", () => {
  it("shows the refreshed guide version and keeps one rendered section per catalog entry", () => {
    render(<GuidePage />);
    expect(PRODUCT_GUIDE_CATALOG.content_version).toBe("2026.11.22.1");
    expect(screen.getByText("User guide · v6 · 2026")).toBeInTheDocument();
    expect(document.querySelectorAll("article > section[id]")).toHaveLength(
      PRODUCT_GUIDE_CATALOG.sections.length,
    );
  });

  it("documents teams, IP availability, retirement, court sync, redlines, the assistant and mobile status", () => {
    render(<GuidePage />);
    expect(section("getting-started")).toHaveTextContent("not yet in the App Store or Google Play");
    expect(section("workspace")).toHaveTextContent("Teams and team leads");
    expect(section("workspace")).toHaveTextContent("It does not yet give the lead extra permissions");
    expect(section("documents")).toHaveTextContent("CaseOps adds it to a workspace's plan on request");
    expect(section("documents")).toHaveTextContent("there is no live IP India or WIPO feed");
    expect(section("documents")).toHaveTextContent("Retire an IP document");
    expect(section("documents")).toHaveTextContent("a document already published to a client cannot be retired");
    expect(section("case-tracking")).toHaveTextContent("Madras and Telangana High Courts");
    expect(section("contracts")).toHaveTextContent("moved passages (counted once");
    expect(section("contracts")).toHaveTextContent("It does not compare two separate files");
    expect(section("contracts")).not.toHaveTextContent("suggests an edit per deviation");
    expect(section("research")).toHaveTextContent("Opening a citation rechecks your access");
  });
});
