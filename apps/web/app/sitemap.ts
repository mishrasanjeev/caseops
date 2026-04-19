import type { MetadataRoute } from "next";

import { siteConfig } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const base = siteConfig.url.replace(/\/$/, "");
  // Only public marketing pages belong here. /sign-in and /app are
  // disallowed in robots.ts, so listing them here would contradict.
  return [
    { url: `${base}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${base}/llms.txt`, lastModified: now, changeFrequency: "weekly", priority: 0.5 },
    { url: `${base}/llms-full.txt`, lastModified: now, changeFrequency: "weekly", priority: 0.5 },
  ];
}
