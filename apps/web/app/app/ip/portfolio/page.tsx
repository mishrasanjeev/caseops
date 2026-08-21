"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookmarkPlus,
  Check,
  Download,
  LayoutGrid,
  List,
  LoaderCircle,
  RotateCcw,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
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
import { apiErrorMessage } from "@/lib/api/config";
import {
  createIpPortfolioExport,
  createIpPortfolioSavedView,
  deleteIpPortfolioSavedView,
  downloadIpPortfolioExport,
  fetchIpPortfolio,
  listIpPortfolioExports,
  listIpPortfolioSavedViews,
  previewIpPortfolioExport,
  retryIpPortfolioExport,
  updateIpPortfolioSavedView,
  type IpPortfolioFilters,
  type IpPortfolioResponse,
  type IpPortfolioRow,
  type IpPortfolioSavedView,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const COLUMN_OPTIONS = [
  ["mark", "Mark"],
  ["representation", "Representation"],
  ["application_numbers", "Application no."],
  ["opposition_numbers", "Opposition no."],
  ["classes", "Classes"],
  ["goods_services", "Goods/services"],
  ["jurisdiction", "Jurisdiction"],
  ["office", "Office"],
  ["status", "Status"],
  ["phase", "Filing phase"],
  ["proprietors", "Proprietors"],
  ["agents", "Agents"],
  ["client", "Client"],
  ["responsible_lawyer", "Responsible lawyer"],
  ["team", "Team"],
  ["deadlines", "Deadlines"],
  ["data_quality", "Data quality"],
  ["registry_sync", "Registry sync"],
  ["created_at", "Created"],
  ["updated_at", "Updated"],
] as const;

type ColumnKey = (typeof COLUMN_OPTIONS)[number][0];

const DEFAULT_COLUMNS: ColumnKey[] = [
  "mark",
  "application_numbers",
  "opposition_numbers",
  "classes",
  "jurisdiction",
  "status",
  "deadlines",
  "data_quality",
];

const EMPTY_FILTERS: IpPortfolioFilters = {
  query: null,
  client: [],
  proprietor: [],
  nice_class: [],
  jurisdiction: [],
  office: [],
  filing_phase: [],
  docket_status: [],
  deadline_state: [],
  opposition_only: false,
  registry_sync_state: [],
  include_inactive: false,
};

function one(value: string) {
  return value === "all" ? [] : [value];
}

function first(values: string[] | undefined) {
  return values?.[0] ?? "all";
}

export default function IpPortfolioPage() {
  const canView = useCapability("ip:read");
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<IpPortfolioFilters>(EMPTY_FILTERS);
  const [queryDraft, setQueryDraft] = useState("");
  const [columns, setColumns] = useState<ColumnKey[]>(DEFAULT_COLUMNS);
  const [selectedViewId, setSelectedViewId] = useState("none");
  const [saveOpen, setSaveOpen] = useState(false);
  const [viewName, setViewName] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [exportPreview, setExportPreview] = useState<Awaited<
    ReturnType<typeof previewIpPortfolioExport>
  > | null>(null);

  const listing = useInfiniteQuery({
    queryKey: ["ip", "portfolio", filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => fetchIpPortfolio(filters, { limit: 50, cursor: pageParam }),
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: canView,
  });
  const savedViews = useQuery({
    queryKey: ["ip", "portfolio", "views"],
    queryFn: listIpPortfolioSavedViews,
    enabled: canView,
  });
  const exports = useQuery({
    queryKey: ["ip", "portfolio", "exports"],
    queryFn: listIpPortfolioExports,
    enabled: canView,
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => job.status === "pending" || job.status === "running")
        ? 1500
        : false,
  });
  const rows = useMemo(
    () => listing.data?.pages.flatMap((page) => page.rows) ?? [],
    [listing.data],
  );
  const counts = listing.data?.pages[0]?.counts;
  const selectedView = savedViews.data?.views.find((view) => view.id === selectedViewId);

  const saveView = useMutation({
    mutationFn: async () => {
      if (selectedView?.editable) {
        return updateIpPortfolioSavedView({
          id: selectedView.id,
          name: viewName.trim(),
          filters,
          columns,
          isDefault: selectedView.is_default,
          expectedVersion: selectedView.version,
          scope: selectedView.scope,
          teamId: selectedView.team_id,
        });
      }
      return createIpPortfolioSavedView({
        name: viewName.trim(),
        filters,
        columns,
      });
    },
    onSuccess: async (view) => {
      toast.success(selectedView?.editable ? "Saved view updated." : "View saved.");
      setSelectedViewId(view.id);
      setSaveOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["ip", "portfolio", "views"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save this view.")),
  });

  const removeView = useMutation({
    mutationFn: deleteIpPortfolioSavedView,
    onSuccess: async () => {
      setSelectedViewId("none");
      toast.success("Saved view removed.");
      await queryClient.invalidateQueries({ queryKey: ["ip", "portfolio", "views"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not remove this view.")),
  });

  const previewExport = useMutation({
    mutationFn: () => previewIpPortfolioExport({ filters, columns, rowLimit: 50000 }),
    onSuccess: setExportPreview,
    onError: (error) => toast.error(apiErrorMessage(error, "Could not preview the export.")),
  });

  const createExport = useMutation({
    mutationFn: () => {
      if (!exportPreview) throw new Error("Export preview is required.");
      return createIpPortfolioExport({
        filters,
        columns,
        rowLimit: 50000,
        previewToken: exportPreview.preview_token,
      });
    },
    onSuccess: async () => {
      toast.success("Portfolio export queued.");
      setExportPreview(null);
      await queryClient.invalidateQueries({ queryKey: ["ip", "portfolio", "exports"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not queue the export.")),
  });

  const retryExport = useMutation({
    mutationFn: retryIpPortfolioExport,
    onSuccess: async () => {
      toast.success("Portfolio export requeued.");
      await queryClient.invalidateQueries({ queryKey: ["ip", "portfolio", "exports"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not retry the export.")),
  });

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setFilters((current) => ({ ...current, query: queryDraft.trim() || null }));
  };

  const applyView = (id: string) => {
    setSelectedViewId(id);
    if (id === "none") return;
    const view = savedViews.data?.views.find((candidate) => candidate.id === id);
    if (!view) return;
    setFilters(view.filters);
    setQueryDraft(view.filters.query ?? "");
    setColumns(view.columns.filter(isColumnKey));
  };

  if (!canView) {
    return (
      <EmptyState
        title="IP portfolio access required"
        description="Your role does not include permission to view intellectual-property records."
      />
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Intellectual property"
        title="Trademark portfolio"
        actions={
          <>
            <div className="flex rounded-md border border-[var(--color-line)] p-0.5">
              <Button
                size="sm"
                variant={viewMode === "list" ? "secondary" : "ghost"}
                aria-label="List view"
                title="List view"
                onClick={() => setViewMode("list")}
              >
                <List className="h-4 w-4" aria-hidden />
              </Button>
              <Button
                size="sm"
                variant={viewMode === "grid" ? "secondary" : "ghost"}
                aria-label="Grid view"
                title="Grid view"
                onClick={() => setViewMode("grid")}
              >
                <LayoutGrid className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            <Button size="sm" variant="outline" href="/app/ip/portfolio/imports">
              <Upload className="h-4 w-4" aria-hidden /> Import
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setViewName(selectedView?.editable ? selectedView.name : "");
                setSaveOpen(true);
              }}
            >
              <BookmarkPlus className="h-4 w-4" aria-hidden />
              {selectedView?.editable ? "Update view" : "Save view"}
            </Button>
            <Button
              size="sm"
              disabled={previewExport.isPending || createExport.isPending}
              onClick={() => previewExport.mutate()}
            >
              {previewExport.isPending || createExport.isPending ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Download className="h-4 w-4" aria-hidden />
              )}
              Export
            </Button>
          </>
        }
      />

      <section aria-label="Portfolio controls" className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:items-end">
          <form className="flex min-w-0 flex-1 gap-2" onSubmit={submitSearch}>
            <div className="min-w-0 flex-1">
              <Label htmlFor="ip-portfolio-search" className="sr-only">
                Search marks and registry numbers
              </Label>
              <Input
                id="ip-portfolio-search"
                value={queryDraft}
                onChange={(event) => setQueryDraft(event.target.value)}
                placeholder="Mark, application number, opposition number"
              />
            </div>
            <Button type="submit" variant="outline" aria-label="Search portfolio">
              <Search className="h-4 w-4" aria-hidden />
            </Button>
          </form>

          <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4 xl:flex xl:w-auto">
            <FilterSelect
              label="Jurisdiction"
              value={first(filters.jurisdiction)}
              options={[["all", "All jurisdictions"], ["IN", "India"], ["GB", "United Kingdom"], ["US", "United States"]]}
              onChange={(value) => setFilters((current) => ({ ...current, jurisdiction: one(value) }))}
            />
            <FilterSelect
              label="Phase"
              value={first(filters.filing_phase)}
              options={[["all", "All phases"], ["draft", "Draft"], ["pre_filing", "Pre-filing"], ["filed", "Filed"]]}
              onChange={(value) => setFilters((current) => ({ ...current, filing_phase: one(value) }))}
            />
            <FilterSelect
              label="Status"
              value={first(filters.docket_status)}
              options={[["all", "All statuses"], ["draft", "Draft"], ["ready", "Ready"], ["on_hold", "On hold"], ["closed", "Closed"]]}
              onChange={(value) => setFilters((current) => ({ ...current, docket_status: one(value) }))}
            />
            <Select value={selectedViewId} onValueChange={applyView}>
              <SelectTrigger aria-label="Saved view" className="min-w-0 xl:w-44">
                <SelectValue placeholder="Saved view" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Current filters</SelectItem>
                {(savedViews.data?.views ?? []).map((view) => (
                  <SelectItem key={view.id} value={view.id}>
                    {view.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" aria-label="Choose portfolio columns">
                <Settings2 className="h-4 w-4" aria-hidden /> Columns
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-80 w-56 overflow-y-auto p-2">
              <DropdownMenuLabel>Visible columns</DropdownMenuLabel>
              {COLUMN_OPTIONS.map(([key, label]) => {
                const checked = columns.includes(key);
                return (
                  <label
                    key={key}
                    className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-[var(--color-bg-2)]"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        setColumns((current) =>
                          checked
                            ? current.length > 1
                              ? current.filter((column) => column !== key)
                              : current
                            : [...current, key],
                        );
                      }}
                    />
                    <span>{label}</span>
                  </label>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" aria-label="More portfolio filters">
                <SlidersHorizontal className="h-4 w-4" aria-hidden /> Filters
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72 space-y-3 p-3">
              <DropdownMenuLabel>Additional filters</DropdownMenuLabel>
              <div className="space-y-1">
                <Label htmlFor="portfolio-client-filter">Client</Label>
                <Input
                  id="portfolio-client-filter"
                  value={filters.client?.[0] ?? ""}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      client: event.target.value ? [event.target.value] : [],
                    }))
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="portfolio-proprietor-filter">Proprietor</Label>
                <Input
                  id="portfolio-proprietor-filter"
                  value={filters.proprietor?.[0] ?? ""}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      proprietor: event.target.value ? [event.target.value] : [],
                    }))
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="portfolio-class-filter">Nice class</Label>
                <Input
                  id="portfolio-class-filter"
                  inputMode="numeric"
                  value={filters.nice_class?.[0] ?? ""}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    setFilters((current) => ({
                      ...current,
                      nice_class:
                        Number.isInteger(value) && value >= 1 && value <= 45 ? [value] : [],
                    }));
                  }}
                />
              </div>
              <FilterSelect
                label="Deadline state"
                value={first(filters.deadline_state)}
                options={[
                  ["all", "All deadline states"],
                  ["open", "Open"],
                  ["unconfirmed", "Unconfirmed"],
                  ["overdue", "Overdue"],
                ]}
                onChange={(value) =>
                  setFilters((current) => ({ ...current, deadline_state: one(value) }))
                }
              />
              <FilterSelect
                label="Registry freshness"
                value={first(filters.registry_sync_state)}
                options={[
                  ["all", "All freshness states"],
                  ["current", "Current"],
                  ["stale", "Stale"],
                  ["failed", "Failed"],
                  ["unavailable", "Unavailable"],
                ]}
                onChange={(value) =>
                  setFilters((current) => ({
                    ...current,
                    registry_sync_state:
                      value === "all"
                        ? []
                        : [value as "current" | "stale" | "failed" | "unavailable"],
                  }))
                }
              />
              <label className="flex min-h-9 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={filters.opposition_only ?? false}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      opposition_only: event.target.checked,
                    }))
                  }
                />
                Opposition records only
              </label>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {counts ? <PortfolioCounts counts={counts} /> : null}
      </section>

      {listing.isPending ? (
        <div className="flex flex-col gap-2" role="status" aria-label="Loading trademark portfolio">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : listing.isError ? (
        <QueryErrorState
          error={listing.error}
          title="Could not load the trademark portfolio"
          onRetry={() => listing.refetch()}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No matching trademark records"
          description="Change the current filters or add a trademark record from the IP docket."
          action={<Button href="/app/ip">Open IP docket</Button>}
        />
      ) : (
        <>
          {viewMode === "list" ? (
            <>
              <PortfolioTable rows={rows} columns={columns} />
              <PortfolioCards rows={rows} columns={columns} />
            </>
          ) : (
            <PortfolioCards rows={rows} columns={columns} forceGrid />
          )}
          {listing.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                disabled={listing.isFetchingNextPage}
                onClick={() => listing.fetchNextPage()}
              >
                {listing.isFetchingNextPage ? "Loading" : "Load more"}
              </Button>
            </div>
          ) : null}
        </>
      )}

      <ExportQueue
        jobs={exports.data?.jobs ?? []}
        onRetry={(id) => retryExport.mutate(id)}
        onDownload={async (id) => {
          try {
            const blob = await downloadIpPortfolioExport(id);
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = `trademark-portfolio-${id}.csv`;
            anchor.click();
            URL.revokeObjectURL(url);
          } catch (error) {
            toast.error(apiErrorMessage(error, "Could not download the portfolio export."));
          }
        }}
      />

      <Dialog open={exportPreview !== null} onOpenChange={(open) => !open && setExportPreview(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm portfolio export</DialogTitle>
            <DialogDescription>
              {exportPreview?.row_count ?? 0} accessible records will be included
              {exportPreview?.truncated ? " up to the 50,000 row limit" : ""}.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-wrap gap-2 text-sm text-[var(--color-mute)]">
            <Badge>{exportPreview?.columns.length ?? 0} columns</Badge>
            <Badge tone="success">Permission scope checked</Badge>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setExportPreview(null)}>
              Cancel
            </Button>
            <Button disabled={createExport.isPending} onClick={() => createExport.mutate()}>
              {createExport.isPending ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Download className="h-4 w-4" aria-hidden />
              )}
              Queue export
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selectedView?.editable ? "Update saved view" : "Save current view"}
            </DialogTitle>
            <DialogDescription>The current filters and visible columns will be saved.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="portfolio-view-name">View name</Label>
            <Input
              id="portfolio-view-name"
              value={viewName}
              maxLength={120}
              onChange={(event) => setViewName(event.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            {selectedView?.editable ? (
              <Button
                variant="ghost"
                disabled={removeView.isPending}
                onClick={() => removeView.mutate(selectedView.id)}
              >
                <Trash2 className="h-4 w-4" aria-hidden /> Delete
              </Button>
            ) : null}
            <Button
              disabled={viewName.trim().length === 0 || saveView.isPending}
              onClick={() => saveView.mutate()}
            >
              <Check className="h-4 w-4" aria-hidden /> Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function isColumnKey(value: string): value is ColumnKey {
  return COLUMN_OPTIONS.some(([key]) => key === value);
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className="min-w-0 xl:w-40">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(([key, text]) => (
          <SelectItem key={key} value={key}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function PortfolioCounts({ counts }: { counts: IpPortfolioResponse["counts"] }) {
  const items = [
    ["Total", counts.total],
    ["Complete", counts.complete_records],
    ["Incomplete", counts.incomplete_records],
    ["Unconfirmed deadlines", counts.unconfirmed_deadline_records],
    ["Overdue", counts.overdue_records],
    ["Stale sync", counts.stale_sync_records],
  ];
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2 border-y border-[var(--color-line)] py-3 text-sm">
      {items.map(([label, value]) => (
        <span key={label} className="flex items-baseline gap-1.5">
          <strong className="tabular-nums text-[var(--color-ink)]">{value}</strong>
          <span className="text-[var(--color-mute)]">{label}</span>
        </span>
      ))}
      {counts.sync_failure_records === null ? (
        <Badge tone="warning">Registry sync unavailable</Badge>
      ) : (
        <Badge tone={counts.sync_failure_records ? "warning" : "success"}>
          {counts.sync_failure_records} sync failures
        </Badge>
      )}
    </div>
  );
}

function PortfolioTable({ rows, columns }: { rows: IpPortfolioRow[]; columns: ColumnKey[] }) {
  return (
    <div className="hidden min-w-0 overflow-x-auto border-y border-[var(--color-line)] md:block">
      <table className="w-full min-w-[980px] table-fixed border-collapse text-left text-sm">
        <thead className="bg-[var(--color-bg-2)] text-xs font-semibold text-[var(--color-mute)]">
          <tr>
            {columns.map((column) => (
              <th key={column} className="w-44 px-3 py-2.5">
                {COLUMN_OPTIONS.find(([key]) => key === column)?.[1]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-line)]">
          {rows.map((row) => (
            <tr key={row.application_id} className="align-top hover:bg-[var(--color-bg-2)]/60">
              {columns.map((column) => (
                <td key={column} className="px-3 py-3">
                  <PortfolioValue row={row} column={column} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioCards({
  rows,
  columns,
  forceGrid = false,
}: {
  rows: IpPortfolioRow[];
  columns: ColumnKey[];
  forceGrid?: boolean;
}) {
  return (
    <div
      className={
        forceGrid
          ? "grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-3"
          : "flex flex-col divide-y divide-[var(--color-line)] border-y border-[var(--color-line)] md:hidden"
      }
    >
      {rows.map((row) => (
        <article
          key={row.application_id}
          className={`grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 py-4 ${
            forceGrid ? "rounded-md border border-[var(--color-line)] px-4" : ""
          }`}
        >
          {columns.map((column) => (
            <div key={column} className="contents">
              <span className="text-xs font-medium text-[var(--color-mute)]">
                {COLUMN_OPTIONS.find(([key]) => key === column)?.[1]}
              </span>
              <div className="min-w-0 text-sm">
                <PortfolioValue row={row} column={column} />
              </div>
            </div>
          ))}
        </article>
      ))}
    </div>
  );
}

function PortfolioValue({ row, column }: { row: IpPortfolioRow; column: ColumnKey }) {
  switch (column) {
    case "mark":
      return (
        <Link href={`/app/ip?docket=${row.docket_id}`} className="font-semibold text-[var(--color-brand-700)] hover:underline">
          {row.asset_title ?? row.docket_title}
        </Link>
      );
    case "representation":
      return <ListValue values={row.representation_kinds} />;
    case "application_numbers":
      return <ListValue values={row.application_numbers} mono />;
    case "opposition_numbers":
      return <ListValue values={row.opposition_numbers} mono />;
    case "classes":
      return <ListValue values={row.nice_classes.map(String)} />;
    case "goods_services":
      return <ListValue values={row.goods_services} />;
    case "jurisdiction":
      return row.jurisdiction ?? "Not recorded";
    case "office":
      return row.office ?? "Not recorded";
    case "status":
      return <Badge>{row.docket_status.replaceAll("_", " ")}</Badge>;
    case "phase":
      return row.filing_phase.replaceAll("_", " ");
    case "proprietors":
      return <ListValue values={row.proprietors} />;
    case "agents":
      return <ListValue values={row.agents} />;
    case "client":
      return row.client_name ?? "Not linked";
    case "responsible_lawyer":
      return row.responsible_lawyer ?? "Not assigned";
    case "team":
      return row.team_name ?? "Firm-wide";
    case "deadlines":
      return (
        <span className="tabular-nums">
          {row.open_deadline_count} open · {row.unconfirmed_deadline_count} unconfirmed · {row.overdue_deadline_count} overdue
        </span>
      );
    case "data_quality":
      return row.record_complete ? (
        <Badge tone="success">Complete</Badge>
      ) : (
        <Badge tone="warning">{row.incomplete_reasons.length} gaps</Badge>
      );
    case "registry_sync":
      return (
        <Badge tone={row.registry_sync_state === "current" ? "success" : "warning"}>
          {row.registry_sync_state}
        </Badge>
      );
    case "created_at":
      return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(
        new Date(row.application_created_at),
      );
    case "updated_at":
      return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(row.updated_at));
  }
}

function ListValue({ values, mono = false }: { values: string[]; mono?: boolean }) {
  if (values.length === 0) return <span className="text-[var(--color-mute)]">Not recorded</span>;
  return <span className={mono ? "font-mono text-xs" : "break-words"}>{values.join(", ")}</span>;
}

function ExportQueue({
  jobs,
  onDownload,
  onRetry,
}: {
  jobs: Array<{
    id: string;
    status: "pending" | "running" | "completed" | "failed";
    row_count: number | null;
    download_ready: boolean;
    error: string | null;
  }>;
  onDownload: (id: string) => Promise<void>;
  onRetry: (id: string) => void;
}) {
  if (jobs.length === 0) return null;
  return (
    <section aria-labelledby="portfolio-exports" className="border-t border-[var(--color-line)] pt-5">
      <h2 id="portfolio-exports" className="text-base font-semibold">
        Recent exports
      </h2>
      <div className="mt-2 flex flex-col divide-y divide-[var(--color-line)]">
        {jobs.slice(0, 5).map((job) => (
          <div key={job.id} className="flex min-w-0 items-center justify-between gap-3 py-2.5 text-sm">
            <div className="min-w-0">
              <span className="font-mono text-xs">{job.id.slice(0, 8)}</span>
              <span className="ml-2 text-[var(--color-mute)]">
                {job.status === "completed" ? `${job.row_count ?? 0} rows` : job.status}
              </span>
              {job.error ? <span className="ml-2 text-red-700">{job.error}</span> : null}
            </div>
            {job.download_ready ? (
              <Button size="sm" variant="ghost" onClick={() => onDownload(job.id)} aria-label="Download export">
                <Download className="h-4 w-4" aria-hidden />
              </Button>
            ) : job.status === "pending" || job.status === "running" ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--color-mute)]" aria-label="Export running" />
            ) : job.status === "failed" ? (
              <Button size="sm" variant="ghost" onClick={() => onRetry(job.id)} aria-label="Retry export">
                <RotateCcw className="h-4 w-4" aria-hidden />
              </Button>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
