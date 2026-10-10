export const siteConfig = {
  name: "CaseOps",
  tagline: "The matter-native legal operating system.",
  description:
    "CaseOps is matter management software for Indian law firms and legal teams, connecting hearings, notices, source-backed drafting, contracts, and billing.",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "https://caseops.ai",
  appUrl: process.env.NEXT_PUBLIC_APP_URL ?? "https://caseops.ai/app",
  author: "Sanjeev Kumar",
  publisher: "Orchestrum Technologies LLP",
  ownership: {
    legalOwner: "Orchestrum Technologies LLP",
    inventorOwner: "Sanjeev Kumar",
    emails: ["sanjeev@orchestrum.in", "mishra.sanjeev@gmail.com"],
  },
  locale: "en_IN",
  contact: {
    email: "sanjeev@orchestrum.in",
    sales: "sanjeev@orchestrum.in",
    support: "support@caseops.ai",
    founder: "sanjeev@orchestrum.in",
    alternateOwner: "mishra.sanjeev@gmail.com",
  },
  nav: {
    primary: [
      { label: "Product", href: "#product" },
      { label: "Pricing", href: "/pricing" },
      { label: "Law firms", href: "/law-firms" },
      { label: "General counsels", href: "/general-counsels" },
      { label: "Solo lawyers", href: "/solo-lawyers" },
      { label: "Guide", href: "/guide" },
    ],
    footer: {
      Product: [
        { label: "Matter Cockpit", href: "/#product" },
        { label: "Notices", href: "/#product" },
        { label: "Conflict checks", href: "/#product" },
        { label: "Research", href: "/#product" },
        { label: "Drafting Studio", href: "/#product" },
        { label: "Hearing Prep", href: "/#product" },
        { label: "Case tracking", href: "/#product" },
        { label: "Matter billing", href: "/#product" },
      ],
      Company: [
        { label: "For law firms", href: "/law-firms" },
        { label: "For general counsels", href: "/general-counsels" },
        { label: "For solo lawyers", href: "/solo-lawyers" },
        { label: "User guide", href: "/guide" },
        { label: "Matter management checklist", href: "/resources/legal-matter-management-india" },
        { label: "Request a conversation", href: "/demo/guide" },
      ],
      Trust: [
        { label: "Security", href: "/#security" },
        { label: "Multi-tenancy", href: "/#security" },
        { label: "AI governance", href: "/#security" },
      ],
    },
  },
} as const;

export type SiteConfig = typeof siteConfig;
