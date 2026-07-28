"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardList,
  Loader2,
  MessageSquareText,
  Pencil,
  Save,
  X,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { CounselRecommendationsCard } from "@/components/app/CounselRecommendationsCard";
import { BenchStrategyPanel } from "@/components/matter/BenchStrategyPanel";
import { ConflictCheckCard } from "@/components/matters/ConflictCheckCard";
import { MatterLifecycleDialog } from "@/components/matters/MatterLifecycleDialog";
import { MatterForumCard } from "@/components/matters/MatterForumCard";
import { NextActionCard } from "@/components/matters/NextActionCard";
import { OrderBadges } from "@/components/matters/OrderBadges";
import { ScheduleHearingDialog } from "@/components/matters/ScheduleHearingDialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage, isApiErrorShape } from "@/lib/api/config";
import { updateMatter } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";
import { normalizeMatterCodeInput } from "@/lib/matter-code";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  if (!withTime) {
    return formatLegalDate(value, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  }
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type MatterEditDraft = {
  title: string;
  matterCode: string;
  clientName: string;
  opposingParty: string;
  caseNumber: string;
  cnrNumber: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  practiceArea: string;
  forumLevel: string;
  courtName: string;
  courtForumNumber: string;
  judgeName: string;
  nextHearingOn: string;
  description: string;
};

const STATUS_OPTIONS: Array<{ value: MatterEditDraft["status"]; label: string }> = [
  { value: "intake", label: "Intake" },
  { value: "active", label: "Active" },
  { value: "on_hold", label: "On hold" },
];

const FORUM_LEVEL_OPTIONS = [
  { value: "lower_court", label: "Lower court" },
  { value: "high_court", label: "High court" },
  { value: "supreme_court", label: "Supreme Court" },
  { value: "tribunal", label: "Tribunal" },
  { value: "arbitration", label: "Arbitration" },
  { value: "advisory", label: "Advisory" },
] as const;

function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function draftFromMatter(matter: Matter): MatterEditDraft {
  return {
    title: matter.title ?? "",
    matterCode: matter.matter_code ?? "",
    clientName: matter.client_name ?? "",
    opposingParty: matter.opposing_party ?? "",
    caseNumber: matter.case_number ?? "",
    cnrNumber: matter.cnr_number ?? "",
    status: matter.status as MatterEditDraft["status"],
    practiceArea: matter.practice_area ?? "",
    forumLevel: matter.forum_level ?? "",
    courtName: matter.court_name ?? "",
    courtForumNumber: matter.court_forum_number ?? "",
    judgeName: matter.judge_name ?? "",
    nextHearingOn: matter.next_hearing_on ?? "",
    description: matter.description ?? "",
  };
}

type MatterUpdateInput = Parameters<typeof updateMatter>[0];

/** Build a PATCH from fields the user actually changed.
 *
 * Sending a whole record from a stale editor was the primary accidental
 * reopening path: a title edit could replay an old Active status after another
 * user disposed the matter. The timestamp precondition is still mandatory,
 * but omitting untouched fields also makes the intent explicit.
 */
function buildMatterUpdateInput(
  matterId: string,
  matter: Matter,
  draft: MatterEditDraft,
): MatterUpdateInput {
  const input: MatterUpdateInput = {
    matterId,
    expected_updated_at: matter.updated_at,
  };
  const title = draft.title.trim();
  const matterCode = normalizeMatterCodeInput(draft.matterCode);
  const practiceArea = draft.practiceArea.trim();
  const forumLevel = draft.forumLevel.trim();
  const clientName = blankToNull(draft.clientName);
  const opposingParty = blankToNull(draft.opposingParty);
  const caseNumber = blankToNull(draft.caseNumber);
  const cnrNumber = blankToNull(draft.cnrNumber);
  const courtName = blankToNull(draft.courtName);
  const courtForumNumber = blankToNull(draft.courtForumNumber);
  const judgeName = blankToNull(draft.judgeName);
  const nextHearingOn = draft.nextHearingOn || null;
  const description = blankToNull(draft.description);

  if (title !== matter.title) input.title = title;
  if (matterCode !== matter.matter_code) input.matter_code = matterCode;
  if (clientName !== (matter.client_name ?? null)) input.client_name = clientName;
  if (opposingParty !== (matter.opposing_party ?? null)) {
    input.opposing_party = opposingParty;
  }
  if (caseNumber !== (matter.case_number ?? null)) input.case_number = caseNumber;
  if (cnrNumber !== (matter.cnr_number ?? null)) input.cnr_number = cnrNumber;
  if (practiceArea !== (matter.practice_area ?? "")) {
    input.practice_area = practiceArea;
  }
  if (forumLevel !== (matter.forum_level ?? "")) input.forum_level = forumLevel;
  if (courtName !== (matter.court_name ?? null)) input.court_name = courtName;
  if (courtForumNumber !== (matter.court_forum_number ?? null)) {
    input.court_forum_number = courtForumNumber;
  }
  if (judgeName !== (matter.judge_name ?? null)) input.judge_name = judgeName;
  if (nextHearingOn !== (matter.next_hearing_on ?? null)) {
    input.next_hearing_on = nextHearingOn;
  }
  if (description !== (matter.description ?? null)) input.description = description;
  if (
    draft.status !== matter.status &&
    draft.status !== "disposed" &&
    matter.status !== "disposed"
  ) {
    input.status = draft.status;
  }
  return input;
}

function hasMatterChanges(input: MatterUpdateInput): boolean {
  return Object.keys(input).some(
    (key) => key !== "matterId" && key !== "expected_updated_at",
  );
}

function MatterDetail({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 text-sm text-[var(--color-ink)]">{value || "-"}</div>
    </div>
  );
}

export default function MatterOverviewPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data } = useMatterWorkspace(params.id);
  const canEditMatter = useCapability("matters:edit");
  const canArchiveMatter = useCapability("matters:archive");
  const [isEditingMatter, setIsEditingMatter] = useState(false);
  const [matterDraft, setMatterDraft] = useState<MatterEditDraft | null>(null);
  const [matterEditBase, setMatterEditBase] = useState<Matter | null>(null);
  const [matterEditConcurrencyError, setMatterEditConcurrencyError] =
    useState<string | null>(null);
  const matterMutation = useMutation({
    mutationFn: (input: MatterUpdateInput) => updateMatter(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", params.id, "workspace"],
      });
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      toast.success("Matter updated.");
      setIsEditingMatter(false);
      setMatterDraft(null);
      setMatterEditBase(null);
      setMatterEditConcurrencyError(null);
    },
    onError: async (err) => {
      const message = apiErrorMessage(err, "Could not update the matter.");
      const isStaleWrite = isApiErrorShape(err) && err.status === 409;
      setMatterEditConcurrencyError(isStaleWrite ? message : null);
      if (isStaleWrite) {
        await queryClient.invalidateQueries({
          queryKey: ["matters", params.id, "workspace"],
        });
        await queryClient.invalidateQueries({ queryKey: ["matters"] });
      }
      toast.error(message);
    },
  });

  if (!data) return null;

  const activeTasks = data.tasks
    .filter((task) => !["completed", "cancelled"].includes(task.status))
    .slice(0, 5);
  const upcomingHearings = data.hearings
    .filter((h) => h.status !== "completed" && h.status !== "cancelled")
    .filter((h) => h.hearing_on || h.scheduled_for || h.listing_date)
    .slice(0, 4);
  const latestOrder = data.court_orders[0];
  const recentActivity = data.activity.slice(0, 6);
  const recentNotes = data.notes.slice(0, 3);

  function beginMatterEdit(matter: Matter) {
    // Freeze both the comparison record and OCC token for the lifetime of the
    // editor. A background query refetch must not silently adopt a newer token
    // while retaining the user's older draft.
    setMatterEditBase({ ...matter });
    setMatterDraft(draftFromMatter(matter));
    setIsEditingMatter(true);
    setMatterEditConcurrencyError(null);
  }

  function updateMatterDraft(patch: Partial<MatterEditDraft>) {
    setMatterDraft((current) => (current ? { ...current, ...patch } : current));
  }

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      {/* PG-004 follow-up (2026-05-01) — single highest-priority
          item demanding attention on this matter, derived from the
          /api/me/today feed. The card auto-hides when nothing is
          queued so it doesn't leave dead space. */}
      <div className="lg:col-span-3">
        <NextActionCard matterId={data.matter.id} />
      </div>

      <Card className="lg:col-span-2">
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Matter summary</CardTitle>
            <CardDescription>
              The brief a partner should get in 30 seconds before a status call.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {canArchiveMatter ? (
              <MatterLifecycleDialog
                matter={data.matter as Matter}
                onChanged={async () => {
                  setIsEditingMatter(false);
                  setMatterDraft(null);
                  setMatterEditBase(null);
                  await queryClient.invalidateQueries({
                    queryKey: ["matters", params.id, "workspace"],
                  });
                  await queryClient.invalidateQueries({ queryKey: ["matters"] });
                }}
              />
            ) : null}
            {canEditMatter && data.matter.status !== "disposed" ? (
              <Button
                type="button"
                variant={isEditingMatter ? "ghost" : "outline"}
                size="sm"
                onClick={() => {
                  if (isEditingMatter) {
                    setIsEditingMatter(false);
                    setMatterDraft(null);
                    setMatterEditBase(null);
                    setMatterEditConcurrencyError(null);
                  } else {
                    beginMatterEdit(data.matter as Matter);
                  }
                }}
                data-testid="matter-edit-open"
              >
                {isEditingMatter ? (
                  <X className="h-4 w-4" aria-hidden />
                ) : (
                  <Pencil className="h-4 w-4" aria-hidden />
                )}
                {isEditingMatter ? "Cancel" : "Edit matter"}
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          {isEditingMatter && matterDraft && matterEditBase ? (
            <form
              className="grid gap-3 md:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault();
                const input = buildMatterUpdateInput(
                  params.id,
                  matterEditBase,
                  matterDraft,
                );
                if (!hasMatterChanges(input)) {
                  setIsEditingMatter(false);
                  setMatterDraft(null);
                  setMatterEditBase(null);
                  toast.success("No matter changes to save.");
                  return;
                }
                matterMutation.mutate(input);
              }}
              data-testid="matter-edit-form"
            >
              {matterEditConcurrencyError ? (
                <div
                  className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900 md:col-span-2"
                  role="alert"
                  data-testid="matter-edit-stale-write"
                >
                  <p className="font-medium">This matter changed in another session.</p>
                  <p className="mt-1 text-xs leading-5">
                    {matterEditConcurrencyError} Your stale values were not applied. Cancel and
                    reopen the editor to use the latest record.
                  </p>
                </div>
              ) : null}
              <div className="md:col-span-2">
                <Label htmlFor="matter-edit-title">Title</Label>
                <Input
                  id="matter-edit-title"
                  className="mt-1.5"
                  value={matterDraft.title}
                  onChange={(event) => updateMatterDraft({ title: event.target.value })}
                  data-testid="matter-edit-title"
                  required
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-code">Matter code</Label>
                <Input
                  id="matter-edit-code"
                  className="mt-1.5"
                  value={matterDraft.matterCode}
                  onChange={(event) => updateMatterDraft({ matterCode: event.target.value })}
                  data-testid="matter-edit-code"
                  required
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-status">Status</Label>
                <select
                  id="matter-edit-status"
                  className="mt-1.5 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={matterDraft.status}
                  onChange={(event) =>
                    updateMatterDraft({
                      status: event.target.value as MatterEditDraft["status"],
                    })
                  }
                  data-testid="matter-edit-status"
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="matter-edit-practice-area">Practice area</Label>
                <Input
                  id="matter-edit-practice-area"
                  className="mt-1.5"
                  value={matterDraft.practiceArea}
                  onChange={(event) =>
                    updateMatterDraft({ practiceArea: event.target.value })
                  }
                  data-testid="matter-edit-practice-area"
                  required
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-forum-level">Forum level</Label>
                <select
                  id="matter-edit-forum-level"
                  className="mt-1.5 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={matterDraft.forumLevel}
                  onChange={(event) => updateMatterDraft({ forumLevel: event.target.value })}
                  data-testid="matter-edit-forum-level"
                >
                  {FORUM_LEVEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="matter-edit-client">Client name</Label>
                <Input
                  id="matter-edit-client"
                  className="mt-1.5"
                  value={matterDraft.clientName}
                  onChange={(event) => updateMatterDraft({ clientName: event.target.value })}
                  data-testid="matter-edit-client"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-opposing">Opposing party</Label>
                <Input
                  id="matter-edit-opposing"
                  className="mt-1.5"
                  value={matterDraft.opposingParty}
                  onChange={(event) =>
                    updateMatterDraft({ opposingParty: event.target.value })
                  }
                  data-testid="matter-edit-opposing"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-case-number">Case number</Label>
                <Input
                  id="matter-edit-case-number"
                  className="mt-1.5"
                  value={matterDraft.caseNumber}
                  onChange={(event) => updateMatterDraft({ caseNumber: event.target.value })}
                  data-testid="matter-edit-case-number"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-cnr-number">CNR number</Label>
                <Input
                  id="matter-edit-cnr-number"
                  className="mt-1.5"
                  value={matterDraft.cnrNumber}
                  onChange={(event) => updateMatterDraft({ cnrNumber: event.target.value })}
                  data-testid="matter-edit-cnr-number"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-court">Court / forum name</Label>
                <Input
                  id="matter-edit-court"
                  className="mt-1.5"
                  value={matterDraft.courtName}
                  onChange={(event) => updateMatterDraft({ courtName: event.target.value })}
                  data-testid="matter-edit-court"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-court-forum-number">Court / forum number</Label>
                <Input
                  id="matter-edit-court-forum-number"
                  className="mt-1.5"
                  value={matterDraft.courtForumNumber}
                  maxLength={120}
                  onChange={(event) =>
                    updateMatterDraft({ courtForumNumber: event.target.value })
                  }
                  data-testid="matter-edit-court-forum-number"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-judge">Judge / bench</Label>
                <Input
                  id="matter-edit-judge"
                  className="mt-1.5"
                  value={matterDraft.judgeName}
                  onChange={(event) => updateMatterDraft({ judgeName: event.target.value })}
                  data-testid="matter-edit-judge"
                />
              </div>
              <div>
                <Label htmlFor="matter-edit-next-hearing">Next hearing</Label>
                <Input
                  id="matter-edit-next-hearing"
                  className="mt-1.5"
                  type="date"
                  value={matterDraft.nextHearingOn}
                  onChange={(event) =>
                    updateMatterDraft({ nextHearingOn: event.target.value })
                  }
                  data-testid="matter-edit-next-hearing"
                />
              </div>
              <div className="md:col-span-2">
                <Label htmlFor="matter-edit-description">Summary</Label>
                <Textarea
                  id="matter-edit-description"
                  className="mt-1.5 min-h-28"
                  value={matterDraft.description}
                  onChange={(event) =>
                    updateMatterDraft({ description: event.target.value })
                  }
                  data-testid="matter-edit-description"
                />
              </div>
              <div className="flex justify-end gap-2 md:col-span-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setIsEditingMatter(false);
                    setMatterDraft(null);
                    setMatterEditConcurrencyError(null);
                  }}
                  data-testid="matter-edit-cancel"
                >
                  <X className="h-4 w-4" aria-hidden />
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={matterMutation.isPending}
                  data-testid="matter-edit-save"
                >
                  {matterMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Save className="h-4 w-4" aria-hidden />
                  )}
                  Save
                </Button>
              </div>
            </form>
          ) : (
            <div className="space-y-5">
              {data.matter.description ? (
                <p className="text-prose-wide whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]">
                  {data.matter.description}
                </p>
              ) : (
                <EmptyState
                  icon={ClipboardList}
                  title="No summary yet"
                  description={
                    canEditMatter
                      ? "Use Edit matter to add the summary and correct matter details."
                      : "Matter details will appear here when the team adds a summary."
                  }
                />
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <MatterDetail label="Matter code" value={data.matter.matter_code} />
                <MatterDetail label="Client" value={data.matter.client_name} />
                <MatterDetail label="Opposing party" value={data.matter.opposing_party} />
                <MatterDetail label="Practice area" value={data.matter.practice_area} />
                <MatterDetail label="Case number" value={data.matter.case_number} />
                <MatterDetail label="CNR number" value={data.matter.cnr_number} />
                <MatterDetail label="Court / forum" value={data.matter.court_name} />
                <MatterDetail
                  label="Court / forum number"
                  value={data.matter.court_forum_number}
                />
                <MatterDetail label="Judge / bench" value={data.matter.judge_name} />
                <MatterDetail
                  label="Next hearing"
                  value={formatDate(data.matter.next_hearing_on)}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <ConflictCheckCard
        matterId={data.matter.id}
        matterLifecycleVersion={data.matter.lifecycle_version}
        opposingParty={data.matter.opposing_party}
      />

      <MatterForumCard matter={data.matter} />

      <CounselRecommendationsCard matterId={data.matter.id} />

      <BenchStrategyPanel matterId={data.matter.id} />

      {/* BUG-011 (Hari 2026-04-22 reopen): hide the "Last court order"
          card on matters with no order yet, mirroring the Open tasks
          treatment. The empty state with "Go to court sync" CTA reads
          as a broken promise on a fresh matter — court sync only
          works for adapter-backed courts (Delhi, Bombay, Karnataka,
          Madras) and only after a court_name is set, which most
          fresh matters don't have. When an order exists we render the
          card; otherwise we keep the overview lean. */}
      {latestOrder ? (
        <Card>
          <CardHeader>
            <CardTitle>Last court order</CardTitle>
            <CardDescription>Most recent imported or attached order.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-1.5">
              <div className="text-xs font-medium uppercase tracking-wider text-[var(--color-mute-2)]">
                {formatDate(latestOrder.order_date)}
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                {latestOrder.title ?? "Order"}
              </h3>
              {latestOrder.summary ? (
                <p className="line-clamp-4 text-sm text-[var(--color-mute)]">
                  {latestOrder.summary}
                </p>
              ) : null}
              <OrderBadges order={latestOrder} />
              {latestOrder.source ? (
                <span className="mt-1 inline-flex w-fit items-center rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-mute)]">
                  {latestOrder.source}
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* BUG-011: Open tasks card only renders when there ARE tasks —
          there's no task-creation UI on the overview today, so an
          always-visible empty card reads as a broken promise. */}
      {activeTasks.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Open tasks</CardTitle>
            <CardDescription>Across this matter.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-3">
              {activeTasks.map((task) => (
                <li
                  key={task.id}
                  className="flex flex-col gap-1 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {task.title}
                    </span>
                    <StatusBadge status={task.status} />
                  </div>
                  <div className="flex items-center justify-between text-xs text-[var(--color-mute)]">
                    <span>{task.owner_name ?? "Unassigned"}</span>
                    <span>{task.due_on ? formatDate(task.due_on) : "No due date"}</span>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {/* Upcoming hearings: when there are some, show the next four.
          When empty, show a dedicated empty-state card with a "+ Add
          hearing" CTA — BUG-019/025 durable closure (workflow-as-fix,
          not UX-as-fix). The empty-state card is bounded to this row
          and renders ONLY here, so populated matters stay clean per
          BUG-011's invariant. */}
      {upcomingHearings.length > 0 ? (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Upcoming hearings</CardTitle>
              <CardDescription>Next four on the calendar.</CardDescription>
            </div>
            {data.matter.status !== "disposed" ? (
              <ScheduleHearingDialog matterId={params.id} />
            ) : null}
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-3">
              {upcomingHearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-center justify-between rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {h.hearing_type ?? "Hearing"}
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      {formatDate(h.hearing_on ?? h.scheduled_for ?? h.listing_date, true)}
                    </span>
                  </div>
                  <StatusBadge status={h.status ?? "pending"} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : (
        <Card data-testid="matter-overview-no-hearings">
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Upcoming hearings</CardTitle>
              <CardDescription>
                No hearings scheduled yet — add one to populate the calendar
                and unlock the hearing-pack workflow.
              </CardDescription>
            </div>
            {data.matter.status !== "disposed" ? (
              <ScheduleHearingDialog
                matterId={params.id}
                triggerLabel="Add hearing"
              />
            ) : null}
          </CardHeader>
        </Card>
      )}

      <Card className="lg:col-span-3">
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>
              Every state change on this matter. Audit on by default.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {recentActivity.length === 0 ? (
            <EmptyState
              icon={MessageSquareText}
              title="No activity yet"
              description="As you update this matter, structured events appear here."
            />
          ) : (
            <ol className="relative flex flex-col gap-4 border-l border-[var(--color-line)] pl-5">
              {recentActivity.map((event) => (
                <li key={event.id} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[22px] top-1.5 h-2 w-2 rounded-full bg-[var(--color-brand-500)]"
                  />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-sm font-semibold text-[var(--color-ink)]">
                      {event.title}
                    </span>
                    <span className="text-xs text-[var(--color-mute-2)]">
                      {formatDate(event.created_at, true)}
                    </span>
                  </div>
                  {event.detail ? (
                    <p className="mt-0.5 text-sm text-[var(--color-mute)]">{event.detail}</p>
                  ) : null}
                  <p className="mt-0.5 text-xs text-[var(--color-mute-2)]">
                    {event.actor_name ?? "system"} · {event.event_type}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {recentNotes.length > 0 ? (
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Recent notes</CardTitle>
            <CardDescription>Your team's private thinking on this matter.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-4">
              {recentNotes.map((note) => (
                <li
                  key={note.id}
                  className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-sm text-[var(--color-ink-2)]"
                >
                  <div className="mb-1 flex items-center justify-between text-xs text-[var(--color-mute)]">
                    <span>{note.author_name ?? "Unknown"}</span>
                    <span>{formatDate(note.created_at, true)}</span>
                  </div>
                  <p className="whitespace-pre-line leading-relaxed">{note.body}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
