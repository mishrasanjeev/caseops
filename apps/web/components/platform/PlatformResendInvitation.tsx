"use client";

import { Mail } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { consoleErrorMessage, platformApi } from "@/lib/platform/client";

export function PlatformResendInvitation({ id = "platform-resend-email" }: { id?: string }) {
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || accepted) return;
    setPending(true); setError(null);
    try { await platformApi.resendInvitation(email.trim()); setAccepted(true); }
    catch (failure) { setError(consoleErrorMessage(failure)); }
    finally { setPending(false); }
  }
  return <form onSubmit={submit} aria-label="Resend setup email" className="space-y-3">
    <div className="space-y-2"><Label htmlFor={id}>Email</Label><Input id={id} type="email" autoComplete="username" required value={email}
      disabled={pending} onChange={(event) => { setEmail(event.target.value); setAccepted(false); }} /></div>
    <Button type="submit" variant="outline" disabled={pending || accepted} className="w-full"><Mail className="h-4 w-4" aria-hidden />{pending ? "Requesting..." : "Resend setup email"}</Button>
    {accepted ? <p role="status" className="text-sm">If this account is eligible, a fresh setup email will be sent.</p> : null}
    {error ? <p role="alert" className="text-sm">{error}</p> : null}
  </form>;
}
