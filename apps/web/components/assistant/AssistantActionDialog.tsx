"use client";

import { AlertTriangle, CheckCircle2, ExternalLink, LoaderCircle, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  confirmAssistantAction,
  previewAssistantAction,
  type AssistantActionInput,
  type AssistantActionPreview,
  type AssistantMatterField,
  type AssistantProposedAction,
} from "@/lib/api/workspace-assistant";

const MATTER_FIELDS: Array<{ value: AssistantMatterField; label: string }> = [
  { value: "title", label: "Title" },
  { value: "description", label: "Description" },
  { value: "matter_type", label: "Matter type" },
  { value: "client_name", label: "Client name" },
  { value: "opposing_party", label: "Opposing party" },
  { value: "opposing_counsel", label: "Opposing counsel" },
  { value: "practice_area", label: "Practice area" },
  { value: "court_name", label: "Court name" },
  { value: "judge_name", label: "Judge name" },
];

type Props = {
  sessionId: string;
  sessionVersion: number;
  turnId: string;
  action: AssistantProposedAction;
  onClose: () => void;
  onConfirmed: (preview: AssistantActionPreview) => void;
};

function initialInput(action: AssistantProposedAction): AssistantActionInput {
  if (action.action_type === "field_update") {
    return { field_name: "description", field_value: "" };
  }
  if (action.action_type === "draft") {
    return { title: action.instruction ?? "", draft_type: "memo" };
  }
  return { title: action.instruction ?? "", priority: "medium" };
}

