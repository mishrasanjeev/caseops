"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Briefcase } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { NewMatterDialog } from "@/components/app/NewMatterDialog";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

const PAGE_SIZE = 50;

const FORUMS: Record<string, string> = {
  lower_court: "Lower",
  high_court: "High Court",
  supreme_court: "Supreme Court",
  tribunal: "Tribunal",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

export default function MattersPage() {
  const router = useRouter();
  const {
    data,
    isPending,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["matters", "list"],
    queryFn: ({ pageParam }) =>
      listMatters({ limit: PAGE_SIZE, cursor: pageParam ?? null }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const columns = useMemo<ColumnDef<Matter>[]>(
    () => [
      {
        accessorKey: "matter_code",
        header: "Code",
        cell: (ctx) => (
          <span className="font-mono text-xs text-[var(--color-ink-2)]">
            {ctx.getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: "title",
        header: "Matter",
        cell: (ctx) => (
          <div className="flex flex-col">
            <span className="font-medium text-[var(--color-ink)]">
              {ctx.getValue<string>()}
            </span>
            {ctx.row.original.client_name ? (
              <span className="text-xs text-[var(--color-mute)]">
                v. {ctx.row.original.opposing_party ?? "—"} · {ctx.row.original.client_name}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        accessorKey: "forum_level",
        header: "Forum",
        cell: (ctx) => FORUMS[ctx.getValue<string>() ?? ""] ?? ctx.getValue<string>() ?? "—",
      },
      {
        accessorKey: "court_name",
        header: "Court",
        cell: (ctx) => ctx.getValue<string>() ?? "—",
      },
      {
        accessorKey: "next_hearing_on",
        header: "Next hearing",
        cell: (ctx) => formatDate(ctx.getValue<string | null>()),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (ctx) => <StatusBadge status={ctx.getValue<string>()} />,
      },
    ],
    [],
  );

  const matters = useMemo(
    () => data?.pages.flatMap((page) => page.matters) ?? [],
    [data],
  );
  const canCreateMatter = useCapability("matters:create");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matters"
        title="Matter portfolio"
        description="Every matter in your workspace. Click a row to open the cockpit."
        actions={canCreateMatter ? <NewMatterDialog /> : null}
      />

      {isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : isError ? (
        <EmptyState
          icon={Briefcase}
          title="Could not load matters"
          description={
            error instanceof Error ? error.message : "Check your connection and try again."
          }
        />
      ) : matters.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="No matters yet"
          description={
            canCreateMatter
              ? "Create your first matter to start tracking hearings, drafts, and billing."
              : "No matters are assigned to you yet. Ask an admin to add you to a matter."
          }
          action={canCreateMatter ? <NewMatterDialog /> : null}
        />
      ) : (
        <>
          <DataTable
            data={matters}
            columns={columns}
            filterPlaceholder="Search matters, codes, clients…"
            onRowClick={(m) => router.push(`/app/matters/${m.id}`)}
            getRowId={(m) => m.id}
          />
          {hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
