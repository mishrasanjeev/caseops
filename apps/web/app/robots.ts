import type { MetadataRoute } from "next";

import { siteConfig } from "@/lib/site";

// Explicit allow-list for every crawler the product wants indexed.
// The one wildcard rule at the end keeps the door open for anything
// else, but named crawlers get a clean allow + disallow pair so
// search-console and LLM-crawler tools can confirm their access.
//
// Crawlers we care about (2026 list):
//   - Google: Googlebot, Googlebot-Image, Googlebot-News,
//     Google-Extended (Gemini training signal)
//   - Microsoft: Bingbot
//   - OpenAI: GPTBot, ChatGPT-User, OAI-SearchBot
//   - Anthropic: ClaudeBot, anthropic-ai, Claude-Web
//   - Perplexity: PerplexityBot
//   - Meta AI: Meta-ExternalAgent, FacebookBot
//   - Common Crawl: CCBot
//   - DuckDuckGo: DuckDuckBot
//   - Applebot (Siri / Apple Intelligence)
//   - Amazon: Amazonbot
// App and API routes stay disallowed. The public sign-in page must be
// crawlable so engines can read its noindex; robots blocking can index a URL
// without fetching it. Authentication remains the private-data boundary.
const ALLOW_ALL_UA = [
  "*",
  "Googlebot",
  "Googlebot-Image",
  "Googlebot-News",
  "Google-Extended",
  "Bingbot",
  "GPTBot",
  "ChatGPT-User",
  "OAI-SearchBot",
  "ClaudeBot",
  "anthropic-ai",
  "Claude-Web",
  "PerplexityBot",
  "Meta-ExternalAgent",
  "FacebookBot",
  "CCBot",
  "DuckDuckBot",
  "Applebot",
  "Amazonbot",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: ALLOW_ALL_UA.map((ua) => ({
      userAgent: ua,
      allow: "/",
      disallow: ["/app", "/app/", "/api/"],
    })),
    sitemap: `${siteConfig.url}/sitemap.xml`,
    host: siteConfig.url,
  };
}
