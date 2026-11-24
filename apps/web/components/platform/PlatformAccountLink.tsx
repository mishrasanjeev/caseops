"use client";

import { ArrowLeft, KeyRound, Mail } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { ConsoleError, consoleErrorMessage, platformApi } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

import { usePlatformLink } from "./PlatformLinkBoundary";
import { PlatformResendInvitation } from "./PlatformResendInvitation";

type InvitationAccount = { account: "new" | "existing"; email: string };

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
  // Which setup form applies: an invitee who already has a CaseOps account
  // confirms with that account's current password instead of creating one.
  const [invitation, setInvitation] = useState<InvitationAccount | null>(null);
  const [inspectFailed, setInspectFailed] = useState<string | null>(null);
  const [inspectAttempt, setInspectAttempt] = useState(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  const requestLink = mode === "reset" && !link?.token;
  const invalid = Boolean(link?.invalid) || (mode === "setup" && (!link?.token || linkRejected));
  const setupToken = mode === "setup" && !link?.invalid ? link?.token ?? null : null;
  const linkSignal = link?.signal;

  useEffect(() => {
    if (!setupToken || linkRejected) return;
    const controller = new AbortController();
    const supersede = () => controller.abort();
    linkSignal?.addEventListener("abort", supersede, { once: true });
    setInvitation(null); setInspectFailed(null);
    platformApi.inspectInvitation(setupToken, controller.signal).then((result) => {
      if (!controller.signal.aborted) setInvitation(result);
    }, (failure: unknown) => {
      if (controller.signal.aborted) return;
      if (failure instanceof ConsoleError && failure.kind === "unauthorized") setLinkRejected(true);
      else setInspectFailed(consoleErrorMessage(failure));
    });
    return () => { linkSignal?.removeEventListener("abort", supersede); controller.abort(); };
  }, [setupToken, linkSignal, linkRejected, inspectAttempt]);

  const existing = invitation?.account === "existing";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || invalid || request.current || link?.signal.aborted) return;
    if (mode === "setup" && !invitation) return;
    if (!requestLink && !existing && password !== confirm) { setError("Passwords do not match."); return; }
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
        const body = existing ? { token: link.token, password } : { token: link.token, password, full_name: name.trim() };
        const auth = await platformApi.acceptInvitation(body, controller.signal);
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

  let body: ReactNode;
  if (invalid) {
    body = <div className="space-y-5"><p role="alert" className="text-sm">This link is invalid, expired or already used. Request a fresh setup or reset link.</p>
      {mode === "setup" ? <PlatformResendInvitation id="setup-resend-email" /> : <a href="/platform/reset-password" referrerPolicy="no-referrer" className="inline-block text-sm underline">Request a fresh reset link</a>}
    </div>;
  } else if (mode === "setup" && !invitation) {
    body = inspectFailed ? <div className="space-y-3"><p role="alert" className="text-sm">{inspectFailed}</p>
      <Button type="button" variant="outline" onClick={() => setInspectAttempt((value) => value + 1)}>Check the link again</Button></div>
      : <p role="status" className="text-sm">Checking your invitation link...</p>;
  } else {
    body = <form onSubmit={submit} className="space-y-5" aria-label={mode === "setup" ? "Accept invitation" : "Platform password reset"}>
      {invitation ? <p className="text-sm">{existing ? "Accepting as " : "Creating report console access for "}<span className="font-medium">{invitation.email}</span>.</p> : null}
      {existing ? <p className="text-sm text-[var(--color-mute)]">This email already has a CaseOps account. Enter the password you currently use to sign in to CaseOps. Your name and password stay unchanged. Forgotten it? <a href="/account/forgot-password" referrerPolicy="no-referrer" className="underline">Reset your CaseOps password</a>, then request a fresh invitation link here, because a password change retires this link.</p> : null}
      {requestLink ? <div className="space-y-2"><Label htmlFor="reset-email">Email</Label><Input id="reset-email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} disabled={pending} /></div> : <>
        {mode === "setup" && !existing ? <div className="space-y-2"><Label htmlFor="setup-name">Full name</Label><Input id="setup-name" autoComplete="name" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={pending} /></div> : null}
        <div className="space-y-2"><Label htmlFor="setup-password">{existing ? "Current CaseOps password" : mode === "setup" ? "Password" : "New password"}</Label><PasswordInput id="setup-password" autoComplete={existing ? "current-password" : "new-password"} required maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} /></div>
        {existing ? null : <div className="space-y-2"><Label htmlFor="setup-confirm">Confirm password</Label><PasswordInput id="setup-confirm" autoComplete="new-password" required maxLength={1024} value={confirm} onChange={(event) => setConfirm(event.target.value)} disabled={pending} /></div>}
      </>}
      <Button type="submit" disabled={pending || Boolean(notice)} className="w-full">{requestLink ? <Mail className="h-4 w-4" aria-hidden /> : <KeyRound className="h-4 w-4" aria-hidden />}{pending ? "Submitting..." : requestLink ? "Send reset link" : mode === "setup" ? "Accept invitation" : "Reset password"}</Button>
    </form>;
  }
  return <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-5 py-10">
    <Link href="/platform/sign-in" prefetch={false} className="inline-flex items-center gap-2 text-sm underline"><ArrowLeft className="h-4 w-4" aria-hidden />Platform sign in</Link>
    <h1 className="text-2xl font-bold">{mode === "setup" ? "Accept administrator invitation" : requestLink ? "Request password reset" : "Reset platform password"}</h1>
    {body}
    {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">{error}</p> : null}
  </main>;
}
