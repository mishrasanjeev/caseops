"use client";

import { Minus, Plus } from "lucide-react";
import { useState } from "react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/cn";
import { siteConfig } from "@/lib/site";

const faqs = [
  {
    q: "Is CaseOps another chatbot for lawyers?",
    a: "No. CaseOps is a system of work. Drafting, hearing prep, research, contracts, and billing are first-class workspaces backed by a matter graph. AI is a feature of the system, not the product.",
  },
  {
    q: "How does CaseOps avoid hallucinated citations?",
    a: "Legal knowledge lives in retrieval and source systems, not the model. Every substantive answer is grounded in statutes, judgments, or your own precedents — with inline citations, assumptions, missing facts, and confidence. Weak-evidence prompts return an explicit refusal.",
  },
  {
    q: "What courts and jurisdictions are covered?",
    a: "Lower courts, High Courts, and the Supreme Court are in scope from the first release. Delhi / NCR, Maharashtra, Karnataka, and Telangana are priority rollouts, with Tamil Nadu and Gujarat to follow.",
  },
  {
    q: "How is tenant data isolated?",
    a: "Every record, document, embedding, and audit event carries a tenant_id and is filtered at the query and storage layer. Matter-level ethical walls override broad role access. Agents run with scoped grants, not user credentials.",
  },
  {
    q: "Can we self-host or run in a private VPC?",
    a: "Yes — on the Enterprise tier. CaseOps ships a packaged private inference stack that deploys in dedicated tenant environments, with a path to on-prem for qualifying customers.",
  },
  {
    q: "How does billing and fee collection work?",
    a: "Timekeeping, rate cards, invoice approval, and payment links are built in. Pine Labs is the launch payment rail. Corporate legal teams get matched invoice intake, budget mapping, and spend dashboards.",
  },
  {
    q: "Who owns the data used to fine-tune models?",
    a: "You do. Customer data is not used for cross-tenant training by default. Tenant-specific adapters are an opt-in that stays inside your tenant boundary.",
  },
] as const;

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
          {faqs.map((item, idx) => {
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
