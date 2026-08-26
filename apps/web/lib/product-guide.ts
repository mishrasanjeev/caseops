import catalogProjection from "@/lib/product-guide.generated.json";

import type { Capability } from "@/lib/capabilities";

export type ProductGuideNavigationGroup =
  | "overview"
  | "schedule"
  | "casework"
  | "ip"
  | "intel"
  | "admin";

export type ProductGuideSection = {
  id: string;
  title: string;
  summary: string;
  keywords: readonly string[];
  aliases: readonly string[];
};

export type ProductGuideCommand = {
  id: string;
  label: string;
  href: string;
  icon: string;
  group: ProductGuideNavigationGroup;
  summary: string;
  keywords: readonly string[];
  required_capabilities: readonly Capability[];
};

export type ProductGuideCatalog = {
  schema_version: 1;
  corpus_id: string;
  content_version: string;
  display_version: string;
  language: "en-IN";
  canonical_path: "/guide";
  updated_on: string;
  navigation_groups: Record<ProductGuideNavigationGroup, string>;
  sections: readonly ProductGuideSection[];
  commands: readonly ProductGuideCommand[];
};

// The projection gate validates every field, route, capability, and section
// anchor before this data reaches either independently built application.
export const PRODUCT_GUIDE_CATALOG = catalogProjection as ProductGuideCatalog;

export function formatGuideDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}
