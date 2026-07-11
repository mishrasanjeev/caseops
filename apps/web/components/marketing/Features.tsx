import {
  BookOpenText,
  Briefcase,
  FileSignature,
  Gavel,
  IndianRupee,
  ListTodo,
  MailCheck,
  Scale,
  ShieldAlert,
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
    body: "A single workspace per matter - timeline, tasks, documents, notices, drafts, hearings, intelligence, communications, billing, next-hearing provenance, and audit.",
  },
  {
    icon: ShieldAlert,
    title: "Intake & Conflict Checks",
    body: "Triage inbound legal requests, promote them into matters, scan clients, matters, and contacts for overlap, and require partner or admin clearance before Active status.",
  },
  {
    icon: MailCheck,
    title: "Notices & Response Deadlines",
    body: "Track received and sent notices, reply ownership and due dates, related reply or supporting documents, overdue queues, and linked matter deadlines.",
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
    title: "Hearing Prep & Cause Lists",
    body: "Compile hearing packs and generate date-wise cause-list PDFs with missing-field warnings, printable court tables, and download audit.",
  },
  {
    icon: Sparkles,
    title: "Court-Order Compliance",
    body: "Extract source-backed compliance items from orders and uploads, keep them review-required by default, and activate tasks or deadlines only after confirmation.",
  },
  {
    icon: Scale,
    title: "Contract & Playbooks",
    body: "Clause extraction, playbook comparison, obligation tracking, and parsed review of DOCX tracked changes.",
  },
  {
    icon: Users,
    title: "Outside Counsel & Spend",
    body: "Assign, evaluate, and budget outside counsel with matter-scoped spend, realization, panel status, and audited invoice review.",
  },
  {
    icon: ListTodo,
    title: "Case Tracking & Ops",
    body: "Refresh explicitly tracked cases in the 4-6 PM IST window, surface skipped/blocked/provider-disabled states, and resume backlog fairly by tenant.",
  },
  {
    icon: IndianRupee,
    title: "Matter Billing India",
    body: "Configure law-firm profiles, rates, fixed fees, milestones, expenses, GST splits, TDS adjustments, invoice sequencing, and server-rendered PDFs.",
  },
  {
    icon: ShieldCheck,
    title: "Trust Plane",
    body: "Tenant isolation, matter-level access controls, audit on material actions, and agent grant readiness. Autonomous scoped-agent execution is planned, not live.",
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
