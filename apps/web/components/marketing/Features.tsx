import {
  BookOpenText,
  Briefcase,
  FileSignature,
  Gavel,
  ListTodo,
  Scale,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";

const features = [
  {
    icon: Briefcase,
    title: "Matter Cockpit",
    body: "A single workspace per matter — parties, stage, documents, hearings, drafts, billing, and audit — always in sync.",
  },
  {
    icon: BookOpenText,
    title: "Research & Citations",
    body: "Hybrid retrieval across statutes, judgments, and your internal precedents. Every answer is grounded and linked to source.",
  },
  {
    icon: FileSignature,
    title: "Drafting Studio",
    body: "Generate first drafts from templates and matter context, with inline citations, version history, and reviewer approval.",
  },
  {
    icon: Gavel,
    title: "Hearing Prep",
    body: "Auto-compile chronologies, last orders, pending compliance, bench brief, and oral points before every listing.",
  },
  {
    icon: Sparkles,
    title: "Explainable Recommendations",
    body: "Forum and supporting-authority recommendations today, with rationale, assumptions, missing facts, and confidence on every option.",
  },
  {
    icon: Scale,
    title: "Contract & Playbooks",
    body: "Clause extraction, playbook comparison, obligation tracking, and redlines with tracked version lineage.",
  },
  {
    icon: Users,
    title: "Outside Counsel & Spend",
    body: "Assign, evaluate, and budget outside counsel. Full fee-collection rail with Pine Labs built in.",
  },
  {
    icon: ListTodo,
    title: "Legal Ops & Intake",
    body: "Route incoming requests, standardize intake, and keep GC dashboards honest with structured workflows.",
  },
  {
    icon: ShieldCheck,
    title: "Trust Plane",
    body: "Tenant isolation, matter-level ethical walls, scoped agent grants, and audit on every action — by default.",
  },
] as const;

export function Features() {
  return (
    <section id="product" className="py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Product"
          title="Every legal workflow, on one matter graph."
          description="CaseOps connects the work, the sources, and the decisions. Not another chatbot, not another CRM — a system of work for legal teams."
        />

        <div className="mt-16 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <article
              key={feature.title}
              className="group relative flex flex-col rounded-2xl border border-[var(--color-line)] bg-white p-6 shadow-[var(--shadow-soft)] transition-all hover:-translate-y-0.5 hover:border-[var(--color-ink-3)]/30 hover:shadow-[var(--shadow-raised)]"
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
                <feature.icon className="h-5 w-5" aria-hidden />
              </span>
              <h3 className="mt-5 text-lg font-semibold tracking-tight text-[var(--color-ink)]">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">{feature.body}</p>
            </article>
          ))}
        </div>
      </Container>
    </section>
  );
}
