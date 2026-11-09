import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import rules from "./approved-rules.json";
import WorkspaceUsePage, { metadata } from "./page";

describe("public CaseOps workspace use rules", () => {
  it("publishes the canonical policy URL and title", () => {
    expect(metadata.title).toBe(rules.title);
    expect(metadata.alternates).toEqual({ canonical: "https://caseops.ai/workspace-use" });
  });

  it("renders every approved section with the current version and reporting contacts", () => {
    render(<WorkspaceUsePage />);

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main");
    expect(screen.getByRole("link", { name: /^Skip to main content$/ })).toHaveAttribute("href", "#main");
    expect(within(main).getByRole("heading", { level: 1, name: rules.title })).toBeVisible();
    expect(within(main).getByText(rules.version, { exact: true })).toHaveAttribute("datetime", rules.version);
    expect(within(main).getByText(rules.intro, { exact: true })).toBeVisible();

    const article = within(main).getByRole("article", { name: rules.title });
    expect(within(article).getAllByRole("heading", { level: 2 }).map((heading) => heading.id)).toEqual(
      rules.sections.map(({ id }) => id),
    );
    for (const section of rules.sections) {
      const region = within(article).getByRole("region", { name: section.title });
      expect(within(region).getByText(section.text, { exact: true })).toBeVisible();
    }

    const support = within(article).getByRole("navigation", { name: /^Related policy and support$/ });
    expect(within(support).getByRole("link", { name: rules.contactEmail })).toHaveAttribute(
      "href", `mailto:${rules.contactEmail}`,
    );
    expect(within(support).getByRole("link", { name: /^Privacy policy$/ })).toHaveAttribute("href", "/privacy");
  });
});
