import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GeneralCounselsPage, { metadata } from "./page";

function card(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("article") as HTMLElement;
}

describe("general-counsel page product claims", () => {
  it("keeps a distinct canonical and description", () => {
    expect(metadata.alternates).toEqual({ canonical: "/general-counsels" });
    expect(metadata.description).toContain("trade mark portfolios");
  });

  it("describes outside counsel only as shipped: panel, budget ceiling and logged spend", () => {
    render(<GeneralCounselsPage />);
    expect(card("Counsel panel")).toBeInTheDocument();
    expect(card("Budget per assignment")).toHaveTextContent("budget ceiling");
    expect(card("Spend by firm")).toHaveTextContent("covers only what has been entered");
    // The "what's broken today" slide may describe spreadsheets without realisation
    // tracking; the product claims live in the counsel slide.
    const counsel = document.getElementById("counsel")?.textContent ?? "";
    expect(counsel).not.toMatch(/realisation|realization|historical outcomes|GC override|compare outcomes/i);
    expect(document.body.textContent).not.toMatch(/MatterPortalGrant|\/portal\/oc|OpenAI/);
  });

  it("states redline, IP, assistant, wall and mobile limits", () => {
    render(<GeneralCounselsPage />);
    expect(card("Counterparty redlines")).toHaveTextContent("tracked changes the viewer cannot display");
    expect(card("Trade mark and patent portfolio")).toHaveTextContent("there is no live IP India or WIPO feed");
    expect(card("Ask this Workspace")).toHaveTextContent("Off until the workspace owner enables it");
    expect(card("On a phone")).toHaveTextContent("not yet in the App Store or Google Play");
    expect(screen.getByText(/Workspace owners always keep access/)).toBeInTheDocument();
    expect(screen.getByText(/illustrative figures/)).toBeInTheDocument();
  });
});
