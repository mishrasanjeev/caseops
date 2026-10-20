"use client";

import { ArrowLeft, KeyRound, Mail } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { ConsoleError, consoleErrorMessage, platformApi } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

import { usePlatformLink } from "./PlatformLinkBoundary";
import { PlatformResendInvitation } from "./PlatformResendInvitation";

export function PlatformAccountLink({ mode }: { mode: "setup" | "reset" }) {
  const link = usePlatformLink();
  const session = usePlatformSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linkRejected, setLinkRejected] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  const requestLink = mode === "reset" && !link?.token;
  const invalid = Boolean(link?.invalid) || (mode === "setup" && (!link?.token || linkRejected));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || invalid || request.current || link?.signal.aborted) return;
    if (!requestLink && password !== confirm) { setError("Passwords do not match."); return; }
    const controller = new AbortController();
    const supersede = () => controller.abort();
    link?.signal.addEventListener("abort", supersede, { once: true });
    request.current = controller;
    const isCurrent = () => request.current === controller && !controller.signal.aborted && !link?.signal.aborted;
    setPending(true); setError(null); setNotice(null);
    try {
      if (requestLink) {
        await platformApi.startReset(email.trim(), controller.signal);
        if (!isCurrent()) return;
        setNotice("If this account is eligible, a password reset link will be sent.");
      } else if (mode === "setup" && link?.token) {
        const auth = await platformApi.acceptInvitation({ token: link.token, password, full_name: name.trim() }, controller.signal);
        if (!isCurrent()) return;
        session.accept(auth); router.replace("/platform/security");
      } else if (link?.token) {
        await platformApi.completeReset({ token: link.token, password }, controller.signal);
        if (!isCurrent()) return;
        setNotice("Password reset complete. Sign in again and complete MFA.");
      }
    } catch (failure) {
      if (!isCurrent()) return;
      if (mode === "setup" && failure instanceof ConsoleError && failure.kind === "unauthorized") {
        setLinkRejected(true);
      } else setError(consoleErrorMessage(failure));
    }
    finally {
      link?.signal.removeEventListener("abort", supersede);
      if (isCurrent()) { request.current = null; setPassword(""); setConfirm(""); setPending(false); }
    }
  }
  return <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-5 py-10">
    <Link href="/platform/sign-in" prefetch={false} className="inline-flex items-center gap-2 text-sm underline"><ArrowLeft className="h-4 w-4" aria-hidden />Platform sign in</Link>
    <h1 className="text-2xl font-bold">{mode === "setup" ? "Accept administrator invitation" : requestLink ? "Request password reset" : "Reset platform password"}</h1>
    {invalid ? <div className="space-y-5"><p role="alert" className="text-sm">This link is invalid, expired or already used. Request a fresh setup or reset link.</p>
      {mode === "setup" ? <PlatformResendInvitation id="setup-resend-email" /> : <a href="/platform/reset-password" referrerPolicy="no-referrer" className="inline-block text-sm underline">Request a fresh reset link</a>}
    </div> :
      <form onSubmit={submit} className="space-y-5" aria-label={mode === "setup" ? "Accept invitation" : "Platform password reset"}>
        {requestLink ? <div className="space-y-2"><Label htmlFor="reset-email">Email</Label><Input id="reset-email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} disabled={pending} /></div> : <>
          {mode === "setup" ? <div className="space-y-2"><Label htmlFor="setup-name">Full name</Label><Input id="setup-name" autoComplete="name" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={pending} /></div> : null}
          <div className="space-y-2"><Label htmlFor="setup-password">{mode === "setup" ? "Password" : "New password"}</Label><PasswordInput id="setup-password" autoComplete={mode === "setup" ? "current-password" : "new-password"} required maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} /></div>
          <div className="space-y-2"><Label htmlFor="setup-confirm">Confirm password</Label><PasswordInput id="setup-confirm" autoComplete={mode === "setup" ? "current-password" : "new-password"} required maxLength={1024} value={confirm} onChange={(event) => setConfirm(event.target.value)} disabled={pending} /></div>
        </>}
        <Button type="submit" disabled={pending || Boolean(notice)} className="w-full">{requestLink ? <Mail className="h-4 w-4" aria-hidden /> : <KeyRound className="h-4 w-4" aria-hidden />}{pending ? "Submitting..." : requestLink ? "Send reset link" : mode === "setup" ? "Accept invitation" : "Reset password"}</Button>
      </form>}
    {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">{error}</p> : null}
  </main>;
}
