"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { useSession } from "@/lib/use-session";

export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "anonymous") {
      const current =
        typeof window !== "undefined"
          ? window.location.pathname + window.location.search
          : "/app";
      router.replace(`/sign-in?next=${encodeURIComponent(current)}`);
    }
  }, [session.status, router]);

  if (session.status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)]">
        <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading your workspace…
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
