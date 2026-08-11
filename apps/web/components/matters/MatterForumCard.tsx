"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gavel, Loader2, Pencil, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  ForumSelector,
  isConsumerDistrictFallbackForumSelection,
  isDistrictFallbackForumSelection,
  isLegacyForumSelection,
  type ForumSelection,
} from "@/components/matters/ForumSelector";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchForumCatalog, updateMatter } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import type { WorkspaceMatter } from "@/lib/api/workspace-types";

function selectionFromMatter(matter: WorkspaceMatter): ForumSelection {
  return {
    forum_category: matter.forum_catalog_entry_id
      ? undefined
      : matter.forum_level === "tribunal" && matter.forum_consumer_level
        ? matter.forum_consumer_level === "national"
          ? "ncdrc"
          : matter.forum_consumer_level === "state"
            ? "state_commission"
            : "district_commission"
        : matter.forum_level === "lower_court" && matter.forum_state
          ? "district_court"
          : "legacy",
    forum_level: matter.forum_level ?? "high_court",
    court_id: matter.court_id ?? null,
    court_name: matter.court_name ?? null,
    forum_catalog_entry_id: matter.forum_catalog_entry_id ?? null,
    forum_state: matter.forum_state ?? null,
    forum_district: matter.forum_district ?? null,
    forum_city: matter.forum_city ?? null,
    forum_consumer_level: matter.forum_consumer_level ?? null,
  };
}

function metadataLine(matter: WorkspaceMatter): string {
  return [
    matter.forum_state,
    matter.forum_district,
    matter.forum_city,
    matter.forum_consumer_level
      ? matter.forum_consumer_level.toUpperCase()
      : null,
  ]
    .filter(Boolean)
    .join(" / ");
}

