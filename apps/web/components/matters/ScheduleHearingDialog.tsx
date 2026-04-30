"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Loader2 } from "lucide-react";
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
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import { createMatterHearing } from "@/lib/api/endpoints";

/**
 * ScheduleHearingDialog — manual hearing creation for matters without
 * a third-party court-sync feed. Originally landed on the dedicated
 * Hearings tab (BUG-004 fix, 2026-04-20). Lifted here on 2026-04-30
 * so the matter cockpit empty-state can reuse it (BUG-019/025 durable
 * closure: workflow-as-fix, not UX-as-fix).
 *
 * The component is self-contained — it owns the dialog open/close
 * state, the form fields, and the mutation. Callers control:
 * - ``matterId`` — required, target matter.
 * - ``triggerLabel`` — defaults to "Schedule hearing".
 * - ``triggerSize`` / ``triggerVariant`` — defaults match the prior
 *   inline button on the Hearings tab.
 *
 * On success, invalidates the matter workspace query so calendars,
 * upcoming-hearings cards, and the hearings tab all repaint.
 */
export function ScheduleHearingDialog({
  matterId,
  triggerLabel = "Schedule hearing",
  triggerSize = "sm",
  triggerVariant = "secondary",
}: {
  matterId: string;
  triggerLabel?: string;
  triggerSize?: "sm" | "md" | "lg";
  triggerVariant?: "primary" | "secondary" | "ghost" | "outline";
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [hearingOn, setHearingOn] = useState("");
  const [forumName, setForumName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [judgeName, setJudgeName] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      createMatterHearing({
        matterId,
        hearing_on: hearingOn,
        forum_name: forumName,
        purpose,
        judge_name: judgeName.trim() || null,
      }),
    onSuccess: async () => {
      setOpen(false);
      setHearingOn("");
      setForumName("");
      setPurpose("");
      setJudgeName("");
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Hearing scheduled.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not schedule hearing."));
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size={triggerSize}
          variant={triggerVariant}
          data-testid="schedule-hearing-open"
        >
          <CalendarPlus className="h-4 w-4" aria-hidden /> {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Schedule a hearing</DialogTitle>
          <DialogDescription>
            Add a listing manually. Dates imported by court sync appear
            here alongside manual entries — pick whichever fits the
            matter.
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
            <Label htmlFor="hearing_on">Hearing date</Label>
            <Input
              id="hearing_on"
              type="date"
              required
              value={hearingOn}
              onChange={(e) => setHearingOn(e.target.value)}
              data-testid="schedule-hearing-date"
            />
          </div>
          <div>
            <Label htmlFor="forum_name">Forum / bench</Label>
            <Input
              id="forum_name"
              type="text"
              required
              minLength={2}
              maxLength={255}
              placeholder="e.g. Delhi HC, Bench: Hon'ble Mr. Justice X"
              value={forumName}
              onChange={(e) => setForumName(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="purpose">Purpose / stage</Label>
            <Input
              id="purpose"
              type="text"
              required
              minLength={2}
              maxLength={255}
              placeholder="e.g. Arguments on bail, first listing, evidence"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="judge_name">Judge name (optional)</Label>
            <Input
              id="judge_name"
              type="text"
              maxLength={255}
              placeholder="Leave blank if the bench is not yet assigned"
              value={judgeName}
              onChange={(e) => setJudgeName(e.target.value)}
            />
          </div>
          <p
            className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-mute)]"
            role="note"
          >
            <strong className="font-medium text-[var(--color-ink-2)]">Reminders:</strong>{" "}
            the hearing will appear on this page and on the matter overview.
            Email reminders (T-24h and T-1h) are scheduled the moment the
            hearing is saved — they'll be delivered once the workspace's
            email provider is configured.
          </p>
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
              disabled={mutation.isPending || !hearingOn || !forumName || !purpose}
              data-testid="schedule-hearing-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                "Schedule"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
