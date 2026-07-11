import { Fingerprint, KeyRound, Lock, ScrollText, Server, ShieldCheck } from "lucide-react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";

const pillars = [
  {
    icon: ShieldCheck,
    title: "Tenant isolation by default",
    body: "Every tenant-owned row, document, vector, and audit event is isolated from other tenants. Shared public authorities remain separate from tenant-private material, and matter access restrictions override broad role access.",
  },
  {
    icon: KeyRound,
    title: "Agent trust readiness",
    body: "Agent grants, budgets, revocation, and execution audit records exist as readiness scaffolding. Autonomous provider or tool execution remains planned until tenant policy, UAT evidence, and founder go/no-go are complete.",
  },
  {
    icon: ScrollText,
    title: "Audit by default",
    body: "Actor, tenant, matter, action, target, result, invoice export, compliance review, and scheduled-job state recorded for material events.",
  },
  {
    icon: Lock,
    title: "Customer data stays private",
    body: "No cross-tenant training without explicit opt-in. Raw prompts, raw LLM responses, provider payloads, tokens, and internal costs stay out of tenant-facing views.",
  },
  {
    icon: Fingerprint,
    title: "Notification guardrails",
    body: "Job failures and review events create durable in-app notification intents. External email, SMS, and WhatsApp delivery stays provider-gated until configuration, template/DLT approval, and UAT evidence are complete.",
  },
  {
    icon: Server,
    title: "Private inference planning",
    body: "Shared SaaS is the live path today. Dedicated, VPC, and on-prem inference are planned enterprise deployment options that require separate security and implementation signoff.",
  },
] as const;

export function Security() {
  return (
    <section id="security" className="py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Trust"
          title="Built to pass a vendor security review."
          description="CaseOps is enterprise-shaped from day one. Multi-tenant, auditable, and explicit about which controls are live, review-first, provider-gated, or planned."
        />

        <div className="mt-16 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {pillars.map((pillar) => (
            <article
              key={pillar.title}
              className="flex flex-col rounded-2xl border border-[var(--color-line)] bg-white p-6"
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-ink)] text-white">
                <pillar.icon className="h-5 w-5" aria-hidden />
              </span>
              <h3 className="mt-5 text-lg font-semibold tracking-tight text-[var(--color-ink)]">
                {pillar.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">{pillar.body}</p>
            </article>
          ))}
        </div>

        <div className="mt-14 rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg)] p-6 md:p-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 className="text-lg font-semibold tracking-tight text-[var(--color-ink)]">
                AI that refuses to guess.
              </h3>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--color-mute)]">
                CaseOps keeps law in retrieval, not in weights. Substantive answers come with
                citations, assumptions, and confidence. Weak-evidence prompts return an explicit
                refusal instead of a confident guess. Court-order compliance extraction is
                schema-validated, source-backed, reviewable, and audited before activation.
              </p>
            </div>
            <ul className="grid grid-cols-2 gap-3 text-xs text-[var(--color-ink-2)] md:grid-cols-1">
              {[
                "Citation verification",
                "Hallucination checks",
                "Prompt-injection tests",
                "Tenant-data leak red-team",
              ].map((item) => (
                <li
                  key={item}
                  className="rounded-full border border-[var(--color-line)] bg-white px-3 py-1.5 text-center font-medium"
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Container>
    </section>
  );
}
