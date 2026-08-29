import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { siteConfig } from "@/lib/site";

// Hermetic font loading via @fontsource — fonts are vendored as
// npm-installed woff2 assets, not fetched from Google Fonts at
// build time. Codex's 2026-04-19 E2E pass surfaced that
// next/font/google made `npm run build:web` fail in any
// network-restricted environment (CI sandbox, locked-down
// enterprise build server, disaster recovery). The @fontsource
// packages are SIL OFL-licensed and ship as part of the bundle,
// so the build succeeds offline.
//
// The font CSS files declare @font-face with the same names the
// fallback chain in globals.css points at ("Atkinson Hyperlegible",
// "Libre Caslon Text", "JetBrains Mono"), so no other code changes
// are needed.
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/libre-caslon-text/400.css";
import "@fontsource/libre-caslon-text/700.css";
import "@fontsource/libre-caslon-text/400-italic.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import { GoogleAnalytics } from "@/components/analytics/GoogleAnalytics";
import { ProductOwnershipNotice } from "@/components/legal/ProductOwnershipNotice";

import "./globals.css";

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: siteConfig.ownership.legalOwner,
  legalName: siteConfig.ownership.legalOwner,
  alternateName: siteConfig.name,
  url: siteConfig.url,
  logo: `${siteConfig.url}/icon`,
  email: [...siteConfig.ownership.emails],
  brand: { "@type": "Brand", name: siteConfig.name },
  contactPoint: siteConfig.ownership.emails.map((email) => ({
    "@type": "ContactPoint",
    contactType: "owner",
    email,
  })),
  sameAs: [],
  foundingDate: "2026",
  areaServed: { "@type": "Country", name: "India" },
};

const softwareJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: siteConfig.name,
  applicationCategory: "BusinessApplication",
  applicationSubCategory: "Legal Software",
  operatingSystem: "Web",
  description: siteConfig.description,
  creator: {
    "@type": "Person",
    name: siteConfig.ownership.inventorOwner,
    email: [...siteConfig.ownership.emails],
    jobTitle: "Inventor and Owner",
  },
  publisher: {
    "@type": "Organization",
    name: siteConfig.ownership.legalOwner,
  },
  copyrightHolder: {
    "@type": "Organization",
    name: siteConfig.ownership.legalOwner,
  },
  offers: {
    "@type": "AggregateOffer",
    priceCurrency: "INR",
    offerCount: 3,
    url: `${siteConfig.url}/pricing`,
    availability: "https://schema.org/LimitedAvailability",
    description: "Versioned plan catalog; assisted activation while production payments remain UAT-gated.",
  },
  featureList: [
    "Matter management",
    "Pre-engagement conflict checks",
    "Received and sent notice tracking",
    "AI-assisted legal drafting with citation grounding",
    "Hearing pack generation",
    "Authority research over Supreme Court + High Court corpus",
    "Contract clause and obligation extraction",
    "Outside counsel management and spend tracking",
    "Invoice generation and time tracking",
    "Tenant isolation and matter-level access controls",
  ],
  inLanguage: "en",
};

// WebSite + SearchAction — tells Google + LLM crawlers the site has
// an internal search and what the canonical URL shape is. The
// authenticated search lives at /app/research; we surface its shape
// here even though it's gated behind login so structured-data
// consumers understand the site layout.
const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: siteConfig.name,
  url: siteConfig.url,
  description: siteConfig.description,
  inLanguage: "en",
  publisher: { "@type": "Organization", name: siteConfig.ownership.legalOwner },
};

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: `${siteConfig.name} — ${siteConfig.tagline}`,
    template: `%s — ${siteConfig.name}`,
  },
  description: siteConfig.description,
  keywords: [...siteConfig.keywords],
  applicationName: siteConfig.name,
  authors: [
    { name: siteConfig.ownership.inventorOwner },
    { name: siteConfig.ownership.legalOwner },
  ],
  creator: siteConfig.author,
  publisher: siteConfig.publisher,
  other: {
    "product-owner": siteConfig.ownership.legalOwner,
    "inventor-owner": siteConfig.ownership.inventorOwner,
    "owner-contact": siteConfig.ownership.emails.join(", "),
  },
  category: "technology",
  alternates: {
    canonical: "/",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
  openGraph: {
    type: "website",
    locale: siteConfig.locale,
    url: siteConfig.url,
    siteName: siteConfig.name,
    title: `${siteConfig.name} — ${siteConfig.tagline}`,
    description: siteConfig.description,
  },
  twitter: {
    card: "summary_large_image",
    title: `${siteConfig.name} — ${siteConfig.tagline}`,
    description: siteConfig.description,
    creator: siteConfig.twitter,
  },
  // icons removed — app/icon.tsx is a Next file-based icon convention and
  // is auto-served at /icon (PNG). Declaring it here as /icon.png creates
  // a broken link: Next emits /icon, not /icon.png.
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1220" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script
          nonce={nonce}
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationJsonLd) }}
        />
        <script
          nonce={nonce}
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareJsonLd) }}
        />
        <script
          nonce={nonce}
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
        {children}
        <ProductOwnershipNotice />
        <GoogleAnalytics nonce={nonce} />
      </body>
    </html>
  );
}
