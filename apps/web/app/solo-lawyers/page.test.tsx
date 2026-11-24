import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SoloLawyersPage, { metadata } from "./page";

function card(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("article") as HTMLElement;
}

describe("solo-lawyer page product claims", () => {
  it("keeps a distinct canonical", () => {
    expect(metadata.alternates).toEqual({ canonical: "/solo-lawyers" });
  });

  it("describes court sync, mobile status and billing without overclaiming", () => {
    render(<SoloLawyersPage />);
    expect(card("Court sync and case tracking")).toHaveTextContent(
      "Supreme Court of India and the Delhi, Bombay, Karnataka, Madras and Telangana High Courts",
    );
    expect(card("iPad-ready in court")).toHaveTextContent("not yet in the App Store or Google Play");
    expect(card("Workspace-private notes")).toHaveTextContent("private to your workspace");
    const copy = document.body.textContent ?? "";
    expect(copy).not.toMatch(/Monthly report exports|Annotations travel with the matter|Get paid\./);
    expect(copy).not.toMatch(/manual today, automated incrementally/);
  });
});
