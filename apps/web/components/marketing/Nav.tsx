"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";
import { cn } from "@/lib/cn";
import { siteConfig } from "@/lib/site";

import { Logo } from "./Logo";

export function Nav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <header
      className={cn(
        "sticky top-0 z-50 border-b backdrop-blur-md transition-colors",
        scrolled
          ? "border-[var(--color-line)] bg-white/85"
          : "border-transparent bg-white/60",
      )}
    >
      <Container className="flex h-16 items-center justify-between">
        <Logo />

        <nav className="hidden md:flex md:items-center md:gap-8" aria-label="Primary">
          {siteConfig.nav.primary.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm font-medium text-[var(--color-ink-2)] transition-colors hover:text-[var(--color-ink)]"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <Button href="/sign-in" variant="ghost" size="sm">
            Sign in
          </Button>
          <Button href="#cta" variant="primary" size="sm">
            Request a demo
          </Button>
        </div>

        <button
          type="button"
          className="inline-flex items-center justify-center rounded-md p-2 text-[var(--color-ink-2)] md:hidden"
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </Container>

      {open ? (
        <div
          id="mobile-nav"
          className="border-t border-[var(--color-line)] bg-white md:hidden"
        >
          <Container className="flex flex-col gap-1 py-4">
            {siteConfig.nav.primary.map((item) => (
              <a
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="rounded-md px-3 py-2 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                {item.label}
              </a>
            ))}
            <div className="mt-3 flex flex-col gap-2">
              <Button href="/sign-in" variant="outline" size="md">
                Sign in
              </Button>
              <Button href="#cta" variant="primary" size="md">
                Request a demo
              </Button>
            </div>
          </Container>
        </div>
      ) : null}
    </header>
  );
}
