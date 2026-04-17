import { Container } from "@/components/ui/Container";
import { siteConfig } from "@/lib/site";

import { Logo } from "./Logo";

export function Footer() {
  const groups = Object.entries(siteConfig.nav.footer);
  return (
    <footer className="border-t border-[var(--color-line)] bg-white py-14">
      <Container>
        <div className="grid gap-10 md:grid-cols-[1.25fr_repeat(4,1fr)]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-[var(--color-mute)]">
              {siteConfig.tagline} Built for Indian law firms and corporate legal teams.
            </p>
            <a
              href={`mailto:${siteConfig.contact.email}`}
              className="mt-4 inline-block text-sm font-medium text-[var(--color-ink-2)] hover:text-[var(--color-ink)]"
            >
              {siteConfig.contact.email}
            </a>
          </div>

          {groups.map(([title, items]) => (
            <div key={title}>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-mute-2)]">
                {title}
              </div>
              <ul className="mt-4 space-y-2.5 text-sm">
                {items.map((it) => (
                  <li key={it.label}>
                    <a
                      href={it.href}
                      className="text-[var(--color-ink-2)] transition-colors hover:text-[var(--color-ink)]"
                    >
                      {it.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-4 border-t border-[var(--color-line)] pt-6 text-xs text-[var(--color-mute-2)] md:flex-row md:items-center">
          <span>
            © {new Date().getFullYear()} {siteConfig.name}. All rights reserved.
          </span>
          <span>Designed for dense, professional legal workflows.</span>
        </div>
      </Container>
    </footer>
  );
}
