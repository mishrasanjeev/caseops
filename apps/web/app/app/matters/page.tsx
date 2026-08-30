"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Briefcase,
  Filter,
  Loader2,
  RotateCcw,
  Tags,
  UploadCloud,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { NewMatterDialog } from "@/components/app/NewMatterDialog";
import { MatterLifecycleDialog } from "@/components/matters/MatterLifecycleDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  bulkAssignMatterTag,
  listMatterTags,
  listMatters,
  updateMatter,
} from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

const PAGE_SIZE = 50;
const CLAIM_CURRENCY_PATTERN = /^[A-Z]{3}$/;

const FORUMS: Record<string, string> = {
  lower_court: "Lower",
  high_court: "High Court",
  supreme_court: "Supreme Court",
  tribunal: "Tribunal",
};

type FilterState = {
  q: string;
  status: string;
  forum_level: string;
  tag: string;
  min_claim_amount: string;
  max_claim_amount: string;
};

const EMPTY_FILTERS: FilterState = {
  q: "",
  status: "all",
  forum_level: "all",
  tag: "all",
  min_claim_amount: "",
  max_claim_amount: "",
};

const MATTER_STATUSES = [
  { value: "intake", label: "Intake" },
  { value: "active", label: "Active" },
  { value: "on_hold", label: "On hold" },
] as const;

type MatterStatusValue = (typeof MATTER_STATUSES)[number]["value"];

const MATTER_STATUS_LABELS: Record<string, string> = Object.fromEntries(
  MATTER_STATUSES.map((status) => [status.value, status.label]),
);
MATTER_STATUS_LABELS.disposed = "Disposed";

function formatDate(value: string | null | undefined): string {
  // Legal calendar dates (next_hearing_on etc.) are SQL Date values
  // and must never shift across timezones. See lib/dates.ts.
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function toMinor(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) return undefined;
  return Math.round(parsed * 100);
}

function formatClaimAmount(matter: Matter): string {
  if (matter.claim_amount_minor == null) return "—";
  const currency =
    matter.claim_currency && CLAIM_CURRENCY_PATTERN.test(matter.claim_currency)
      ? matter.claim_currency
      : "INR";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(matter.claim_amount_minor / 100);
  } catch {
    return `INR ${(matter.claim_amount_minor / 100).toLocaleString("en-IN", {
      maximumFractionDigits: 0,
    })}`;
  }
}

function TagCell({ matter }: { matter: Matter }) {
  const tags = matter.tags ?? [];
  if (tags.length === 0)
    return <span className="text-[var(--color-mute-2)]">—</span>;
  return (
    <div className="flex max-w-52 flex-wrap gap-1">
      {tags.slice(0, 2).map((tag) => (
        <Badge key={tag.id} tone="neutral" className="py-0.5">
          {tag.name}
        </Badge>
      ))}
      {tags.length > 2 ? (
        <span className="text-xs text-[var(--color-mute)]">
          +{tags.length - 2}
        </span>
      ) : null}
    </div>
  );
}

