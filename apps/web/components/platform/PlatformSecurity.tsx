"use client";

import Link from "next/link";

import { usePlatformSession } from "@/lib/platform/session";

import { PlatformMfa } from "./PlatformMfa";
import { PlatformPending } from "./PlatformPending";
import { PlatformShell } from "./PlatformShell";

export function PlatformSecurity() {
  const session = usePlatformSession();
  return <PlatformShell><div className="space-y-6">
    <h1 className="border-b border-[var(--color-line)] pb-4 text-2xl font-bold">Account security</h1>
    {session.status === "loading" ? <PlatformPending title="Account verification" label="Checking account security..." />
      : session.auth ? <><p className="break-words text-sm">{session.auth.admin?.email ?? "Platform verification session"}</p><PlatformMfa /></>
      : <><p role={session.error ? "alert" : undefined} className="text-sm">{session.error ?? "Sign in to manage your platform account."}</p><Link href="/platform/sign-in" prefetch={false} className="inline-block underline">Platform sign in</Link></>}
    <Link href="/platform/reset-password" prefetch={false} className="inline-block text-sm underline">Reset password</Link>
  </div></PlatformShell>;
}
