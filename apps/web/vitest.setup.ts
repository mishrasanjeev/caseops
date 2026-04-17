import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

// next/navigation is a runtime boundary; stub it so components that call
// useRouter / useParams / useSearchParams don't crash outside of a Next
// request context.
vi.mock("next/navigation", () => {
  const push = vi.fn();
  const replace = vi.fn();
  const refresh = vi.fn();
  const back = vi.fn();
  const forward = vi.fn();
  return {
    useRouter: () => ({ push, replace, refresh, back, forward }),
    useParams: () => ({}),
    useSearchParams: () => new URLSearchParams(),
    usePathname: () => "/",
    redirect: vi.fn(),
  };
});

// Next's font-loader shims: tests don't need real font files.
vi.mock("next/font/google", () => ({
  Atkinson_Hyperlegible: () => ({ variable: "" }),
  Libre_Caslon_Text: () => ({ variable: "" }),
  JetBrains_Mono: () => ({ variable: "" }),
}));

// Keep ResizeObserver + matchMedia available inside jsdom for Radix
// primitives and TanStack Table.
if (typeof window !== "undefined") {
  window.ResizeObserver =
    window.ResizeObserver ||
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };

  if (!window.matchMedia) {
    window.matchMedia = (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }

  // Radix Select uses PointerEvent.hasPointerCapture which jsdom hasn't
  // implemented — stub it to keep the Select trigger happy in tests.
  if (typeof Element !== "undefined") {
    Element.prototype.hasPointerCapture =
      Element.prototype.hasPointerCapture || (() => false);
    Element.prototype.releasePointerCapture =
      Element.prototype.releasePointerCapture || (() => {});
    // scrollIntoView is used by Radix focus management; jsdom no-op.
    Element.prototype.scrollIntoView =
      Element.prototype.scrollIntoView || (() => {});
  }
}
