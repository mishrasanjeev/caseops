"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ExternalLink,
  Languages,
  Pencil,
  Plus,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createPlatformForumAlias,
  fetchForumCatalog,
  fetchPlatformForumAliases,
  updatePlatformForumAlias,
} from "@/lib/api/endpoints";
import type {
  ForumCatalogAliasRecord,
  ForumCatalogAliasType,
  ForumCatalogAliasVerificationStatus,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]";

const ALIAS_TYPES: Array<{ value: ForumCatalogAliasType; label: string }> = [
  { value: "court_complex", label: "Court complex" },
  { value: "abbreviation", label: "Abbreviation" },
  { value: "legacy_name", label: "Legacy name" },
  { value: "local_name", label: "Local name" },
  { value: "spelling_variant", label: "Spelling variant" },
  { value: "provider_label", label: "Provider label" },
  { value: "other", label: "Other" },
];

type AliasForm = {
  forumCatalogEntryId: string;
  alias: string;
  aliasType: ForumCatalogAliasType;
  sourceName: string;
  sourceUrl: string;
  verificationStatus: ForumCatalogAliasVerificationStatus;
  isActive: boolean;
  reason: string;
};

const EMPTY_FORM: AliasForm = {
  forumCatalogEntryId: "",
  alias: "",
  aliasType: "court_complex",
  sourceName: "",
  sourceUrl: "",
  verificationStatus: "pending",
  isActive: true,
  reason: "",
};

