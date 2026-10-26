import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./NativeSignIn", () => ({
  NativeSignIn: () => <main aria-label="Connect the CaseOps app" />,
}));

import NativeSignInPage, { dynamic, metadata } from "./page";

describe("native sign-in page boundary", () => {
  it("renders the browser handoff inside its search-parameter suspense boundary", () => {
    const page = NativeSignInPage();
    expect(page.type).toBe(Suspense);
    render(page);
    expect(screen.getByRole("main", { name: "Connect the CaseOps app" })).toBeInTheDocument();
  });

  it("keeps one-time handoff navigation dynamic, unindexed and without referrers", () => {
    expect(dynamic).toBe("force-dynamic");
    expect(metadata).toEqual({
      title: "Connect the CaseOps app",
      robots: { index: false, follow: false },
      referrer: "no-referrer",
    });
  });
});
