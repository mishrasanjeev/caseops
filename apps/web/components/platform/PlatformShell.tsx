"use client";

import { BarChart3, Inbox, KeyRound, LogOut, ShieldCheck, UsersRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";

import { SkipLink } from "@/components/ui/SkipLink";
import { cn } from "@/lib/cn";
import { consoleErrorMessage } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

export function PlatformShell({ children }: {
  children: ReactNode;
}) {
  const session = usePlatformSession();
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const canManageAdmins = session.auth?.state === "authenticated" && session.auth.admin?.role === "manager";
  const pathname = usePathname();
  const links = [
    { href: "/platform/reports", label: "Reports", icon: BarChart3 },
    ...(canManageAdmins ? [{ href: "/platform/leads", label: "Leads", icon: Inbox }] : []),
    ...(canManageAdmins ? [{ href: "/platform/admins", label: "Administrators", icon: UsersRound }] : []),
    { href: "/platform/security", label: "Security", icon: KeyRound },
  ];
  return (
    <div className="min-h-screen min-w-0">
      <SkipLink />
      <header className="border-b border-[var(--color-line)] bg-[var(--color-surface,var(--color-bg))]">
        <div className="mx-auto flex max-w-[90rem] min-w-0 flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6 lg:px-8">
          <Link href="/platform/reports" prefetch={false} className="inline-flex min-w-0 items-center gap-2 font-bold">
            <ShieldCheck className="h-5 w-5 shrink-0" aria-hidden />
            <span>CaseOps <span className="font-normal text-[var(--color-mute)]">Platform</span></span>
          </Link>
          <nav aria-label="Platform" className="flex min-w-0 flex-wrap gap-1">
            {links.map(({ href, label, icon: Icon }) => (
              <Link key={href} href={href} prefetch={false} aria-current={pathname === href ? "page" : undefined}
                className={cn("inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand-500)]",
                  pathname === href ? "bg-[var(--color-bg-2)] text-[var(--color-ink)]" : "text-[var(--color-mute)] hover:bg-[var(--color-bg-2)]")}>
                <Icon className="h-4 w-4 shrink-0" aria-hidden />{label}
              </Link>
            ))}
          </nav>
          {session.auth ? <button type="button" aria-label="Sign out of platform" title="Sign out of platform" disabled={signingOut}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-[var(--color-line)] disabled:opacity-50"
            onClick={async () => { setSigningOut(true); setError(null); try { await session.signOut(); } catch (failure) { setError(consoleErrorMessage(failure)); } finally { setSigningOut(false); } }}>
            <LogOut className="h-4 w-4" aria-hidden />
          </button> : null}
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[90rem] min-w-0 px-4 py-6 focus:outline-none sm:px-6 lg:px-8">
        {error ? <p role="alert" className="mb-4 text-sm text-[var(--color-danger-500)]">{error}</p> : null}
        {children}
      </main>
    </div>
  );
}
