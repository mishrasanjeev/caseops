export const siteConfig = {
  name: "CaseOps",
  tagline: "The matter-native legal operating system.",
  description:
    "CaseOps unifies matter management, legal research, drafting, hearing prep, contracts, outside counsel, and billing into one citation-grounded workspace for Indian law firms and corporate legal teams.",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "https://caseops.ai",
  appUrl: process.env.NEXT_PUBLIC_APP_URL ?? "https://caseops.ai/app",
  keywords: [
    "legal operating system",
    "legal software India",
    "law firm software",
    "matter management",
    "legal research platform",
    "AI legal drafting",
    "hearing preparation",
    "contract review",
    "legal operations",
    "general counsel software",
    "litigation management",
    "outside counsel management",
    "Pine Labs legal billing",
    "legal AI India",
    "case management software",
  ],
  author: "CaseOps",
  twitter: "@caseops",
  locale: "en_IN",
  contact: {
    email: "hello@caseops.ai",
    sales: "sales@caseops.ai",
    support: "support@caseops.ai",
  },
  nav: {
    primary: [
      { label: "Product", href: "#product" },
      { label: "Workflows", href: "#workflows" },
      { label: "Security", href: "#security" },
      { label: "Pricing", href: "#pricing" },
      { label: "FAQ", href: "#faq" },
    ],
    footer: {
      Product: [
        { label: "Matter Cockpit", href: "#product" },
        { label: "Research", href: "#product" },
        { label: "Drafting Studio", href: "#product" },
        { label: "Hearing Prep", href: "#product" },
        { label: "Contracts", href: "#product" },
        { label: "Recommendations", href: "#product" },
      ],
      Company: [
        { label: "About", href: "#" },
        { label: "Careers", href: "#" },
        { label: "Contact", href: "mailto:hello@caseops.ai" },
      ],
      Trust: [
        { label: "Security", href: "#security" },
        { label: "Multi-tenancy", href: "#security" },
        { label: "AI governance", href: "#security" },
      ],
      Legal: [
        { label: "Privacy", href: "#" },
        { label: "Terms", href: "#" },
        { label: "DPA", href: "#" },
      ],
    },
  },
} as const;

export type SiteConfig = typeof siteConfig;
