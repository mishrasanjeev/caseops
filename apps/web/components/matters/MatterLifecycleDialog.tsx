"use client";

import { useMutation } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { transitionMatterStatus } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";

type LifecycleStatus = "intake" | "active" | "on_hold" | "disposed";

export function MatterLifecycleDialog({
  matter,
  onChanged,
  compact = false,
}: {
  matter: Pick<Matter, "id" | "matter_code" | "status" | "updated_at">;
  onChanged: (matter: Matter) => void | Promise<void>;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const isReopen = matter.status === "disposed";
  const expectedStatus = matter.status as LifecycleStatus;
  const targetStatus = isReopen ? "intake" : "disposed";
  const actionLabel = isReopen ? "Reopen matter" : "Dispose matter";
  const normalizedReason = reason.trim().replace(/\s+/g, " ");
  const reasonIsValid =
    normalizedReason.length >= 10 && normalizedReason.split(" ").length >= 2;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!matter.updated_at) {
        throw new Error(
          "This matter is missing its concurrency timestamp. Refresh before changing its lifecycle.",
        );
      }
      return transitionMatterStatus({
        matterId: matter.id,
        to_status: targetStatus,
        expected_from_status: expectedStatus,
        expected_updated_at: matter.updated_at,
        reason: normalizedReason,
      });
    },
    onSuccess: async (updatedMatter) => {
      await onChanged(updatedMatter);
      toast.success(
        isReopen
          ? "Matter reopened in Intake. Conflict review remains optional before activation."
          : "Matter disposed and removed from active operations.",
      );
      setReason("");
      setErrorMessage(null);
      setOpen(false);
    },
    onError: (error) => {
      const message = apiErrorMessage(
        error,
        `Could not ${isReopen ? "reopen" : "dispose"} the matter.`,
      );
      setErrorMessage(message);
      toast.error(message);
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen && !mutation.isPending) {
          setReason("");
          setErrorMessage(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!matter.updated_at}
          title={
            matter.updated_at
              ? undefined
              : "Refresh this matter before changing its lifecycle."
          }
          data-testid={isReopen ? "matter-reopen-trigger" : "matter-dispose-trigger"}
        >
          {isReopen ? (
            <ArchiveRestore className="h-4 w-4" aria-hidden />
          ) : (
            <Archive className="h-4 w-4" aria-hidden />
          )}
          {compact ? (isReopen ? "Reopen" : "Dispose") : actionLabel}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{actionLabel}</DialogTitle>
          <DialogDescription>
            {isReopen
              ? "Reopening returns this matter to Intake. Run a fresh conflict check if your firm's process calls for one; it does not block Active status."
              : "Disposal is a controlled lifecycle action. The matter is removed from active work views and later background updates cannot reopen it."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor={`matter-lifecycle-reason-${matter.id}`}>
            Reason (required)
          </Label>
          <Textarea
            id={`matter-lifecycle-reason-${matter.id}`}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              setErrorMessage(null);
            }}
            placeholder={
              isReopen
                ? "Explain why this disposed matter must be reopened."
                : "Record the order, outcome, or other basis for disposal."
            }
            className="min-h-24"
            data-testid="matter-lifecycle-reason"
          />
          <p className="text-xs text-[var(--color-mute)]">
            Enter at least two words and 10 characters. The reason is retained in the
            audit trail.
          </p>
          {errorMessage ? (
            <p
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
              role="alert"
              data-testid="matter-lifecycle-error"
            >
              {errorMessage}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!reasonIsValid || mutation.isPending || !matter.updated_at}
            data-testid="matter-lifecycle-confirm"
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : isReopen ? (
              <ArchiveRestore className="h-4 w-4" aria-hidden />
            ) : (
              <Archive className="h-4 w-4" aria-hidden />
            )}
            {isReopen ? "Reopen in Intake" : "Confirm disposal"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