export default function MattersPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draftFilters, setDraftFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] =
    useState<FilterState>(EMPTY_FILTERS);
  const [bulkTagId, setBulkTagId] = useState<string>("none");
  const canCreateMatter = useCapability("matters:create");
  const canBulkImportMatters = useCapability("matters:bulk_import");
  const canEditMatters = useCapability("matters:edit");
  const canArchiveMatters = useCapability("matters:archive");
  const listParams = useMemo(
    () => ({
      q: appliedFilters.q.trim() || undefined,
      status:
        appliedFilters.status === "all" ? undefined : appliedFilters.status,
      forum_level:
        appliedFilters.forum_level === "all"
          ? undefined
          : appliedFilters.forum_level,
      tag: appliedFilters.tag === "all" ? undefined : appliedFilters.tag,
      min_claim_amount_minor: toMinor(appliedFilters.min_claim_amount),
      max_claim_amount_minor: toMinor(appliedFilters.max_claim_amount),
    }),
    [appliedFilters],
  );
  const {
    data,
    isPending,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["matters", "list", listParams],
    queryFn: ({ pageParam }) =>
      listMatters({
        limit: PAGE_SIZE,
        cursor: pageParam ?? null,
        ...listParams,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const { data: tagData } = useQuery({
    queryKey: ["matter-tags"],
    queryFn: listMatterTags,
  });
  const statusMutation = useMutation({
    mutationFn: (input: { matter: Matter; status: MatterStatusValue }) => {
      if (!input.matter.updated_at) {
        throw new Error("Refresh this matter before changing its status.");
      }
      return updateMatter({
        matterId: input.matter.id,
        status: input.status,
        expected_updated_at: input.matter.updated_at,
      });
    },
    onSuccess: async (matter) => {
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      toast.success(
        `Status updated to ${MATTER_STATUS_LABELS[matter.status] ?? matter.status}.`,
      );
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update matter status."));
    },
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
                v. {ctx.row.original.opposing_party ?? "—"} ·{" "}
                {ctx.row.original.client_name}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        accessorKey: "forum_level",
        header: "Forum",
        cell: (ctx) =>
          FORUMS[ctx.getValue<string>() ?? ""] ?? ctx.getValue<string>() ?? "—",
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
        accessorKey: "claim_amount_minor",
        header: "Claim",
        cell: (ctx) => (
          <span className="tabular-nums text-[var(--color-ink-2)]">
            {formatClaimAmount(ctx.row.original)}
          </span>
        ),
      },
      {
        id: "tags",
        header: "Tags",
        cell: (ctx) => <TagCell matter={ctx.row.original} />,
      },
      {
        accessorKey: "has_stay",
        header: "Interim/stay",
        cell: (ctx) => {
          const matter = ctx.row.original;
          return matter.has_stay || matter.has_interim_order ? (
            <div className="flex flex-wrap gap-1">
              {matter.has_stay ? <Badge tone="warning">Stay</Badge> : null}
              {matter.has_interim_order ? (
                <Badge tone="brand">Interim</Badge>
              ) : null}
            </div>
          ) : (
            <span className="text-[var(--color-mute-2)]">—</span>
          );
        },
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (ctx) => {
          const matter = ctx.row.original;
          if (!canEditMatters && !canArchiveMatters) {
            return <StatusBadge status={ctx.getValue<string>()} />;
          }
          const rowPending =
            statusMutation.isPending &&
            statusMutation.variables?.matter.id === matter.id;
          return (
            <div
              className="flex items-center gap-2"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {canEditMatters && matter.status !== "disposed" ? (
                <select
                  aria-label={`Status for ${matter.matter_code}`}
                  className="h-9 min-w-32 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm text-[var(--color-ink)]"
                  value={matter.status}
                  disabled={rowPending || !matter.updated_at}
                  onChange={(event) => {
                    const nextStatus = event.target.value as MatterStatusValue;
                    if (nextStatus !== matter.status) {
                      statusMutation.mutate({ matter, status: nextStatus });
                    }
                  }}
                >
                  {MATTER_STATUSES.map((statusOption) => (
                    <option key={statusOption.value} value={statusOption.value}>
                      {statusOption.label}
                    </option>
                  ))}
                </select>
              ) : (
                <StatusBadge status={matter.status} />
              )}
              {canArchiveMatters ? (
                <MatterLifecycleDialog
                  matter={matter}
                  compact
                  onChanged={async () => {
                    await queryClient.invalidateQueries({
                      queryKey: ["matters"],
                    });
                  }}
                />
              ) : null}
              {rowPending ? (
                <Loader2 className="h-4 w-4 animate-spin text-[var(--color-mute)]" />
              ) : null}
            </div>
          );
        },
      },
    ],
    [canArchiveMatters, canEditMatters, queryClient, statusMutation],
  );

  const matters = useMemo(
    () => data?.pages.flatMap((page) => page.matters) ?? [],
    [data],
  );
  const matterTags = tagData?.tags ?? [];
  const bulkMutation = useMutation({
    mutationFn: () =>
      bulkAssignMatterTag({
        matterIds: matters.map((matter) => matter.id),
        tagId: bulkTagId,
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      toast.success(
        `Tagged ${result.assigned_count} visible matter${result.assigned_count === 1 ? "" : "s"}`,
      );
    },
  });
  const hasActiveFilters = Object.entries(appliedFilters).some(
    ([key, value]) => value !== EMPTY_FILTERS[key as keyof FilterState],
  );

  function applyFilters() {
    setAppliedFilters({ ...draftFilters });
  }

  function clearFilters() {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
  }

  const filterPanel = (
    <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--color-line)] bg-white p-3">
      <div
        className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6"
        role="group"
        aria-label="Matter filters"
        data-testid="matter-filter-grid"
      >
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="matter-filter-q">Search</Label>
          <Input
            id="matter-filter-q"
            value={draftFilters.q}
            onChange={(event) =>
              setDraftFilters((prev) => ({ ...prev, q: event.target.value }))
            }
            placeholder="Party, code, court"
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label>Status</Label>
          <Select
            value={draftFilters.status}
            onValueChange={(value) =>
              setDraftFilters((prev) => ({ ...prev, status: value }))
            }
          >
            <SelectTrigger aria-label="Matter status filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="intake">Intake</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="on_hold">On hold</SelectItem>
              <SelectItem value="disposed">Dispose</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label>Forum</Label>
          <Select
            value={draftFilters.forum_level}
            onValueChange={(value) =>
              setDraftFilters((prev) => ({ ...prev, forum_level: value }))
            }
          >
            <SelectTrigger aria-label="Forum filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {Object.entries(FORUMS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label>Tag</Label>
          <Select
            value={draftFilters.tag}
            onValueChange={(value) =>
              setDraftFilters((prev) => ({ ...prev, tag: value }))
            }
          >
            <SelectTrigger aria-label="Tag filter">
              <SelectValue placeholder="All tags" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All tags</SelectItem>
              {matterTags.map((tag) => (
                <SelectItem key={tag.id} value={tag.slug}>
                  {tag.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="matter-filter-min-claim">Min claim</Label>
          <Input
            id="matter-filter-min-claim"
            inputMode="numeric"
            type="number"
            min={0}
            value={draftFilters.min_claim_amount}
            onChange={(event) =>
              setDraftFilters((prev) => ({
                ...prev,
                min_claim_amount: event.target.value,
              }))
            }
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="matter-filter-max-claim">Max claim</Label>
          <Input
            id="matter-filter-max-claim"
            inputMode="numeric"
            type="number"
            min={0}
            value={draftFilters.max_claim_amount}
            onChange={(event) =>
              setDraftFilters((prev) => ({
                ...prev,
                max_claim_amount: event.target.value,
              }))
            }
          />
        </div>
        <div className="flex min-w-0 flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-3 2xl:col-span-6">
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            onClick={applyFilters}
          >
            <Filter className="h-4 w-4" /> Apply
          </Button>
          {hasActiveFilters ? (
            <Button
              type="button"
              variant="ghost"
              className="w-full sm:w-auto"
              onClick={clearFilters}
            >
              <RotateCcw className="h-4 w-4" /> Reset
            </Button>
          ) : null}
        </div>
      </div>
      {canEditMatters && matterTags.length > 0 ? (
        <div className="flex flex-wrap items-end gap-2 border-t border-[var(--color-line)] pt-3">
          <div className="w-56">
            <Label>Bulk tag visible rows</Label>
            <Select value={bulkTagId} onValueChange={setBulkTagId}>
              <SelectTrigger aria-label="Bulk tag">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Choose tag</SelectItem>
                {matterTags.map((tag) => (
                  <SelectItem key={tag.id} value={tag.id}>
                    {tag.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={
              bulkTagId === "none" ||
              matters.length === 0 ||
              bulkMutation.isPending
            }
            onClick={() => bulkMutation.mutate()}
          >
            <Tags className="h-4 w-4" /> Tag visible
          </Button>
        </div>
      ) : null}
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matters"
        title="Matter portfolio"
        description="Every matter in your workspace. Click a row to open the cockpit."
        actions={
          canCreateMatter || canBulkImportMatters ? (
            <div className="flex flex-wrap gap-2">
              {canBulkImportMatters ? (
                <Button
                  variant="outline"
                  onClick={() => router.push("/app/matters/imports")}
                  data-testid="matter-import-trigger"
                >
                  <UploadCloud className="h-4 w-4" /> Bulk upload matters
                </Button>
              ) : null}
              {canCreateMatter ? <NewMatterDialog /> : null}
            </div>
          ) : null
        }
      />

      {!isPending && !isError ? filterPanel : null}

      {isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : isError ? (
        <QueryErrorState
          title="Could not load matters"
          error={error}
          onRetry={refetch}
        />
      ) : matters.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title={
            hasActiveFilters
              ? "No matters match these filters"
              : "No matters yet"
          }
          description={
            hasActiveFilters
              ? "Adjust or reset filters to return to the full matter portfolio."
              : canCreateMatter
                ? "Create your first matter to start tracking hearings, drafts, and billing."
                : "No matters are assigned to you yet. Ask an admin to add you to a matter."
          }
          action={
            hasActiveFilters ? (
              <Button type="button" variant="outline" onClick={clearFilters}>
                <RotateCcw className="h-4 w-4" /> Reset filters
              </Button>
            ) : canCreateMatter ? (
              <NewMatterDialog />
            ) : null
          }
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
