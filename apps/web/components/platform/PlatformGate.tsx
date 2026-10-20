"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Fragment } from "react";

import { Button } from "@/components/ui/Button";
import { usePlatformSession } from "@/lib/platform/session";

import { PlatformPending } from "./PlatformPending";

export function PlatformGate({ children, managerOnly = false }: { children: ReactNode; managerOnly?: boolean }) {
  const session = usePlatformSession();
  if (session.status === "loading") return <PlatformPending title="Platform reports" label="Checking platform access..." />;
  if (session.status === "error") return <section><h1 className="text-2xl font-bold">Unable to check access</h1><p role="alert" className="my-4 text-sm">{session.error}</p><Button onClick={() => void session.refresh()} variant="outline">Check again</Button></section>;
  if (!session.auth) return <section><h1 className="text-2xl font-bold">Sign in required</h1><Link href="/platform/sign-in" prefetch={false} className="mt-4 inline-block underline">Sign in to platform reports</Link></section>;
  if (session.auth.state !== "authenticated") return <section><h1 className="text-2xl font-bold">Verification required</h1><Link href="/platform/security" prefetch={false} className="mt-4 inline-block underline">Complete multi-factor verification</Link></section>;
  if (managerOnly && session.auth.admin?.role !== "manager") return <section><h1 className="text-2xl font-bold">Access denied</h1><p role="alert" className="mt-4 text-sm">Administrator management requires manager access.</p></section>;
  return <Fragment key={`${session.auth.admin?.id}:${session.auth.expires_at}`}>{children}</Fragment>;
}
