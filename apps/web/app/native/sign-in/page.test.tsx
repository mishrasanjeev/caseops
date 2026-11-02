import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ loadPolicy: vi.fn() }));
vi.mock("@/lib/native-link-policy.server", () => ({ loadNativeLinkPolicy: mocks.loadPolicy }));

vi.mock("./NativeSignIn", () => ({
  NativeSignIn: () => <main aria-label="Connect the CaseOps app" />,
}));

import NativeSignInPage, { dynamic, metadata } from "./page";

describe("native sign-in page boundary", () => {
  beforeEach(() => {
    mocks.loadPolicy.mockReset();
    mocks.loadPolicy.mockReturnValue({ mode: "disabled" });
  });
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

  it.each([
    { mode: "disabled" },
    { mode: "local", redirectUri: "caseops://oauth/callback" },
    { mode: "https", redirectUri: "https://native.invalid/native/oauth/callback", configSha256: "a".repeat(64) },
  ])("passes only the exact server-admitted public policy to the client, including disabled mode %#", (policy) => {
    mocks.loadPolicy.mockReturnValue(policy);
    const page = NativeSignInPage();
    expect(page.type).toBe(Suspense);
    expect(page.props.children.props.policy).toBe(policy);
    expect(mocks.loadPolicy).toHaveBeenCalledExactlyOnceWith();
  });
});
