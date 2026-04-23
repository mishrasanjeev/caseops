"use client";

// Phase B / J12 / M11 slice 1 — matter Communications tab.
//
// Slice 1 supports MANUAL logging only: "I called the client at 3pm"
// or "client emailed me back". The lawyer types into a small form
// and we store it. Slice 2 will add a "Compose & send" path on top
// of the same row (template picker → SendGrid → delivery webhook).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  Loader2,
  Mail,
  MessageSquare,
  Phone,
  Plus,
  StickyNote,
  Users,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createMatterCommunication,
  fetchMatterCommunications,
} from "@/lib/api/endpoints";
import type {
  CommunicationChannel,
  CommunicationRecord,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { cn } from "@/lib/cn";

const CHANNEL_ICON: Record<CommunicationChannel, typeof Mail> = {
  email: Mail,
  sms: MessageSquare,
  phone: Phone,
  meeting: Users,
  note: StickyNote,
};

const CHANNEL_LABEL: Record<CommunicationChannel, string> = {
  email: "Email",
  sms: "SMS",
  phone: "Phone",
  meeting: "Meeting",
  note: "Note",
};

function formatLocal(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MatterCommunicationsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const canWrite = useCapability("communications:write");

  const [composing, setComposing] = useState(false);

  const query = useQuery({
    queryKey: ["matters", matterId, "communications"],
    queryFn: () => fetchMatterCommunications(matterId),
  });

  const createMutation = useMutation({
    mutationFn: (input: {
      channel: CommunicationChannel;
      body: string;
      subject: string | null;
      recipient_name: string | null;
      direction: "outbound" | "inbound";
    }) =>
      createMatterCommunication({
        matterId,
        channel: input.channel,
        body: input.body,
        subject: input.subject,
        recipient_name: input.recipient_name,
        direction: input.direction,
      }),
    onSuccess: async () => {
      toast.success("Logged.");
      setComposing(false);
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "communications"],
      });
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not log communication."));
    },
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
            Communications
          </h1>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            Log calls, meetings, emails, and notes against this matter.
          </p>
        </div>
        {canWrite ? (
          <Button
            type="button"
            onClick={() => setComposing((c) => !c)}
            data-testid="comm-log-toggle"
          >
            <Plus className="h-4 w-4" aria-hidden />
            {composing ? "Cancel" : "Log communication"}
          </Button>
        ) : null}
      </header>

      {composing ? (
        <LogForm
          submitting={createMutation.isPending}
          onSubmit={(input) => createMutation.mutate(input)}
        />
      ) : null}

      {query.isError ? (
        <QueryErrorState
          title="Could not load communications"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : query.data && query.data.communications.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {query.data.communications.map((row) => (
            <CommunicationRow key={row.id} row={row} />
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={ArrowLeft}
          title="No communications yet"
          description={
            canWrite
              ? "Click 'Log communication' above to record a call, meeting, email, or note."
              : "No one has logged anything against this matter yet."
          }
        />
      )}
    </div>
  );
}

function CommunicationRow({ row }: { row: CommunicationRecord }) {
  const Icon = CHANNEL_ICON[row.channel];
  const accent =
    row.direction === "outbound"
      ? "bg-[var(--color-accent)]"
      : "bg-[var(--color-info-500)]";
  return (
    <li
      className="rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`communication-${row.id}`}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white",
            accent,
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-sm font-semibold text-[var(--color-ink)]">
              {row.subject ?? `${CHANNEL_LABEL[row.channel]} (${row.direction})`}
            </span>
            <span className="text-xs text-[var(--color-mute)]">
              <CalendarClock className="mr-1 inline h-3 w-3" aria-hidden />
              {formatLocal(row.occurred_at)}
            </span>
            {row.recipient_name ? (
              <span className="text-xs text-[var(--color-mute)]">
                with {row.recipient_name}
              </span>
            ) : null}
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">
            {row.body}
          </p>
        </div>
      </div>
    </li>
  );
}

function LogForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean;
  onSubmit: (input: {
    channel: CommunicationChannel;
    direction: "outbound" | "inbound";
    body: string;
    subject: string | null;
    recipient_name: string | null;
  }) => void;
}) {
  const [channel, setChannel] = useState<CommunicationChannel>("phone");
  const [direction, setDirection] = useState<"outbound" | "inbound">("outbound");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [recipient, setRecipient] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          Log a communication
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!body.trim()) return;
            onSubmit({
              channel,
              direction,
              body: body.trim(),
              subject: subject.trim() || null,
              recipient_name: recipient.trim() || null,
            });
          }}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Channel
              <select
                value={channel}
                onChange={(e) =>
                  setChannel(e.target.value as CommunicationChannel)
                }
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-channel"
              >
                {(Object.keys(CHANNEL_LABEL) as CommunicationChannel[]).map(
                  (c) => (
                    <option key={c} value={c}>
                      {CHANNEL_LABEL[c]}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Direction
              <select
                value={direction}
                onChange={(e) =>
                  setDirection(e.target.value as "outbound" | "inbound")
                }
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-direction"
              >
                <option value="outbound">Outbound (we sent / called)</option>
                <option value="inbound">Inbound (they sent / called)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Recipient (optional)
              <input
                type="text"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="e.g. Hari Gupta"
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-recipient"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
            Subject (optional)
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="One-line summary"
              className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
              data-testid="comm-subject"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
            Body
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="What was discussed / said / agreed?"
              rows={4}
              required
              className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
              data-testid="comm-body"
            />
          </label>
          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={submitting || !body.trim()}
              data-testid="comm-submit"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Logging…
                </>
              ) : (
                "Log"
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
