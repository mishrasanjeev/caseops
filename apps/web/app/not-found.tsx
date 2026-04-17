import { Compass } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[var(--color-bg)] px-6 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
        <Compass className="h-5 w-5" aria-hidden />
      </span>
      <h1 className="text-3xl font-semibold tracking-tight text-[var(--color-ink)]">
        This page isn't on the matter graph
      </h1>
      <p className="max-w-md text-sm leading-relaxed text-[var(--color-mute)]">
        The link may be stale or mistyped. Head back to the landing page or open
        your workspace.
      </p>
      <div className="mt-3 flex items-center gap-2">
        <Button href="/">Back to site</Button>
        <Button href="/app" variant="outline">
          Open workspace
        </Button>
        <Link
          href="/sign-in"
          className="text-sm font-medium text-[var(--color-brand-700)] underline-offset-4 hover:underline"
        >
          Sign in
        </Link>
      </div>
    </main>
  );
}
