import {
  BookOpenText,
  Briefcase,
  FileSignature,
  Gavel,
  IndianRupee,
  Landmark,
  ListTodo,
  MailCheck,
  MessageSquare,
  Scale,
  Share2,
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
    body: "Triage inbound legal requests, promote them into matters, and run optional overlap scans across clients and matters with auditable partner or admin review that never blocks Active status.",
  },
  {
    icon: MailCheck,
    title: "Notices & Response Deadlines",
    body: "Track received and sent notices, reply ownership and due dates, related reply or supporting documents, overdue queues, and linked matter deadlines.",
  },
  {
    icon: BookOpenText,
    title: "Research & Citations",
    body: "Hybrid retrieval across available statutes, judgments and internal precedents. Inspect retrieved sources and generated answers; source links do not guarantee correctness or complete coverage.",
  },
  {
    icon: MessageSquare,
    title: "Ask this Workspace",
    body: "Ask factual questions about the matters, IP records and documents you are permitted to see. Answers cite the exact record, and opening a citation rechecks access and is audited. Off until a workspace owner enables it; legal questions go to Research.",
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
    body: "Clause extraction, playbook comparison and obligation tracking. The redline viewer reads Word's own tracked changes, counts a moved passage once, and warns when a file holds changes it cannot display.",
  },
  {
    icon: Landmark,
    title: "IP Workspace",
    body: "Trade mark and patent docket, portfolio views, renewals with recorded client instructions, journal watch, Madrid, recordals, controlled documents and client reports. Registry data is entered or imported; there is no live IP India or WIPO feed. Added to a plan on request.",
  },
  {
    icon: Users,
    title: "Outside Counsel & Spend",
    body: "Keep a counsel panel, assign counsel to a matter with a budget ceiling, and log and review spend against it.",
  },
  {
    icon: Share2,
    title: "Client & Counsel Portals",
    body: "Clients see only the matters and IP records you share, reply, submit KYC and send instructions. Outside counsel see assigned matters and submit work product, time and invoices for your review.",
  },
  {
    icon: ListTodo,
    title: "Case Tracking & Ops",
    body: "Court sync for the Supreme Court and the Delhi, Bombay, Karnataka, Madras and Telangana High Courts suggests dates for lawyer review. eCourts tracking refreshes eligible cases from 6 PM IST with skipped and blocked states visible.",
  },
  {
    icon: IndianRupee,
    title: "Matter Billing India",
    body: "Configure law-firm profiles, rates, fixed fees, milestones, expenses, GST splits, TDS adjustments, invoice sequencing, and server-rendered PDFs.",
  },
  {
    icon: ShieldCheck,
    title: "Trust Plane",
    body: "Tenant isolation, matter-level access controls and ethical walls, teams with optional team-scoped matter visibility, and audit on material actions. Autonomous scoped-agent execution is planned, not live.",
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
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">
                {feature.body}
              </p>
            </article>
          ))}
        </div>
      </Container>
    </section>
  );
}
