"use client";

import { ExternalLink, Flag, Loader2, ShieldAlert } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { API_BASE_URL, apiErrorMessage } from "@/lib/api/config";
import {
  reportSourceLink,
  type SourceIssueType,
  type SourceOriginSurface,
  type SourceTargetType,
} from "@/lib/api/source-actions";

export type SourceActionState =
  | "available"
  | "missing"
  | "unverified"
  | "blocked"
  | "quarantined";

export type SourceActionContract = {
  state: SourceActionState;
  label: string;
  open_url: string | null;
  source_reference: string | null;
  reason: string | null;
  opens_new_tab: boolean;
  target_type?: SourceTargetType | null;
  target_id?: string | null;
};

export function SourceAction({
  action,
  compact = false,
  originSurface = "other",
}: {
  action: SourceActionContract | null | undefined;
  compact?: boolean;
  originSurface?: SourceOriginSurface;
}) {
  const [reportOpen, setReportOpen] = useState(false);
  const target =
    action?.target_type && action.target_id
      ? { type: action.target_type, id: action.target_id }
      : null;

  if (action?.state === "available" && action.open_url) {
    const sourceUrl = action.open_url.startsWith("/api/")
      ? `${API_BASE_URL}${action.open_url}`
      : action.open_url;
    const href = target
      ? appendOriginSurface(sourceUrl, originSurface)
      : sourceUrl;
    return (
      <>
        <span className="flex w-full min-w-0 flex-wrap items-center gap-1 sm:w-auto">
          <a
            className="min-w-0 flex-1 sm:flex-none"
            href={href}
            target={action.opens_new_tab ? "_blank" : undefined}
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
            data-testid="source-action-open"
          >
            <Button className="w-full sm:w-auto" size="sm" variant="outline" type="button">
              <ExternalLink className="h-4 w-4" aria-hidden />
              {compact ? "Source" : action.label}
            </Button>
          </a>
          {target ? (
            <Button
              className="min-w-0 flex-1 sm:flex-none"
              size="sm"
              variant="ghost"
              type="button"
              onClick={() => setReportOpen(true)}
              data-testid="source-action-report"
            >
              <Flag className="h-4 w-4" aria-hidden />
              Report
            </Button>
          ) : null}
        </span>
        {target ? (
          <SourceReportDialog
            open={reportOpen}
            onOpenChange={setReportOpen}
            targetType={target.type}
            targetId={target.id}
            originSurface={originSurface}
          />
        ) : null}
      </>
    );
  }

  const state = action?.state ?? "missing";
  const reason = action?.reason ?? "No verified source is available.";
  return (
    <>
      <span className="flex w-full min-w-0 flex-wrap items-start gap-1 sm:w-auto">
        <span
          className="inline-flex min-w-0 max-w-64 flex-1 items-start gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900 sm:flex-none"
          role="status"
          data-testid={`source-action-${state}`}
          title={reason}
        >
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{compact ? state.replaceAll("_", " ") : reason}</span>
        </span>
        {target ? (
          <Button
            className="min-w-0 flex-1 sm:flex-none"
            size="sm"
            variant="ghost"
            type="button"
            onClick={() => setReportOpen(true)}
            data-testid="source-action-report"
          >
            <Flag className="h-4 w-4" aria-hidden />
            Report
          </Button>
        ) : null}
      </span>
      {target ? (
        <SourceReportDialog
          open={reportOpen}
          onOpenChange={setReportOpen}
          targetType={target.type}
          targetId={target.id}
          originSurface={originSurface}
        />
      ) : null}
    </>
  );
}

function appendOriginSurface(
  sourceUrl: string,
  originSurface: SourceOriginSurface,
): string {
  const separator = sourceUrl.includes("?") ? "&" : "?";
  return `${sourceUrl}${separator}origin=${encodeURIComponent(originSurface)}`;
}

function SourceReportDialog({
  open,
  onOpenChange,
  targetType,
  targetId,
  originSurface,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetType: SourceTargetType;
  targetId: string;
  originSurface: SourceOriginSurface;
}) {
  const fieldId = useId();
  const [issueType, setIssueType] = useState<SourceIssueType>("broken");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(): Promise<void> {
    setSubmitting(true);
    try {
      await reportSourceLink({
        targetType,
        targetId,
        originSurface,
        issueType,
        description,
      });
      toast.success("Source report queued for review.");
      setDescription("");
      setIssueType("broken");
      onOpenChange(false);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not report this source."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Report source issue</DialogTitle>
          <DialogDescription>
            Tell the source-health queue what went wrong. The citation remains
            visible while the link is reviewed.
          </DialogDescription>
        </DialogHeader>
        <div className="grid min-w-0 gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor={`${fieldId}-issue`}>Issue</Label>
            <select
              id={`${fieldId}-issue`}
              className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
              value={issueType}
              onChange={(event) =>
                setIssueType(event.target.value as SourceIssueType)
              }
            >
              <option value="broken">Link is broken</option>
              <option value="wrong_document">Wrong document</option>
              <option value="access_denied">Access denied</option>
              <option value="stale">Source appears stale</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${fieldId}-description`}>
              Details (optional)
            </Label>
            <Textarea
              id={`${fieldId}-description`}
              value={description}
              maxLength={1000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Describe what you expected and what happened."
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Queuing...
              </>
            ) : (
              "Queue report"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
