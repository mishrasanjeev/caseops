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
    a: "No. CaseOps is a system of work. Drafting, hearing prep, research, contracts, compliance review, cause lists, and billing are first-class workspaces backed by a matter graph. AI is a feature of the system, not the product.",
  },
  {
    q: "How does CaseOps avoid hallucinated citations?",
    a: "Legal knowledge lives in retrieval and source systems, not the model. Every substantive answer is grounded in statutes, judgments, or your own precedents with inline citations, assumptions, missing facts, and confidence. Weak-evidence prompts return an explicit refusal. The structured statute model feeds bare text into appeal drafts so the LLM quotes verbatim instead of paraphrasing.",
  },
  {
    q: "How does case tracking work?",
    a: "Production scheduled refresh is opt-in by default: only explicitly tracked or bookmarked matters refresh. The daily job is configured for the 4 PM to 6 PM IST window, keeps backlog for the next run, batches fairly across tenants, and records attempted, refreshed, changed, skipped, blocked, provider-call, error, partial, and backlog metrics. CaseOps does not bypass captcha, login, or session-gated court sources.",
  },
  {
    q: "How does court-order compliance extraction work?",
    a: "Manual and adapter-created court orders first go through deterministic extraction. AI extraction runs only when tenant policy allows it, must pass schema validation, and creates source-backed review-required compliance items by default. Lawyers confirm, edit, reject, waive, complete, or retry items before tasks and deadlines become active unless a tenant admin has explicitly enabled auto-activation.",
  },
  {
    q: "How cautious are deadline calculations?",
    a: "Deadline items show source snippet, confidence, and the calculation convention. Calendar days are the default unless a configured court calendar exists. Ambiguous phrases such as from today, within two weeks, next date, or missing order date remain review-required. CaseOps does not invent due dates.",
  },
  {
    q: "What is included in matter billing?",
    a: "Matter billing is separate from CaseOps SaaS subscription billing. Tenant admins configure law-firm profiles, firm GSTIN/PAN/name/address, client billing fields, place of supply, SAC/HSN or service classification, invoice sequence, payment terms, hourly and fixed-fee arrangements, milestones, expenses, retainers or advances, GST split, TDS adjustments, amount paid/outstanding, and server-rendered invoice PDFs.",
  },
  {
    q: "Does the appeal draft consider which bench will hear it?",
    a: "Yes. When a matter has an upcoming listing whose bench is resolved against the judge catalog, the appeal-memorandum draft can pull authorities authored by that bench and prefer ones aligned with the matter's practice area. Predictive and bench-context surfaces stay source-backed: they show sample size, confidence band, evidence links, and limitation notes rather than uncited court-strategy claims.",
  },
  {
    q: "How is tenant data isolated?",
    a: "Every record, document, embedding, and audit event carries a tenant_id and is filtered at the query and storage layer. Matter-level ethical walls override broad role access. Agent grant and execution-audit records are readiness scaffolding; autonomous scoped-agent execution is not live. Tenant-facing surfaces do not expose provider tokens, raw provider payloads, raw prompts, raw LLM responses, internal costs, or unauthorized tenant-private data.",
  },
  {
    q: "Can we self-host or run in a private VPC?",
    a: "Enterprise deployment is planned and readiness-scaffolded, but not marketed as live. Private VPC, on-prem inference, OIDC/SAML SSO, SCIM, and dedicated connectors require security review, provider/UAT evidence, and a separate implementation signoff.",
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
