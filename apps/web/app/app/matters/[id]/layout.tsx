"use client";

import { Loader2, Triangle } from "lucide-react";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { MatterCockpitNav } from "@/components/app/MatterCockpitNav";
import { MatterHeader } from "@/components/app/MatterHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

export default function MatterCockpitLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const { data, isPending, isError, error } = useMatterWorkspace(matterId);

  if (isPending) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-[var(--color-mute)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Loading matter…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <EmptyState
        icon={Triangle}
        title="Could not load this matter"
        description={
          error instanceof Error
            ? error.message
            : "The matter may no longer exist, or you don't have access."
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
