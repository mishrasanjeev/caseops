import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LawFirmPitchPage, { metadata } from "./page";

function card(title: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: title });
  return heading.closest("article") as HTMLElement;
}

describe("law-firm page product claims", () => {
  it("keeps a distinct canonical and description", () => {
    expect(metadata.alternates).toEqual({ canonical: "/law-firms" });
    expect(metadata.description).toContain("IP dockets");
  });

  it("states the IP, teams, redline, court-sync and mobile limits", () => {
    render(<LawFirmPitchPage />);
    expect(card("IP workspace availability")).toHaveTextContent("There is no live IP India or WIPO feed.");
    expect(card("IP workspace availability")).toHaveTextContent("adds it to a workspace's plan on request");
    expect(card("Trademark journal watch")).toHaveTextContent("through manual intake");
    expect(card("Controlled IP documents")).toHaveTextContent("lists every record that still relies on it");
    expect(card("Contracts and playbooks")).toHaveTextContent("tracked changes it cannot display");
    expect(card("Teams and matter visibility")).toHaveTextContent("does not yet grant extra permissions");
    expect(card("Court sync for six courts")).toHaveTextContent("Madras and Telangana High Courts");
    expect(card("Ask this Workspace")).toHaveTextContent("recorded in the audit log");
    expect(card("Mobile app — development candidate")).toHaveTextContent(
      "not yet in the App Store or Google Play",
    );
  });

  it("drops internal identifiers from the portal copy", () => {
    render(<LawFirmPitchPage />);
    const copy = document.body.textContent ?? "";
    expect(copy).not.toMatch(/MatterPortalGrant|\/portal\/oc/);
  });
});