export default function PlatformForumAliasesPage() {
  const canManage = useCapability("platform:catalog_manage");
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [statusFilter, setStatusFilter] = useState<"all" | ForumCatalogAliasVerificationStatus>(
    "all",
  );
  const [activeFilter, setActiveFilter] = useState<"all" | "active" | "inactive">("all");
  const [catalogSearch, setCatalogSearch] = useState("");
  const [editing, setEditing] = useState<ForumCatalogAliasRecord | null>(null);
  const [form, setForm] = useState<AliasForm>(EMPTY_FORM);

  const aliasesQuery = useQuery({
    queryKey: ["platform-admin", "forum-aliases", deferredSearch, statusFilter, activeFilter],
    queryFn: () =>
      fetchPlatformForumAliases({
        q: deferredSearch || undefined,
        verification_status: statusFilter === "all" ? undefined : statusFilter,
        is_active: activeFilter === "all" ? undefined : activeFilter === "active",
        limit: 200,
      }),
    enabled: canManage,
  });
  const catalogQuery = useQuery({
    queryKey: ["forum-catalog"],
    queryFn: fetchForumCatalog,
    enabled: canManage,
    staleTime: 5 * 60_000,
  });

  const catalogOptions = useMemo(() => {
    const normalizedSearch = catalogSearch.trim().toLocaleLowerCase("en-IN");
    return (catalogQuery.data?.entries ?? [])
      .filter((entry) => {
        if (!normalizedSearch) return true;
        return [entry.name, entry.lineage, entry.state, entry.district]
          .filter(Boolean)
          .some((value) => value!.toLocaleLowerCase("en-IN").includes(normalizedSearch));
      })
      .slice(0, 150);
  }, [catalogQuery.data?.entries, catalogSearch]);

  const resetForm = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setCatalogSearch("");
  };
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["platform-admin", "forum-aliases"] }),
      queryClient.invalidateQueries({ queryKey: ["forum-catalog"] }),
    ]);
  };
  const createMutation = useMutation({
    mutationFn: () =>
      createPlatformForumAlias({
        forum_catalog_entry_id: form.forumCatalogEntryId,
        alias: form.alias.trim(),
        alias_type: form.aliasType,
        source_name: form.sourceName.trim(),
        source_url: form.sourceUrl.trim() || null,
        verification_status: form.verificationStatus,
        is_active: form.isActive,
        reason: form.reason.trim(),
      }),
    onSuccess: async () => {
      toast.success("Forum alias created.");
      resetForm();
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the alias.")),
  });
  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("Select an alias to update.");
      return updatePlatformForumAlias(editing.id, {
        alias: form.alias.trim(),
        alias_type: form.aliasType,
        source_name: form.sourceName.trim(),
        source_url: form.sourceUrl.trim() || null,
        verification_status: form.verificationStatus,
        is_active: form.verificationStatus === "rejected" ? false : form.isActive,
        expected_record_version: editing.record_version,
        reason: form.reason.trim(),
      });
    },
    onSuccess: async () => {
      toast.success("Forum alias updated.");
      resetForm();
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update the alias.")),
  });

  if (!canManage) {
    return (
      <div className="flex min-w-0 flex-col gap-6">
        <PageHeader eyebrow="Founder console" title="Forum aliases" />
        <EmptyState
          icon={ShieldAlert}
          title="Catalog curator access required"
          description="Only the configured platform catalog administrator can change the shared forum identity registry."
        />
      </div>
    );
  }

  const saveDisabled =
    !form.forumCatalogEntryId ||
    !form.alias.trim() ||
    !form.sourceName.trim() ||
    !form.reason.trim() ||
    (form.verificationStatus === "verified" && !form.sourceUrl.trim()) ||
    createMutation.isPending ||
    updateMutation.isPending;

  const editAlias = (row: ForumCatalogAliasRecord) => {
    setEditing(row);
    setCatalogSearch(row.canonical_name);
    setForm({
      forumCatalogEntryId: row.forum_catalog_entry_id,
      alias: row.alias,
      aliasType: row.alias_type,
      sourceName: row.source_name,
      sourceUrl: row.source_url ?? "",
      verificationStatus: row.verification_status,
      isActive: row.is_active,
      reason: "",
    });
    document.getElementById("forum-alias-editor")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="flex min-w-0 flex-col gap-8">
      <PageHeader
        eyebrow="Founder console · Legal catalog"
        title="Forum aliases"
        description="Maintain reviewed court-complex, local, legacy, and provider labels against one canonical all-India forum catalog."
        actions={
          <Button href="/app/platform-admin" variant="outline">
            Platform admin
          </Button>
        }
      />

      <section id="forum-alias-editor" className="border-y border-[var(--color-line)] py-6">
        <div className="mb-5 flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-[var(--color-ink)]">
              {editing ? "Edit reviewed alias" : "Add reviewed alias"}
            </h2>
            <p className="mt-1 text-sm text-[var(--color-mute)]">
              Verified aliases require an HTTPS source. Pending and rejected rows never resolve user input.
            </p>
          </div>
          {editing ? (
            <Button type="button" variant="ghost" onClick={resetForm}>
              <RotateCcw className="h-4 w-4" aria-hidden />
              Cancel edit
            </Button>
          ) : null}
        </div>

        <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div className="min-w-0 md:col-span-2 xl:col-span-1">
            <Label htmlFor="forum-catalog-search">Find canonical forum</Label>
            <Input
              id="forum-catalog-search"
              className="mt-1"
              value={catalogSearch}
              onChange={(event) => setCatalogSearch(event.target.value)}
              placeholder="Court, state, district, or lineage"
              disabled={Boolean(editing)}
            />
          </div>
          <div className="min-w-0 md:col-span-2">
            <Label htmlFor="forum-catalog-entry">Canonical forum</Label>
            <select
              id="forum-catalog-entry"
              className={`${SELECT_CLASS} mt-1`}
              value={form.forumCatalogEntryId}
              disabled={Boolean(editing) || catalogQuery.isPending}
              onChange={(event) =>
                setForm((current) => ({ ...current, forumCatalogEntryId: event.target.value }))
              }
            >
              <option value="">Select one active catalog entry</option>
              {catalogOptions.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.lineage}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <Label htmlFor="forum-alias">Alias</Label>
            <Input
              id="forum-alias"
              className="mt-1"
              value={form.alias}
              onChange={(event) => setForm((current) => ({ ...current, alias: event.target.value }))}
              placeholder="e.g. Saket Court"
            />
          </div>
          <div className="min-w-0">
            <Label htmlFor="forum-alias-type">Alias type</Label>
            <select
              id="forum-alias-type"
              className={`${SELECT_CLASS} mt-1`}
              value={form.aliasType}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  aliasType: event.target.value as ForumCatalogAliasType,
                }))
              }
            >
              {ALIAS_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <Label htmlFor="forum-alias-status">Verification</Label>
            <select
              id="forum-alias-status"
              className={`${SELECT_CLASS} mt-1`}
              value={form.verificationStatus}
              onChange={(event) => {
                const verificationStatus = event.target
                  .value as ForumCatalogAliasVerificationStatus;
                setForm((current) => ({
                  ...current,
                  verificationStatus,
                  isActive: verificationStatus === "rejected" ? false : current.isActive,
                }));
              }}
            >
              <option value="pending">Pending</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
          <div className="min-w-0">
            <Label htmlFor="forum-alias-source-name">Source name</Label>
            <Input
              id="forum-alias-source-name"
              className="mt-1"
              value={form.sourceName}
              onChange={(event) =>
                setForm((current) => ({ ...current, sourceName: event.target.value }))
              }
              placeholder="Registry or court directory"
            />
          </div>
          <div className="min-w-0 md:col-span-2">
            <Label htmlFor="forum-alias-source-url">Source URL</Label>
            <Input
              id="forum-alias-source-url"
              className="mt-1"
              type="url"
              value={form.sourceUrl}
              onChange={(event) =>
                setForm((current) => ({ ...current, sourceUrl: event.target.value }))
              }
              placeholder="https://official-source.example/..."
            />
          </div>
          <div className="min-w-0 md:col-span-2 xl:col-span-3">
            <Label htmlFor="forum-alias-reason">Change reason</Label>
            <Textarea
              id="forum-alias-reason"
              className="mt-1 min-h-20"
              value={form.reason}
              onChange={(event) => setForm((current) => ({ ...current, reason: event.target.value }))}
              placeholder="Record why this identity and source are being added or changed."
            />
          </div>
        </div>

        <div className="mt-4 flex min-w-0 flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm font-medium text-[var(--color-ink-2)]">
            <input
              type="checkbox"
              checked={form.isActive}
              disabled={form.verificationStatus === "rejected"}
              onChange={(event) =>
                setForm((current) => ({ ...current, isActive: event.target.checked }))
              }
            />
            Active registry row
          </label>
          <Button
            type="button"
            disabled={saveDisabled}
            onClick={() => (editing ? updateMutation.mutate() : createMutation.mutate())}
          >
            {editing ? <CheckCircle2 className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
            {editing ? "Save alias" : "Add alias"}
          </Button>
        </div>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex min-w-0 flex-wrap items-end gap-3">
          <div className="min-w-[14rem] flex-1">
            <Label htmlFor="forum-alias-search">Search registry</Label>
            <Input
              id="forum-alias-search"
              className="mt-1"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Alias, canonical court, state, or district"
            />
          </div>
          <div className="min-w-[10rem]">
            <Label htmlFor="forum-alias-filter-status">Filter verification</Label>
            <select
              id="forum-alias-filter-status"
              className={`${SELECT_CLASS} mt-1`}
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(
                  event.target.value as "all" | ForumCatalogAliasVerificationStatus,
                )
              }
            >
              <option value="all">All</option>
              <option value="pending">Pending</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
          <div className="min-w-[10rem]">
            <Label htmlFor="forum-alias-filter-active">Registry state</Label>
            <select
              id="forum-alias-filter-active"
              className={`${SELECT_CLASS} mt-1`}
              value={activeFilter}
              onChange={(event) =>
                setActiveFilter(event.target.value as "all" | "active" | "inactive")
              }
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        </div>

        {aliasesQuery.isPending ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : aliasesQuery.isError ? (
          <QueryErrorState
            title="Could not load forum aliases"
            error={aliasesQuery.error}
            onRetry={() => aliasesQuery.refetch()}
          />
        ) : aliasesQuery.data?.aliases.length ? (
          <div className="overflow-x-auto border-y border-[var(--color-line)]">
            <table className="w-full min-w-[980px] text-left text-sm" data-testid="forum-alias-registry">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase text-[var(--color-mute)]">
                <tr>
                  <th className="px-3 py-2">Alias</th>
                  <th className="px-3 py-2">Canonical forum</th>
                  <th className="px-3 py-2">Context</th>
                  <th className="px-3 py-2">Review</th>
                  <th className="px-3 py-2">Source</th>
                  <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {aliasesQuery.data.aliases.map((row) => (
                  <tr key={row.id} data-testid={`forum-alias-row-${row.id}`}>
                    <td className="px-3 py-3">
                      <div className="font-semibold text-[var(--color-ink)]">{row.alias}</div>
                      <div className="mt-1 text-xs text-[var(--color-mute)]">
                        {ALIAS_TYPES.find((type) => type.value === row.alias_type)?.label}
                      </div>
                    </td>
                    <td className="max-w-72 px-3 py-3">
                      <div className="font-medium text-[var(--color-ink-2)]">{row.canonical_name}</div>
                      <div className="mt-1 break-words text-xs text-[var(--color-mute)]">{row.lineage}</div>
                    </td>
                    <td className="px-3 py-3 text-[var(--color-ink-2)]">
                      {[row.state, row.district, row.city].filter(Boolean).join(" · ") || "National"}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <Badge tone={row.verification_status === "verified" ? "success" : "warning"}>
                          {row.verification_status}
                        </Badge>
                        <Badge tone={row.is_active ? "brand" : "warning"}>
                          {row.is_active ? "active" : "inactive"}
                        </Badge>
                      </div>
                    </td>
                    <td className="max-w-60 px-3 py-3">
                      <div className="break-words text-[var(--color-ink-2)]">{row.source_name}</div>
                      {row.source_url ? (
                        <a
                          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-[var(--color-brand-700)] hover:underline"
                          href={row.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open source <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                        </a>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Button type="button" size="sm" variant="outline" onClick={() => editAlias(row)}>
                        <Pencil className="h-4 w-4" aria-hidden />
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={Languages}
            title="No aliases match"
            description="Change the filters or add a source-backed alias to the registry."
          />
        )}
        {aliasesQuery.data?.has_more ? (
          <p className="mt-3 text-sm text-[var(--color-mute)]">
            The first 200 matches are shown. Narrow the search to reach the remaining rows.
          </p>
        ) : null}
      </section>
    </div>
  );
}
