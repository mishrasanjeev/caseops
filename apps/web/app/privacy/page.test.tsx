import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import sitemap from "@/app/sitemap";
import { privacyPolicy } from "@/lib/privacy-policy";
import { siteConfig } from "@/lib/site";

import PrivacyPage, { metadata } from "./page";

const exact = (value: string) => new RegExp(`^${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);

describe("public CaseOps privacy policy", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new Error("Privacy rendering must not send requests or telemetry."));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_GA_MEASUREMENT_ID", "G-OFFLINE-PRIVACY-PAGE-GUARD");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("publishes its own exact title, canonical and Open Graph URL", () => {
    expect(metadata.title).toBe("Privacy policy");
    expect(metadata.description).toBe(privacyPolicy.intro);
    expect(metadata.alternates).toEqual({ canonical: "https://caseops.ai/privacy" });
    expect(metadata.openGraph).toMatchObject({ type: "website", title: "Privacy policy", url: "https://caseops.ai/privacy", description: privacyPolicy.intro });
    expect(metadata.robots).toEqual({ index: true, follow: true, googleBot: { index: true, follow: true } });
  });

  it("renders the public policy without a session provider and identifies its operator, version and effective date", () => {
    render(<PrivacyPage />);
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(within(main).getByRole("heading", { level: 1, name: /^Privacy policy$/ })).toBeVisible();
    expect(main).toHaveAttribute("id", "main");
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(within(main).getByText("Orchestrum Technologies LLP", { exact: true })).toBeVisible();
    expect(within(main).getByText("2026-11-03", { exact: true })).toBeVisible();
    expect(within(main).getByText("3 November 2026", { exact: true })).toHaveAttribute("datetime", "2026-11-03");
    expect(within(main).getByText(privacyPolicy.intro, { exact: true })).toBeVisible();
  });

  it("delivers every policy paragraph and bullet in visible sections rather than collapsed or omitted text", () => {
    render(<PrivacyPage />);
    const article = screen.getByRole("article", { name: /^Full privacy policy$/ });
    expect(privacyPolicy.sections.map(({ id }) => id)).toEqual(["scope", "information", "use", "sharing", "ai", "devices", "security", "retention", "account-deletion", "children", "changes", "contact"]);
    expect(within(article).getAllByRole("heading", { level: 2 })).toHaveLength(13);
    for (const section of privacyPolicy.sections) {
      const region = document.getElementById(section.id)!;
      expect(region).toHaveAttribute("aria-labelledby", `${section.id}-title`);
      expect(within(region).getByRole("heading", { level: 2, name: exact(section.title) })).toBeVisible();
      for (const paragraph of section.paragraphs) expect(within(region).getByText(paragraph, { exact: true })).toBeVisible();
      for (const point of section.bullets) expect(within(region).getByText(point, { exact: true })).toBeVisible();
    }
    expect(article.querySelectorAll("details")).toHaveLength(0);
  });

  it("shows the confirmed privacy commitments verbatim without turning a request receipt into completed deletion", () => {
    render(<PrivacyPage />);
    const article = screen.getByRole("article", { name: /^Full privacy policy$/ });
    const summary = document.getElementById("privacy-summary-title")!.parentElement!;
    expect(within(summary).getByText("We do not sell personal data or use it for targeted advertising.", { exact: true })).toBeVisible();
    expect(within(summary).getByText("Private customer content is not used to train shared AI models without explicit opt-in.", { exact: true })).toBeVisible();
    expect(article).toHaveTextContent("A request receipt confirms that the request was received; it does not mean deletion has been completed.");
    expect(article).toHaveTextContent("Service providers processing personal data for us must use it for the agreed service and protect it with at least the same level of protection described in this policy and required by applicable law.");
    expect(article).toHaveTextContent("Before a CaseOps app feature shares personal data with a third-party AI service, our policy is to explain what information will be shared, with whom and for what purpose, and obtain your explicit permission. You can decline that optional processing. This permission is separate from any opt-in to training shared AI models; this privacy policy does not itself provide either permission.");
    expect(article).toHaveTextContent("We do not represent that every processing activity occurs only in India.");
    expect(article).not.toHaveTextContent(/draft policy|approval pending|awaiting approval/i);
  });

  it("binds every contents link, the skip link and the account-deletion shortcut to a real readable target", () => {
    render(<PrivacyPage />);
    const contents = screen.getByRole("navigation", { name: /^Policy contents$/ });
    expect(within(contents).getAllByRole("link")).toHaveLength(12);
    for (const section of privacyPolicy.sections) {
      const link = within(contents).getByRole("link", { name: exact(section.title) });
      expect(link).toHaveAttribute("href", `#${section.id}`);
      expect(link).toHaveClass("min-h-11", "focus-visible:outline");
      expect(document.getElementById(section.id)).toBeVisible();
    }
    expect(screen.getByRole("link", { name: /^Skip to main content$/ })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("link", { name: /^Account deletion$/ })).toHaveAttribute("href", "#account-deletion");
  });

  it("provides the monitored mailbox, keeps the separate demo notice and exposes one footer privacy link", () => {
    render(<PrivacyPage />);
    const main = screen.getByRole("main");
    expect(within(main).getByRole("link", { name: /^sanjeev@orchestrum\.in$/ })).toHaveAttribute("href", "mailto:sanjeev@orchestrum.in");
    expect(within(main).getByRole("link", { name: /^Demo request privacy notice$/ })).toHaveAttribute("href", "/demo/privacy");
    const footer = screen.getByRole("contentinfo");
    const links = within(footer).getAllByRole("link", { name: /^Privacy policy$/ });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/privacy");
    expect(siteConfig.nav.footer.Trust.filter(({ href }) => href === "/privacy")).toEqual([{ label: "Privacy policy", href: "/privacy" }]);
  });

  it("includes exactly one canonical privacy sitemap entry without inventing a modification date", () => {
    const base = siteConfig.url.replace(/\/$/, "");
    expect(sitemap().filter(({ url }) => new URL(url).pathname === "/privacy")).toEqual([{ url: `${base}/privacy` }]);
  });

  it("does not add forms, tracking media or background network activity even with an analytics identifier configured", () => {
    expect(process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID).toBe("G-OFFLINE-PRIVACY-PAGE-GUARD");
    render(<PrivacyPage />);
    expect(document.querySelectorAll("form, input, textarea, iframe")).toHaveLength(0);
    expect(document.querySelector('script[src],img[src*="google-analytics"],img[src*="googletagmanager"]')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the route a static public content component without new API, session or raw-HTML execution paths", () => {
    const source = readFileSync(path.join(process.cwd(), "app/privacy/page.tsx"), "utf8");
    expect(source).not.toMatch(/useSession|useQuery|useMutation|apiRequest|\bfetch\s*\(|redirect\s*\(|dangerouslySetInnerHTML|["']use client["']/);
    expect(source).not.toMatch(/<form\b|<input\b|<textarea\b|<iframe\b/);
  });
});
