import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { marketingFaqs } from "@/lib/marketing-content";

import LandingPage from "./page";

vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers({ "x-nonce": "test-nonce" })),
}));

describe("landing page product claims", () => {
  // The IP availability strip fetches a public catalogue; keep the test offline.
  beforeEach(() => vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); })));
  afterEach(() => vi.unstubAllGlobals());

  it("describes the shipped IP, assistant, portal, redline and court-sync workflows with their limits", async () => {
    render(await LandingPage());
    const product = document.querySelector("#product") as HTMLElement;
    const card = (name: string) =>
      screen.getByRole("heading", { level: 3, name }).closest("article") as HTMLElement;

    expect(within(product).getByRole("heading", { name: "Intake & Conflict Checks" })).toBeInTheDocument();
    expect(card("IP Workspace")).toHaveTextContent("there is no live IP India or WIPO feed");
    expect(card("IP Workspace")).toHaveTextContent("Added to a plan on request.");
    expect(card("Ask this Workspace")).toHaveTextContent("opening a citation rechecks access and is audited");
    expect(card("Ask this Workspace")).toHaveTextContent("Off until a workspace owner enables it");
    expect(card("Client & Counsel Portals")).toHaveTextContent("only the matters and IP records you share");
    expect(card("Contract & Playbooks")).toHaveTextContent("warns when a file holds changes it cannot display");
    expect(card("Case Tracking & Ops")).toHaveTextContent(
      "Supreme Court and the Delhi, Bombay, Karnataka, Madras and Telangana High Courts",
    );
    expect(card("Trust Plane")).toHaveTextContent("teams with optional team-scoped matter visibility");
    expect(product.textContent).not.toMatch(/realization|realisation/i);
    expect(document.body.innerHTML).not.toMatch(/@gmail\.com/i);
  });

  it("keeps the FAQ JSON-LD in parity with the visible FAQ, including the new limits", async () => {
    render(await LandingPage());
    const script = document.querySelector('script[type="application/ld+json"]');
    expect(script).toHaveAttribute("nonce", "test-nonce");
    const faq = JSON.parse(script!.textContent!) as { mainEntity: { name: string }[] };
    expect(faq.mainEntity.map((item) => item.name)).toEqual(marketingFaqs.map((item) => item.q));
    for (const question of [
      "Does the IP workspace connect to IP India or WIPO?",
      "Which courts does court sync cover?",
      "Is there a mobile app?",
    ]) {
      expect(screen.getByRole("button", { name: question })).toBeInTheDocument();
    }
    const mobile = marketingFaqs.find((item) => item.q === "Is there a mobile app?");
    expect(mobile?.a).toContain("not yet in the App Store or Google Play");
  });
});
