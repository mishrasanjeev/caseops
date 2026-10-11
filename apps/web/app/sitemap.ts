import type { MetadataRoute } from "next";

import { siteConfig } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteConfig.url.replace(/\/$/, "");
  // List only canonical, indexable HTML. A build timestamp is not a content
  // modification date, so omit lastModified until it can be maintained honestly.
  const paths = [
    "/",
    "/guide",
    "/pricing",
    "/law-firms",
    "/general-counsels",
    "/solo-lawyers",
    "/resources/legal-matter-management-india",
    "/resources/source-grounded-legal-recommendations",
  ];
  return paths.map((path) => ({ url: `${base}${path}` }));
}
