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

import "./globals.css";

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: siteConfig.name,
  url: siteConfig.url,
  logo: `${siteConfig.url}/icon`,
  email: siteConfig.contact.email,
  sameAs: [],
};

const softwareJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: siteConfig.name,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description: siteConfig.description,
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "INR",
    availability: "https://schema.org/PreOrder",
    description: "Early access pilot",
  },
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
        {children}
      </body>
    </html>
  );
}