export function MatterForumCard({ matter }: { matter: WorkspaceMatter }) {
  const canEdit = useCapability("matters:edit");
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editBaseUpdatedAt, setEditBaseUpdatedAt] = useState<string | null>(
    null,
  );
  const [selection, setSelection] = useState<ForumSelection>(() =>
    selectionFromMatter(matter),
  );
  const catalogQuery = useQuery({
    queryKey: ["courts", "forum-catalog"],
    queryFn: fetchForumCatalog,
    enabled: editing,
  });
  const catalogEntries = catalogQuery.data?.entries ?? [];
  const catalogEmpty = catalogQuery.isSuccess && catalogEntries.length === 0;
  const catalogFailed = catalogQuery.isError;
  const catalogUnavailable = catalogFailed || catalogEmpty;
  const selectedCatalogEntryMissing =
    catalogQuery.isSuccess &&
    Boolean(selection.forum_catalog_entry_id) &&
    !catalogEntries.some(
      (entry) => entry.id === selection.forum_catalog_entry_id,
    );
  const normalizedSelection: ForumSelection =
    selectedCatalogEntryMissing &&
    selection.forum_level === "lower_court" &&
    Boolean(selection.forum_state)
      ? {
          ...selection,
          forum_category: "district_court",
          court_id: null,
          forum_catalog_entry_id: null,
        }
      : selectedCatalogEntryMissing &&
          selection.forum_level === "tribunal" &&
          Boolean(selection.forum_consumer_level)
        ? {
            ...selection,
            forum_category:
              selection.forum_consumer_level === "national"
                ? "ncdrc"
                : selection.forum_consumer_level === "state"
                  ? "state_commission"
                  : "district_commission",
            court_id: null,
            forum_catalog_entry_id: null,
          }
        : selection;

  useEffect(() => {
    if (matter.status === "disposed") {
      setEditing(false);
      setEditBaseUpdatedAt(null);
      setSelection(selectionFromMatter(matter));
    } else if (!editing) {
      setSelection(selectionFromMatter(matter));
    }
  }, [editing, matter]);

  const mutation = useMutation({
    mutationFn: () =>
      updateMatter({
        matterId: matter.id,
        expected_updated_at: editBaseUpdatedAt ?? matter.updated_at,
        forum_level: normalizedSelection.forum_level,
        court_id: normalizedSelection.court_id,
        court_name: normalizedSelection.court_name,
        forum_catalog_entry_id: normalizedSelection.forum_catalog_entry_id,
        forum_state: normalizedSelection.forum_state,
        forum_district: normalizedSelection.forum_district,
        forum_city: normalizedSelection.forum_city,
        forum_consumer_level: normalizedSelection.forum_consumer_level,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["matters", matter.id, "workspace"],
        }),
        queryClient.invalidateQueries({ queryKey: ["matters"] }),
      ]);
      toast.success("Forum updated.");
      setEditing(false);
      setEditBaseUpdatedAt(null);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update forum."));
    },
  });

  const details = metadataLine(matter);
  const legacyFallbackSelected = isLegacyForumSelection(normalizedSelection);
  const legacyFallbackIncomplete =
    catalogUnavailable &&
    legacyFallbackSelected &&
    !normalizedSelection.court_name?.trim();
  const districtFallbackIncomplete =
    isDistrictFallbackForumSelection(normalizedSelection) &&
    (!normalizedSelection.forum_district?.trim() ||
      !normalizedSelection.court_name?.trim());
  const consumerDistrictFallbackIncomplete =
    isConsumerDistrictFallbackForumSelection(normalizedSelection) &&
    (!normalizedSelection.forum_district?.trim() ||
      !normalizedSelection.court_name?.trim());
  const forumSaveBlocked =
    catalogQuery.isPending ||
    (catalogUnavailable && !legacyFallbackSelected) ||
    legacyFallbackIncomplete ||
    districtFallbackIncomplete ||
    consumerDistrictFallbackIncomplete;
  const catalogStatusMessage = catalogQuery.isPending
    ? "Loading forum catalog before editing."
    : catalogFailed
      ? "Forum catalog could not be loaded. Select Other / uncatalogued and enter a court or forum name to use the legacy fallback."
      : catalogEmpty
        ? "Forum catalog is empty. Select Other / uncatalogued and enter a court or forum name to use the legacy fallback."
        : null;
  const catalogStatusTone = catalogFailed
    ? "error"
    : catalogEmpty
      ? "warning"
      : "info";

  return (
    <Card data-testid="matter-forum-card">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Gavel className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
            Forum
          </CardTitle>
          <CardDescription>
            Structured forum selection for court and filing context.
          </CardDescription>
        </div>
        {canEdit && matter.status !== "disposed" && !editing ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditBaseUpdatedAt(matter.updated_at);
              setEditing(true);
            }}
            data-testid="matter-forum-edit"
          >
            <Pencil className="h-4 w-4" aria-hidden />
            Edit
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="flex flex-col gap-3">
            <ForumSelector
              entries={catalogEntries}
              value={normalizedSelection}
              onChange={setSelection}
              disabled={catalogQuery.isPending || mutation.isPending}
              idPrefix="matter-edit-forum"
              statusMessage={catalogStatusMessage}
              statusTone={catalogStatusTone}
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSelection(selectionFromMatter(matter));
                  setEditing(false);
                  setEditBaseUpdatedAt(null);
                }}
              >
                <X className="h-4 w-4" aria-hidden />
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={mutation.isPending || forumSaveBlocked}
                onClick={() => mutation.mutate()}
                data-testid="matter-forum-save"
              >
                {mutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Save className="h-4 w-4" aria-hidden />
                )}
                Save
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="text-sm font-semibold text-[var(--color-ink)]">
              {matter.court_name ?? "No court selected"}
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
              <span className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5">
                {(matter.forum_level ?? "uncategorized").replace(/_/g, " ")}
              </span>
              {details ? (
                <span className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5">
                  {details}
                </span>
              ) : null}
              {matter.forum_catalog_entry_id ? (
                <span className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5">
                  Catalogued
                </span>
              ) : (
                <span className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5">
                  Legacy fallback
                </span>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
