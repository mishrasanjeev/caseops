import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  can: () => true,
  useResolvedCapabilities: () => null,
  useRole: () => "owner",
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/app" }));

import { Sidebar } from "@/components/app/Sidebar";

// Nov 27 row 9. jsdom has no layout, so the geometry (sidebar stays at top 0
// while the page scrolls; the nav scrolls on its own) is proven by
// tests/e2e/nova-2026-11-27-matter.spec.ts. This pins the CSS contract that
// geometry depends on, so a refactor cannot silently drop it.
describe("Sidebar independent scrolling contract", () => {
  it("pins the desktop sidebar to the viewport and scrolls only its nav", () => {
    render(<Sidebar />);
    const aside = screen.getByTestId("app-sidebar");
    for (const token of ["fixed", "inset-y-0", "left-0", "h-dvh", "md:flex"]) {
      expect(aside.className.split(/\s+/)).toContain(token);
    }
    // The fixed sidebar's width is held in the shell row by a spacer.
    const spacer = screen.getByTestId("app-sidebar-spacer");
    expect(spacer.className.split(/\s+/)).toEqual(expect.arrayContaining(["w-64", "shrink-0", "md:block"]));
    const nav = screen.getByTestId("sidebar-nav-scroller");
    for (const token of ["min-h-0", "overflow-y-auto", "overscroll-contain"]) {
      expect(nav.className.split(/\s+/)).toContain(token);
    }
  });

  it("keeps the app shell from becoming a scroll container of its own", () => {
    const layout = readFileSync(path.join(__dirname, "../../app/app/layout.tsx"), "utf8");
    const shell = layout.match(/<div data-app-shell className="(flex min-h-screen [^"]*)">\s*<Sidebar \/>/);
    expect(shell?.[1]).toBeDefined();
    // overflow-x-hidden computes overflow-y to auto and makes the wrapper a
    // scroll container that can trap the page scroll; clip does not.
    expect(shell?.[1]).toContain("overflow-x-clip");
    expect(shell?.[1]).not.toMatch(/overflow-(?:x-|y-)?(?:hidden|auto|scroll)/);
    // The site footer after the shell is kept clear of the fixed sidebar.
    const css = readFileSync(path.join(__dirname, "../../app/globals.css"), "utf8");
    expect(css).toMatch(
      /body:has\(\[data-app-shell\]\) > aside\[aria-label="CaseOps product ownership"\] \{\s*padding-left: 16rem;/,
    );
  });
});
