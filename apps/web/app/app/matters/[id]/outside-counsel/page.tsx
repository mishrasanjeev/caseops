"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * BUG-019 Hari 2026-04-21: users (and some earlier docs) pointed at
 * ``/app/matters/{id}/outside-counsel`` expecting a per-matter
 * outside-counsel tab. That route didn't exist and 404'd silently,
 * which read as "the module is broken". The real outside-counsel
 * workspace lives at ``/app/outside-counsel`` — redirect there so the
 * click lands somewhere useful instead of a dead end.
 *
 * A true per-matter surface (assignments + spend cards on the matter
 * cockpit) is tracked for a follow-up sprint.
 */
export default function PerMatterOutsideCounselRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/app/outside-counsel");
  }, [router]);
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
      Redirecting to Outside Counsel workspace…
    </div>
  );
}
