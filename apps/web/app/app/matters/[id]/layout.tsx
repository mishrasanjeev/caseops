"use client";

import { Loader2 } from "lucide-react";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { MatterCockpitNav } from "@/components/app/MatterCockpitNav";
import { MatterHeader } from "@/components/app/MatterHeader";
import { Button } from "@/components/ui/Button";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { ApiError } from "@/lib/api/config";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

export default function MatterCockpitLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const { data, isPending, isError, error, refetch } = useMatterWorkspace(matterId);

  if (isPending) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-[var(--color-mute)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Loading matter…
      </div>
    );
  }
  if (isError || !data) {
    // 404 = no such matter / not authorized; retrying won't help, so we
    // offer the "back to portfolio" out instead of a retry button.
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <QueryErrorState
        title={notFound ? "Matter not found" : "Could not load this matter"}
        error={
          notFound
            ? new Error("The matter may no longer exist, or you don't have access to it.")
            : error
        }
        onRetry={notFound ? undefined : refetch}
        secondaryAction={
          <Button href="/app/matters" variant={notFound ? "primary" : "outline"}>
            Back to matter portfolio
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <MatterHeader matter={data.matter} />
      <MatterCockpitNav matterId={matterId} />
      <div>{children}</div>
    </div>
  );
}
