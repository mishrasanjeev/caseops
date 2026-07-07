"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert, ShieldQuestion, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import {
  type ConflictCheckRecord,
  listConflictChecks,
  resolveConflictCheck,
  runConflictCheck,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

/**
 * ConflictCheckCard — pre-engagement conflict gate (PG-001) on the
 * matter cockpit. Displays the latest conflict check (if any), shows
 * candidate matches, and lets a fee-earner run a fresh scan or a
 * partner resolve a pending one (cleared / conflicted / waived).
 *
 * Intake gating is enforced by the API: matter status promotion is
 * blocked unless the latest check is cleared or waived.
 */
export function ConflictCheckCard({
  matterId,
}: {
  matterId: string;
}): React.JSX.Element | null {
  const canRun = useCapability("conflicts:run");
  const canResolve = useCapability("conflicts:resolve");
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["matters", matterId, "conflict-checks"],
    queryFn: () => listConflictChecks(matterId),
  });

  if (!canRun) return null;

  const latest: ConflictCheckRecord | undefined = data?.checks?.[0];
  const refreshAll = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["matters", matterId, "conflict-checks"],
    });
  };

  const tone = latest?.status ?? "untested";

  return (
    <Card data-testid="matter-conflict-card" tabIndex={-1}>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Conflict check</CardTitle>
          <CardDescription>
            Pre-engagement scan against this workspace's clients, matters,
            and contacts. Run before opening the file.
          </CardDescription>
        </div>
        <RunCheckDialog matterId={matterId} onSuccess={refreshAll} />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div
            className="flex items-center gap-2 text-sm text-[var(--color-mute)]"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </div>
        ) : !latest ? (
          <p className="text-sm text-[var(--color-mute)]">
            No conflict check has been run yet.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <StatusBadge status={tone} />
            <p className="text-xs text-[var(--color-mute)]">
              Last scan: {new Date(latest.ran_at).toLocaleString()}
            </p>
            {latest.candidates.length === 0 ? (
              <p className="text-sm text-[var(--color-ink-2)]">
                No overlapping clients, matters, or contacts found.
              </p>
            ) : (
              <CandidatesList candidates={latest.candidates} />
            )}
            {latest.status === "pending" && canResolve ? (
              <ResolveBar checkId={latest.id} onResolved={refreshAll} />
            ) : null}
            {latest.status === "pending" && !canResolve ? (
              <p
                className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                data-testid="conflict-review-restricted"
              >
                A partner or admin must clear, mark conflicted, or waive this
                result before the matter can move to Active.
              </p>
            ) : null}
            {latest.resolution_note ? (
              <p
                className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-mute)]"
                role="note"
              >
                <strong className="font-medium text-[var(--color-ink-2)]">
                  Partner note:
                </strong>{" "}
                {latest.resolution_note}
              </p>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({
  status,
}: {
  status: "pending" | "cleared" | "conflicted" | "waived" | "untested";
}): React.JSX.Element {
  const map = {
    pending: {
      icon: ShieldQuestion,
      label: "Pending review",
      tone: "bg-amber-50 text-amber-900 border-amber-200",
    },
    cleared: {
      icon: CheckCircle2,
      label: "Cleared",
      tone: "bg-emerald-50 text-emerald-900 border-emerald-200",
    },
    conflicted: {
      icon: ShieldAlert,
      label: "Conflicted — do not proceed",
      tone: "bg-rose-50 text-rose-900 border-rose-200",
    },
    waived: {
      icon: ShieldAlert,
      label: "Waived (partner-approved)",
      tone: "bg-sky-50 text-sky-900 border-sky-200",
    },
    untested: {
      icon: ShieldQuestion,
      label: "Untested",
      tone: "bg-slate-50 text-slate-700 border-slate-200",
    },
  } as const;
  const { icon: Icon, label, tone } = map[status];
  return (
    <span
      data-testid={`conflict-status-${status}`}
      className={`inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${tone}`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
    </span>
  );
}

function CandidatesList({
  candidates,
}: {
  candidates: ConflictCheckRecord["candidates"];
}): React.JSX.Element {
  return (
    <ul className="flex flex-col gap-2">
      {candidates.map((c) => (
        <li
          key={`${c.kind}:${c.id}`}
          className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-[var(--color-ink)]">
              {c.kind} · {c.name}
            </span>
            <span className="text-[var(--color-mute-2)]">
              similarity {Math.round(c.similarity * 100)}%
            </span>
          </div>
          <p className="mt-0.5 text-[var(--color-mute)]">{c.overlap_reason}</p>
        </li>
      ))}
    </ul>
  );
}

function RunCheckDialog({
  matterId,
  onSuccess,
}: {
  matterId: string;
  onSuccess: () => Promise<void>;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [opposing, setOpposing] = useState("");
  const [related, setRelated] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      runConflictCheck({
        matterId,
        opposing_party_name: opposing.trim(),
        related_party_names: related
          .split(/\n|,/)
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
      }),
    onSuccess: async () => {
      setOpen(false);
      setOpposing("");
      setRelated("");
      await onSuccess();
      toast.success("Conflict scan completed.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not run conflict check."));
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          data-testid="conflict-run-open"
        >
          Run check
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Run conflict check</DialogTitle>
          <DialogDescription>
            Scan existing clients, matters, and contacts for overlap with
            the parties below. Run this before opening the engagement.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <div>
            <Label htmlFor="opposing-party">Opposing party</Label>
            <Input
              id="opposing-party"
              type="text"
              required
              minLength={1}
              maxLength={255}
              value={opposing}
              onChange={(e) => setOpposing(e.target.value)}
              placeholder='e.g. "Acme Pvt Ltd"'
              data-testid="conflict-run-opposing"
            />
          </div>
          <div>
            <Label htmlFor="related-parties">
              Related parties (optional, one per line)
            </Label>
            <textarea
              id="related-parties"
              className="block w-full rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm text-[var(--color-ink)] outline-none focus-visible:border-[var(--color-brand-500)]"
              rows={3}
              maxLength={2000}
              value={related}
              onChange={(e) => setRelated(e.target.value)}
              placeholder={"Witness Co\nParent Holdings"}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending || !opposing.trim()}
              data-testid="conflict-run-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
                  Running…
                </>
              ) : (
                "Run scan"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResolveBar({
  checkId,
  onResolved,
}: {
  checkId: string;
  onResolved: () => Promise<void>;
}): React.JSX.Element {
  const [waiverNote, setWaiverNote] = useState("");
  const [showWaiver, setShowWaiver] = useState(false);

  const resolve = useMutation({
    mutationFn: (
      input: { status: "cleared" | "conflicted" | "waived"; resolution_note?: string },
    ) => resolveConflictCheck({ checkId, ...input }),
    onSuccess: async () => {
      setWaiverNote("");
      setShowWaiver(false);
      await onResolved();
      toast.success("Conflict check resolved.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not resolve check."));
    },
  });

  if (showWaiver) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs">
        <Label htmlFor="waiver-note">Waiver basis (required)</Label>
        <textarea
          id="waiver-note"
          className="block w-full rounded-md border border-amber-300 bg-white px-2 py-1.5 text-xs"
          rows={3}
          maxLength={4000}
          value={waiverNote}
          onChange={(e) => setWaiverNote(e.target.value)}
          placeholder="e.g. Client granted express written waiver dated 2026-04-30."
        />
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => setShowWaiver(false)}
            disabled={resolve.isPending}
          >
            Back
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={resolve.isPending || !waiverNote.trim()}
            onClick={() =>
              resolve.mutate({ status: "waived", resolution_note: waiverNote.trim() })
            }
          >
            Save waiver
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={resolve.isPending}
        onClick={() => resolve.mutate({ status: "cleared" })}
        data-testid="conflict-resolve-clear"
      >
        Clear (no real conflict)
      </Button>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={resolve.isPending}
        onClick={() =>
          resolve.mutate({
            status: "conflicted",
            resolution_note: "Confirmed conflict; matter cannot proceed.",
          })
        }
        data-testid="conflict-resolve-conflict"
      >
        Mark conflicted
      </Button>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={resolve.isPending}
        onClick={() => setShowWaiver(true)}
        data-testid="conflict-resolve-waive"
      >
        Waive…
      </Button>
    </div>
  );
}
