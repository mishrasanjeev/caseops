"use client";

import { Minus, Plus } from "lucide-react";
import { useState } from "react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/cn";
import { marketingFaqs } from "@/lib/marketing-content";
import { siteConfig } from "@/lib/site";

export function FAQ() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <section id="faq" className="py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="FAQ"
          title="Answers before you book a call."
          description={`If we missed your question, write to ${siteConfig.contact.email} and a human will respond within a working day.`}
        />

        <ul className="mx-auto mt-14 max-w-3xl divide-y divide-[var(--color-line)] rounded-2xl border border-[var(--color-line)] bg-white">
          {marketingFaqs.map((item, idx) => {
            const isOpen = open === idx;
            return (
              <li key={item.q}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={`faq-panel-${idx}`}
                  onClick={() => setOpen(isOpen ? null : idx)}
                  className={cn(
                    "flex w-full items-center justify-between gap-6 px-6 py-5 text-left transition-colors",
                    "hover:bg-[var(--color-bg-2)]",
                  )}
                >
                  <span className="text-base font-medium text-[var(--color-ink)]">{item.q}</span>
                  <span
                    aria-hidden
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--color-line)] bg-white text-[var(--color-ink-2)]"
                  >
                    {isOpen ? <Minus className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                  </span>
                </button>
                <div
                  id={`faq-panel-${idx}`}
                  hidden={!isOpen}
                  className="px-6 pb-6 text-sm leading-relaxed text-[var(--color-mute)]"
                >
                  {item.a}
                </div>
              </li>
            );
          })}
        </ul>
      </Container>
    </section>
  );
}
