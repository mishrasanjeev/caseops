import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformLinkBoundary, usePlatformLink } from "./PlatformLinkBoundary";

function Consumer({ inspect }: { inspect: (value: string | null | undefined) => void }) {
  const link = usePlatformLink();
  inspect(link?.token);
  return <p>Account security</p>;
}

describe("platform link boundary", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));
  it.each(["#token=ephemeral", "#token=ephemeral&mode=reset"])("scrubs %s before child rendering without rendering the token", (suffix) => {
    window.history.replaceState(null, "", `/platform/security${suffix}`);
    const inspect = vi.fn(() => {
      expect(window.location.search).toBe("");
      expect(window.location.hash).toBe("");
    });
    render(<StrictMode><PlatformLinkBoundary><Consumer inspect={inspect} /></PlatformLinkBoundary></StrictMode>);
    expect(inspect).toHaveBeenCalledWith("ephemeral");
    expect(screen.getByText("Account security")).toBeVisible();
    expect(document.body.textContent).not.toContain("ephemeral");
  });
  it("does not expose an ambiguous credential to child controls", () => {
    window.history.replaceState(null, "", "/platform/security?token=first#token=second");
    const inspect = vi.fn();
    render(<PlatformLinkBoundary><Consumer inspect={inspect} /></PlatformLinkBoundary>);
    expect(inspect).toHaveBeenCalledWith(null);
    expect(window.location.href).not.toMatch(/first|second/);
  });
  it.each(["setup", "reset-password"])("consumes a fresh same-page hash on an already mounted %s boundary", async (page) => {
    window.history.replaceState(null, "", `/platform/${page}#token=old-link`);
    const inspect = vi.fn(() => { expect(window.location.hash).toBe(""); });
    render(<StrictMode><PlatformLinkBoundary><Consumer inspect={inspect} /></PlatformLinkBoundary></StrictMode>);
    expect(inspect).toHaveBeenLastCalledWith("old-link");
    act(() => { window.location.hash = "token=fresh-link"; });
    await waitFor(() => expect(inspect).toHaveBeenLastCalledWith("fresh-link"));
    expect(window.location.hash).toBe("");
    expect(document.body.textContent).not.toMatch(/old-link|fresh-link/);
  });
  it("handles history plus hash events once and rejects a later ambiguous fragment", () => {
    window.history.replaceState(null, "", "/platform/setup#token=old-link");
    const inspect = vi.fn();
    render(<PlatformLinkBoundary><Consumer inspect={inspect} /></PlatformLinkBoundary>);
    act(() => {
      window.history.pushState(null, "", "/platform/setup#token=fresh-link");
      window.dispatchEvent(new PopStateEvent("popstate"));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(inspect).toHaveBeenLastCalledWith("fresh-link");
    expect(window.location.hash).toBe("");
    act(() => {
      window.history.pushState(null, "", "/platform/setup?token=unsafe#token=ambiguous");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(inspect).toHaveBeenLastCalledWith(null);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
  });
});
