"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { z } from "zod";
import { Button } from "@/components/ui/Button";
import { demoAdmissionSchema, demoRoles } from "@/lib/demo-admission";
import type { DemoSegment, DemoSource } from "@/lib/demo-admission";
import { fetchJsonWithTimeout } from "@/lib/api/client";

export function DemoRequestForm({ source, segment = "solo", intent = "demo", selectedPlan = null }: {
  source: DemoSource; segment?: DemoSegment; intent?: "demo" | "pilot" | "pricing"; selectedPlan?: string | null;
}) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "unconfirmed">("idle");
  const [error, setError] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [chosenSegment, setChosenSegment] = useState(segment);
  const snapshot = useRef<z.infer<typeof demoAdmissionSchema> | null>(null);
  useEffect(() => { if (!snapshot.current) setChosenSegment(segment); }, [segment]);
  const fieldClass = "min-w-0 w-full rounded-md border border-[var(--color-line)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-ink)]";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === "saving" || state === "saved") return;
    if (!snapshot.current) {
      const data = new FormData(event.currentTarget);
      const parsed = demoAdmissionSchema.safeParse({
        contact_name: data.get("contact_name"), contact_email: data.get("contact_email"),
        company_name: data.get("company_name") || null, role: data.get("role"),
        segment: data.get("segment") || segment, selected_plan: chosenSegment === segment ? selectedPlan : null,
        notes: data.get("notes") || null, source, intent,
        idempotency_key: crypto.randomUUID(), privacy_notice_version: "2026-10-09",
      });
      if (!parsed.success) { setError("Review the request fields and try again."); return; }
      snapshot.current = parsed.data;
    }
    setState("saving");
    setError(null);
    try {
      const response = await fetchJsonWithTimeout("/api/demo-request", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(snapshot.current), credentials: "omit", referrerPolicy: "no-referrer",
      }, 20_000);
      const body = response.data as { error?: string; accepted?: boolean; status?: string; id?: string };
      if (!response.ok) {
        if ([400, 422].includes(response.status)) { snapshot.current = null; setState("idle"); }
        else setState("unconfirmed");
        setError(typeof body.error === "string" ? body.error : "Could not confirm this request.");
        return;
      }
      if (body.accepted !== true || body.status !== "demo_requested" || body.id !== snapshot.current.idempotency_key) {
        throw new Error("Unconfirmed admission");
      }
      setSavedId(body.id);
      setState("saved");
    } catch {
      setState("unconfirmed");
      setError("Could not confirm the saved request. Retry the same request; do not submit different details.");
    }
  }

  return <form aria-label="Request a demo" onSubmit={submit} className="grid min-w-0 gap-4 text-[var(--color-ink)]">
    <fieldset disabled={state !== "idle"} className="grid min-w-0 gap-4 disabled:opacity-80">
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <label className="grid min-w-0 gap-1.5 text-sm">Full name
          <input name="contact_name" autoComplete="name" minLength={2} maxLength={255} required className={fieldClass} />
        </label>
        <label className="grid min-w-0 gap-1.5 text-sm">Work email
          <input name="contact_email" type="email" autoComplete="email" maxLength={320} required className={fieldClass} />
        </label>
        <label className="grid min-w-0 gap-1.5 text-sm">Firm / company (optional)
          <input name="company_name" maxLength={255} className={fieldClass} />
        </label>
        <label className="grid min-w-0 gap-1.5 text-sm">Role
          <select name="role" aria-label="Role" defaultValue="" required className={fieldClass}>
            <option value="" disabled>Select role</option>
            {demoRoles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1.5 text-sm">Practice / team
          <select name="segment" aria-label="Practice / team" value={chosenSegment} onChange={(event) => setChosenSegment(event.target.value as DemoSegment)} className={fieldClass}>
            <option value="solo">Solo practice</option><option value="firm">Law firm</option><option value="gc">In-house legal team</option>
          </select>
        </label>
      </div>
      <label className="grid min-w-0 gap-1.5 text-sm">What would you like to discuss? (optional)
        <textarea name="notes" maxLength={1000} rows={3} className={fieldClass} />
      </label>
    </fieldset>
    <p className="text-xs leading-relaxed text-[var(--color-mute)]">
      Do not include client names, case details or confidential documents. Submitting asks us to contact you about this request.
      Access is limited to authorized platform administrators. A proposed 90-day expiry for new, unconverted requests awaits policy review; you can request earlier deletion using your reference.
      No tracking cookies or client analytics. <Link href="/demo/privacy" className="underline">Request privacy notice</Link>.
    </p>
    {error ? <p role="alert" className="text-sm text-red-700">{error}</p> : null}
    {state === "saved" ? <p role="status" className="break-all text-sm">Request saved. Reference: {savedId}. Scheduling, scope and commercial terms will be confirmed separately.</p> : null}
    <Button type="submit" disabled={state === "saving" || state === "saved"} className="w-full sm:w-auto">
      {state === "saving" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowRight className="h-4 w-4" aria-hidden />}
      {state === "saving" ? "Saving request..." : state === "unconfirmed" ? "Retry the same request" : "Request a conversation"}
    </Button>
  </form>;
}
