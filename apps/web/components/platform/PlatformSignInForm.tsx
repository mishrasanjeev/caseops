"use client";

import { LogIn, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";

export function PlatformSignInForm({ onSignIn, footer }: {
  onSignIn?: (input: { email: string; password: string }) => Promise<void>;
  footer?: ReactNode;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onSignIn || pending) return;
    setPending(true);
    setError(false);
    try {
      await onSignIn({ email: email.trim(), password });
    } catch {
      setError(true);
    } finally {
      setPassword("");
      setPending(false);
    }
  }

  return (
    <main id="main" className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-5 py-10">
      <div className="inline-flex items-center gap-2 font-bold"><ShieldCheck className="h-5 w-5" aria-hidden />CaseOps Platform</div>
      <h1 className="text-2xl font-bold">Sign in</h1>
      <form aria-label="Platform sign in" onSubmit={submit} className="flex min-w-0 flex-col gap-5">
        <div className="space-y-2">
          <Label htmlFor="platform-email">Email</Label>
          <Input id="platform-email" name="email" type="email" autoComplete="username" required value={email}
            onChange={(event) => setEmail(event.target.value)} disabled={pending} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="platform-password">Password</Label>
          <PasswordInput id="platform-password" name="password" autoComplete="current-password" required value={password}
            onChange={(event) => setPassword(event.target.value)} disabled={pending} />
        </div>
        {error ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">Unable to sign in. Check your details and try again.</p> : null}
        <Button type="submit" disabled={!onSignIn || pending} className="w-full">
          <LogIn className="h-4 w-4" aria-hidden />{pending ? "Signing in..." : "Sign in"}
        </Button>
      </form>
      {footer}
    </main>
  );
}
