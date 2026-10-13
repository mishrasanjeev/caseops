import { render, screen, within } from "@testing-library/react";
import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import sitemap from "@/app/sitemap";
import { siteConfig } from "@/lib/site";

import SourceGroundedLegalRecommendationsPage, { metadata } from "./page";

vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers({ "x-nonce": "article-test-nonce" })),
}));

const path = "/resources/source-grounded-legal-recommendations";
const title = "Source-grounded recommendations for law firms";

describe("source-grounded recommendations public article", () => {
  it("has article metadata with one distinct canonical buyer intent", () => {
    expect(metadata.title).toBe(title);
    expect(metadata.description).toMatch(/matter context, supporting citations, missing facts/i);
    expect(metadata.alternates).toEqual({ canonical: path });
    expect(metadata.openGraph).toMatchObject({
      type: "article",
      url: `${siteConfig.url}${path}`,
      title,
      description: metadata.description,
    });
  });

  it("keeps the nonce, headline and visible description in exact Article JSON-LD parity", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getByText(String(metadata.description), { exact: true })).toBeInTheDocument();

    const script = document.querySelector("#source-grounded-recommendations-article-jsonld");
    expect(script).toHaveAttribute("nonce", "article-test-nonce");
    const article = JSON.parse(script!.textContent!) as Record<string, unknown>;
    expect(article).toMatchObject({
      "@context": "https://schema.org",
      "@type": "Article",
      headline: title,
      description: metadata.description,
      mainEntityOfPage: `${siteConfig.url}${path}`,
      inLanguage: "en-IN",
      author: { "@type": "Organization", name: siteConfig.ownership.legalOwner },
      publisher: { "@type": "Organization", name: siteConfig.ownership.legalOwner, url: siteConfig.url },
    });
    expect(article).not.toHaveProperty("datePublished");
    expect(article).not.toHaveProperty("dateModified");
  });

  it("describes all five source and lawyer-decision steps without automatic external action", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    const workflow = document.querySelector("#workflow")!;
    expect(within(workflow as HTMLElement).getAllByRole("listitem")).toHaveLength(5);
    expect(workflow).toHaveTextContent("supporting citations");
    expect(workflow).toHaveTextContent("assumptions and missing facts");
    expect(workflow).toHaveTextContent("accept an option, reject the recommendation or defer it");
    expect(workflow).toHaveTextContent("Recording a decision is not a court filing, client communication");
  });

  it("requires source verification and makes incomplete evidence and outcome limits explicit", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    expect(document.querySelector("#workflow")).toHaveTextContent("generation may be refused");
    const review = document.querySelector("#source-checks");
    expect(review).toHaveTextContent("Generated output can contain legal or factual errors");
    expect(review).toHaveTextContent("cannot establish that every proposition is correct");
    expect(review).toHaveTextContent("A confidence label is not a probability of winning a case");
    expect(review).toHaveTextContent("The lawyer must verify each authority, quotation and material fact");
    expect(review).toHaveTextContent("not legal advice");
  });

  it("qualifies tenant, matter, ethical-wall and policy access rather than claiming universal access", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    const access = document.querySelector("#controlled-access");
    expect(access).toHaveTextContent("tenant-private work");
    expect(access).toHaveTextContent("matter-level access restrictions alongside role capabilities");
    expect(access).toHaveTextContent("ethical wall");
    expect(access).toHaveTextContent("Tenant AI policy and available source coverage");
  });

  it("does not publish model identities, commercial figures or absolute safety promises", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    const copy = `${screen.getByRole("main").textContent} ${JSON.stringify(metadata)} ${
      document.querySelector("#source-grounded-recommendations-article-jsonld")!.textContent
    }`;
    expect(copy).not.toMatch(/\b(?:gpt[\w.-]*|claude|gemini|llama|mistral|deepseek|qwen|voyage[\w.-]*|bge[\w.-]*)\b/i);
    expect(copy).not.toMatch(/hallucination[- ]free|guaranteed (?:win|success|outcome)|100% (?:accuracy|correctness)|\u20b9|\$\d|unlimited (?:AI|usage)/i);
  });

  it("registers one sitemap/footer route and offers only read-only article links with complete contents", async () => {
    render(await SourceGroundedLegalRecommendationsPage());
    expect(sitemap().filter((entry) => entry.url === `${siteConfig.url}${path}`)).toHaveLength(1);
    expect(siteConfig.nav.footer.Company.filter((entry) => entry.href === path)).toHaveLength(1);
    const article = screen.getByRole("article");
    expect(within(article).getByRole("link", { name: "product guide" })).toHaveAttribute("href", "/guide");
    expect(within(article).getByRole("link", { name: "matter management checklist" })).toHaveAttribute(
      "href", "/resources/legal-matter-management-india",
    );
    expect(article.querySelectorAll("form, input, textarea")).toHaveLength(0);
    expect(article.querySelectorAll('a[href^="/demo"]')).toHaveLength(0);
    expect(document.querySelectorAll('script[src*="googletagmanager"], script[src*="google-analytics"]')).toHaveLength(0);
    expect(article.querySelector("#team-checklist ul")!.children).toHaveLength(5);

    const links = within(screen.getByRole("navigation", { name: "On this page" })).getAllByRole("link");
    const sections = Array.from(article.querySelectorAll("section[id]"), (section) => section.id);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(sections.map((id) => `#${id}`));
    expect(new Set(sections).size).toBe(sections.length);
  });

  it("does not invent a shared nonce when the request header is absent", async () => {
    vi.mocked(headers).mockResolvedValueOnce(new Headers());
    render(await SourceGroundedLegalRecommendationsPage());
    expect(document.querySelector("#source-grounded-recommendations-article-jsonld")).not.toHaveAttribute("nonce");
  });
});
