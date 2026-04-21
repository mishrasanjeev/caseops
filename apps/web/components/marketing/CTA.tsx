"use client";

import { ArrowRight, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Container } from "@/components/ui/Container";
import { cn } from "@/lib/cn";
import { siteConfig } from "@/lib/site";

type Status = "idle" | "submitting" | "success" | "error";

export function CTA() {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("submitting");
    setError(null);

    const form = event.currentTarget;
    const data = new FormData(form);
    const payload = Object.fromEntries(data.entries());

    try {
      const res = await fetch("/api/demo-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error("Request failed");
      }
      setStatus("success");
      form.reset();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  return (
    <section id="cta" className="py-20 md:py-28">
      <Container>
        <div className="relative overflow-hidden rounded-3xl bg-[var(--color-ink)] px-6 py-14 md:px-14 md:py-20">
          <div
            aria-hidden
            className="absolute -right-32 -top-32 h-[400px] w-[400px] rounded-full bg-[var(--color-brand-500)]/30 blur-3xl"
          />
          <div
            aria-hidden
            className="absolute -bottom-32 -left-32 h-[400px] w-[400px] rounded-full bg-[var(--color-accent-500)]/20 blur-3xl"
          />

          <div className="relative grid gap-12 md:grid-cols-2 md:items-center">
            <div className="text-white">
              <h2 className="max-w-md text-balance text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
                Run your matters on CaseOps.
              </h2>
              <p className="mt-4 max-w-md text-pretty text-base leading-relaxed text-white/75">
                Tell us about your practice. We'll set up a workspace with a demo matter, wire in
                your court preferences, and walk through it with you.
              </p>
              <ul className="mt-6 space-y-2 text-sm text-white/75">
                {[
                  "45-minute guided walkthrough",
                  "Sample matter loaded with your jurisdiction",
                  "No credit card, no sales trap",
                ].map((item) => (
                  <li key={item} className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-[var(--color-brand-300)]" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
              <p className="mt-6 text-sm text-white/70">
                Or write directly to{" "}
                <a
                  href={`mailto:${siteConfig.contact.founder}`}
                  className="font-medium text-white underline-offset-4 hover:underline"
                >
                  {siteConfig.contact.founder}
                </a>
                .
              </p>
            </div>

            <form
              onSubmit={handleSubmit}
              className="grid gap-3 rounded-2xl bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur-sm"
              aria-label="Request a demo"
            >
              <Field label="Full name" name="name" type="text" autoComplete="name" required />
              <Field
                label="Work email"
                name="email"
                type="email"
                autoComplete="email"
                required
              />
              <Field label="Firm / company" name="company" type="text" required />
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-white/80" htmlFor="cta-role">
                  Role
                </label>
                <select
                  id="cta-role"
                  name="role"
                  required
                  defaultValue=""
                  className="h-11 rounded-md border border-white/15 bg-[var(--color-ink-2)] px-3 text-sm text-white outline-none focus:border-white/40"
                >
                  <option value="" disabled>
                    Select…
                  </option>
                  <option>Managing partner / head of litigation</option>
                  <option>Partner / senior associate</option>
                  <option>General counsel</option>
                  <option>Legal ops</option>
                  <option>Solo advocate</option>
                  <option>Other</option>
                </select>
              </div>

              <Button type="submit" size="lg" className="mt-3 w-full" disabled={status === "submitting"}>
                {status === "submitting" ? "Submitting…" : "Request a demo"}
                {status !== "submitting" ? <ArrowRight className="h-4 w-4" /> : null}
              </Button>

              <p
                className={cn(
                  "min-h-[1.25rem] text-xs",
                  status === "success" && "text-[var(--color-brand-300)]",
                  status === "error" && "text-red-300",
                  status === "idle" && "text-white/55",
                  status === "submitting" && "text-white/70",
                )}
                role={status === "error" ? "alert" : undefined}
              >
                {status === "success"
                  ? "Thanks — we'll be in touch within a working day."
                  : status === "error"
                  ? (error ?? `Could not submit. Please email ${siteConfig.contact.founder}.`)
                  : "We read every submission. No marketing spam."}
              </p>
            </form>
          </div>
        </div>
      </Container>
    </section>
  );
}

function Field({
  label,
  name,
  type,
  autoComplete,
  required,
}: {
  label: string;
  name: string;
  type: "text" | "email";
  autoComplete?: string;
  required?: boolean;
}) {
  const id = `cta-${name}`;
  return (
    <div className="grid gap-1.5">
      <label className="text-xs font-medium text-white/80" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        required={required}
        className="h-11 rounded-md border border-white/15 bg-[var(--color-ink-2)] px-3 text-sm text-white placeholder:text-white/40 outline-none focus:border-white/40"
      />
    </div>
  );
}
