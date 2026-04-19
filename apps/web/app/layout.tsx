import type { Metadata, Viewport } from "next";
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

import { GoogleAnalytics } from "@/components/analytics/GoogleAnalytics";

import "./globals.css";

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: siteConfig.name,
  url: siteConfig.url,
  logo: `${siteConfig.url}/icon`,
  email: siteConfig.contact.email,
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
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "INR",
    availability: "https://schema.org/PreOrder",
    description: "Early access pilot",
  },
  featureList: [
    "Matter management",
    "AI-assisted legal drafting with citation grounding",
    "Hearing pack generation",
    "Authority research over Supreme Court + High Court corpus",
    "Contract clause and obligation extraction",
    "Outside counsel management and spend tracking",
    "Invoice generation and time tracking",
    "Tenant isolation and ethical walls for multi-party matters",
  ],
  inLanguage: ["en", "hi"],
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
  publisher: { "@type": "Organization", name: siteConfig.name },
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
  authors: [{ name: siteConfig.author }],
  creator: siteConfig.author,
  publisher: siteConfig.author,
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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationJsonLd) }}
        />
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareJsonLd) }}
        />
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
        {children}
        <GoogleAnalytics />
      </body>
    </html>
  );
}