export function AssistantActionDialog({
  sessionId,
  sessionVersion,
  turnId,
  action,
  onClose,
  onConfirmed,
}: Props) {
  const [input, setInput] = useState<AssistantActionInput>(() => initialInput(action));
  const [preview, setPreview] = useState<AssistantActionPreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function review() {
    setBusy("preview");
    setError(null);
    try {
      const next = await previewAssistantAction(
        sessionId,
        sessionVersion,
        turnId,
        action.proposal_id,
        input,
      );
      setPreview(next);
    } catch (caught) {
      setError(apiErrorMessage(caught, "The action could not be previewed."));
    } finally {
      setBusy(null);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy("confirm");
    setError(null);
    try {
      const confirmed = await confirmAssistantAction(
        sessionId,
        preview.preview_id,
        sessionVersion,
        preview.preview_token,
      );
      setPreview(confirmed);
      onConfirmed(confirmed);
    } catch (caught) {
      setError(apiErrorMessage(caught, "The action was not confirmed."));
    } finally {
      setBusy(null);
    }
  }

  const actionName = action.action_type === "field_update" ? "field update" : action.action_type;
  const confirmed = preview?.status === "confirmed";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl rounded-md" data-testid="assistant-action-dialog">
        <DialogHeader>
          <DialogTitle>Review {actionName}</DialogTitle>
          <DialogDescription>{action.target_label ?? "Selected workspace record"}</DialogDescription>
        </DialogHeader>

        {!preview ? (
          <div className="space-y-4">
            {action.action_type === "task" ? (
              <>
                <LabeledInput
                  label="Task title"
                  value={input.title ?? ""}
                  onChange={(value) => setInput((current) => ({ ...current, title: value }))}
                />
                <label className="block text-sm font-medium text-[var(--color-ink-2)]">
                  Description
                  <Textarea
                    className="mt-1 min-h-24"
                    value={input.description ?? ""}
                    onChange={(event) =>
                      setInput((current) => ({ ...current, description: event.target.value }))
                    }
                  />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <LabeledInput
                    label="Due date"
                    type="date"
                    value={input.due_on ?? ""}
                    onChange={(value) => setInput((current) => ({ ...current, due_on: value }))}
                  />
                  <label className="block text-sm font-medium text-[var(--color-ink-2)]">
                    Priority
                    <Select
                      value={input.priority ?? "medium"}
                      onValueChange={(value: "low" | "medium" | "high" | "urgent") =>
                        setInput((current) => ({ ...current, priority: value }))
                      }
                    >
                      <SelectTrigger className="mt-1" aria-label="Priority">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(["low", "medium", "high", "urgent"] as const).map((value) => (
                          <SelectItem key={value} value={value}>
                            {value.charAt(0).toUpperCase() + value.slice(1)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                </div>
              </>
            ) : null}

            {action.action_type === "draft" ? (
              <>
                <LabeledInput
                  label="Draft title"
                  value={input.title ?? ""}
                  onChange={(value) => setInput((current) => ({ ...current, title: value }))}
                />
                {action.target_type === "matter" ? (
                  <label className="block text-sm font-medium text-[var(--color-ink-2)]">
                    Draft type
                    <Select
                      value={input.draft_type ?? "memo"}
                      onValueChange={(value: "brief" | "notice" | "reply" | "memo" | "other") =>
                        setInput((current) => ({ ...current, draft_type: value }))
                      }
                    >
                      <SelectTrigger className="mt-1" aria-label="Draft type">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(["brief", "notice", "reply", "memo", "other"] as const).map((value) => (
                          <SelectItem key={value} value={value}>
                            {value.charAt(0).toUpperCase() + value.slice(1)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                ) : null}
              </>
            ) : null}

            {action.action_type === "field_update" ? (
              <>
                <label className="block text-sm font-medium text-[var(--color-ink-2)]">
                  Matter field
                  <Select
                    value={input.field_name ?? "description"}
                    onValueChange={(value: AssistantMatterField) =>
                      setInput((current) => ({ ...current, field_name: value }))
                    }
                  >
                    <SelectTrigger className="mt-1" aria-label="Matter field">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MATTER_FIELDS.map((field) => (
                        <SelectItem key={field.value} value={field.value}>
                          {field.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="block text-sm font-medium text-[var(--color-ink-2)]">
                  Proposed value
                  <Textarea
                    className="mt-1 min-h-24"
                    value={input.field_value ?? ""}
                    onChange={(event) =>
                      setInput((current) => ({ ...current, field_value: event.target.value }))
                    }
                  />
                </label>
              </>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-start gap-3 border-y border-[var(--color-line)] py-4">
              {confirmed ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-success-600)]" />
              ) : (
                <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-brand-700)]" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[var(--color-ink)]">
                  {confirmed ? "Action confirmed" : preview.summary}
                </p>
                <p className="mt-1 text-xs text-[var(--color-mute)]">{preview.target_label}</p>
              </div>
            </div>
            <dl className="divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
              {preview.changes.map((change) => (
                <div key={change.field} className="grid min-w-0 gap-1 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
                  <dt className="text-xs font-semibold text-[var(--color-mute)]">{change.field}</dt>
                  <dd className="min-w-0 break-words text-sm text-[var(--color-ink-2)]">
                    {change.before ? <span className="line-through">{change.before}</span> : null}
                    {change.before ? " → " : ""}
                    {change.after || "Not set"}
                  </dd>
                </div>
              ))}
            </dl>
            <ul className="space-y-2" aria-label="Action warnings">
              {preview.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-xs text-[var(--color-mute)]">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {error ? (
          <p className="text-sm text-[var(--color-danger-700)]" role="alert">
            {error}
          </p>
        ) : null}

        <DialogFooter>
          {confirmed ? (
            <>
              <Button
                type="button"
                variant="outline"
                aria-label="Close action review"
                onClick={onClose}
              >
                Close
              </Button>
              {preview.result_href ? (
                <Button href={preview.result_href}>
                  Open result <ExternalLink className="h-4 w-4" aria-hidden />
                </Button>
              ) : null}
            </>
          ) : preview ? (
            <>
              <Button type="button" variant="outline" disabled={busy !== null} onClick={() => setPreview(null)}>
                Edit details
              </Button>
              <Button type="button" disabled={busy !== null} onClick={() => void confirm()}>
                {busy === "confirm" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                Confirm action
              </Button>
            </>
          ) : (
            <>
              <Button type="button" variant="outline" disabled={busy !== null} onClick={onClose}>
                Cancel
              </Button>
              <Button type="button" disabled={busy !== null} onClick={() => void review()}>
                {busy === "preview" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                Review changes
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LabeledInput({
  label,
  value,
  type = "text",
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm font-medium text-[var(--color-ink-2)]">
      {label}
      <Input
        className="mt-1"
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
