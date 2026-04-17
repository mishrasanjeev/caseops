import { Fingerprint, KeyRound, Lock, ScrollText, Server, ShieldCheck } from "lucide-react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";

const pillars = [
  {
    icon: ShieldCheck,
    title: "Tenant isolation by default",
    body: "Every row, document, vector, and audit event is scoped by tenant. Matter-level ethical walls override broad role access.",
  },
  {
    icon: KeyRound,
    title: "Scoped agent identity",
    body: "Agents run with expiring grants, budgets, and revocation. No tool call happens without an explicit, auditable scope.",
  },
  {
    icon: ScrollText,
    title: "Audit by default",
    body: "Actor, tenant, matter, action, target, and result recorded for every mutating event. Append-only and exportable.",
  },
  {
    icon: Lock,
    title: "Customer data stays yours",
    body: "No cross-tenant training without explicit opt-in. Private notes separated from shareable work product.",
  },
  {
    icon: Fingerprint,
    title: "Enterprise identity",
    body: "OIDC and SAML SSO on the roadmap; MFA and session revocation on suspension. Role-based and team-based scopes.",
  },
  {
    icon: Server,
    title: "Private inference on request",
    body: "Shared SaaS today; dedicated and on-prem inference packaged for enterprise tenants that need it.",
  },
] as const;

export function Security() {
  return (
    <section id="security" className="py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Trust"
          title="Built to pass a vendor security review."
          description="CaseOps is enterprise-shaped from day one. Multi-tenant, auditable, and safe for agents — before it is convenient."
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
                refusal instead of a confident guess.
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
