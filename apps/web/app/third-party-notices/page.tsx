import { Download } from "lucide-react";
import type { Metadata } from "next";

import { Footer } from "@/components/marketing/Footer";
import { Nav } from "@/components/marketing/Nav";
import { Container } from "@/components/ui/Container";
import { SkipLink } from "@/components/ui/SkipLink";

import notices from "./notices.json";

export const metadata: Metadata = {
  title: "Third-party notices",
  description: "Original copyright notices and license texts for the listed fonts and software components.",
  alternates: { canonical: "/third-party-notices" },
  robots: { index: false, follow: true, googleBot: { index: false, follow: true } },
  openGraph: {
    type: "website",
    url: "/third-party-notices",
    title: "Third-party notices",
    description: "Original copyright notices and license texts for the listed fonts and software components.",
  },
};

export default function ThirdPartyNoticesPage() {
  return (
    <>
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] py-10">
          <Container>
            <h1 className="font-display text-3xl font-normal leading-tight text-[var(--color-ink)]">
              Third-party notices
            </h1>
            <p className="mt-4 max-w-3xl text-sm leading-relaxed text-[var(--color-ink-2)]">
              Original copyright notices and license texts for the fonts and software
              components listed below. Listed versions identify the package copies
              used for these notices.
            </p>
          </Container>
        </header>
        <Container className="py-10">
          <article className="min-w-0 max-w-3xl divide-y divide-[var(--color-line)] text-[var(--color-ink-2)]">
            {notices.components.map((component) => (
              <section
                key={component.id}
                id={component.id}
                aria-labelledby={`${component.id}-title`}
                className="min-w-0 space-y-4 py-6 first:pt-0"
              >
                <h2 id={`${component.id}-title`} className="text-xl font-semibold text-[var(--color-ink)]">
                  {component.name}
                </h2>
                <p className="break-words text-sm [overflow-wrap:anywhere]">
                  <code>{component.packageName}</code> / Version {component.version}
                </p>
                {component.notices.map((notice) => (
                  <div key={notice.filename} className="min-w-0 space-y-3">
                    <p className="break-words text-xs text-[var(--color-mute)] [overflow-wrap:anywhere]">
                      {notice.license} / Original source: <code>{notice.sourceFile}</code>
                    </p>
                    <a
                      href={`/third-party-notices/${notice.filename}`}
                      download={notice.filename}
                      aria-label={`Download ${component.name} ${notice.license} notice`}
                      className="inline-flex min-h-11 items-center gap-2 text-sm font-medium underline underline-offset-4 hover:text-[var(--color-ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-brand-700)]"
                    >
                      <Download className="h-4 w-4 shrink-0" aria-hidden="true" />
                      Download {notice.license} notice
                    </a>
                    <details className="min-w-0">
                      <summary className="w-fit cursor-pointer py-2 text-sm font-medium underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-brand-700)]">
                        Read full {notice.license} notice
                      </summary>
                      <pre className="mt-3 w-full max-w-[75ch] whitespace-pre-wrap break-words font-mono text-sm leading-relaxed [overflow-wrap:anywhere]">
                        {notice.text}
                      </pre>
                    </details>
                  </div>
                ))}
              </section>
            ))}
          </article>
        </Container>
      </main>
      <Footer />
    </>
  );
}
