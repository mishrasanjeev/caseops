import { render, screen } from "@testing-library/react";
import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import LegalMatterManagementIndiaPage, { metadata } from "./page";

vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers({ "x-nonce": "test-nonce" })),
}));

describe("legal matter management resource", () => {
  it("has a unique canonical and a useful search description", () => {
    expect(metadata.alternates).toEqual({ canonical: "/resources/legal-matter-management-india" });
    expect(metadata.description).toMatch(/Indian law firms.*case identity.*hearings/i);
  });

  it("offers a concrete checklist without guaranteeing court coverage", async () => {
    render(await LegalMatterManagementIndiaPage());
    expect(screen.getByRole("heading", { level: 1, name: "Legal matter management in India" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Seven checks to run in a demo" })).toBeInTheDocument();
    expect(screen.getByText(/does not guarantee that a provider has access to every court/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "product guide" })).toHaveAttribute("href", "/guide");
    expect(document.querySelector("#matter-management-article-jsonld")).toHaveAttribute("nonce", "test-nonce");
    expect(headers).toHaveBeenCalled();
  });
});
