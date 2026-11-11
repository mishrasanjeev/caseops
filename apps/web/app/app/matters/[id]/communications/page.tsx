"use client";

// J12 / M11: communication history, manual logs and guarded email composition.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  Loader2,
  Mail,
  MessageSquare,
  Paperclip,
  Phone,
  Plus,
  Send,
  ShieldCheck,
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
  fetchMatterCommunicationTimeline,
} from "@/lib/api/endpoints";
import type {
  CommunicationChannel,
  CommunicationTimelineFilter,
  CommunicationTimelineItem,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { cn } from "@/lib/cn";
import { deliverMatterEmail, listMatterEmailTemplates } from "@/lib/api/communications-email";
import { ComposeEmailForm, type EmailSubmission } from "./ComposeEmailForm";

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

const TIMELINE_FILTERS: Array<{
  key: CommunicationTimelineFilter;
  label: string;
}> = [
  { key: "all", label: "All" },
  { key: "email", label: "Email" },
  { key: "platform", label: "Platform" },
  { key: "notes", label: "Notes" },
  { key: "attachments", label: "Attachments" },
  { key: "internal", label: "Internal" },
];

const VISIBILITY_LABEL: Record<CommunicationTimelineItem["visibility"], string> = {
  internal: "Internal",
  firm_only: "Firm only",
  client_visible: "Client visible",
  outside_counsel_visible: "Outside counsel",
  imported_email: "Imported email",
};

const ITEM_TYPE_LABEL: Record<CommunicationTimelineItem["item_type"], string> = {
  platform_message: "Platform",
  imported_email: "Imported email",
  email_thread: "Email thread",
  attachment: "Attachment",
  internal_note: "Internal note",
  client_visible_note: "Client note",
  outside_counsel_visible_update: "Outside counsel",
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
  const [sending, setSending] = useState(false);
  const [timelineFilter, setTimelineFilter] =
    useState<CommunicationTimelineFilter>("all");

  const query = useQuery({
    queryKey: ["matters", matterId, "communications", "timeline", timelineFilter],
    queryFn: () =>
      fetchMatterCommunicationTimeline({
        matterId,
        filter: timelineFilter,
      }),
  });

  const templatesQuery = useQuery({
    queryKey: ["matters", matterId, "communications", "templates"],
    queryFn: () => listMatterEmailTemplates(matterId),
    enabled: sending,  // only load when the Compose dialog opens
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

  const sendMutation = useMutation({
    mutationFn: (input: EmailSubmission) => deliverMatterEmail(matterId, input),
    onSuccess: async () => {
      toast.success("Email sent.");
      setSending(false);
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "communications"],
      });
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not send email.")),
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
            Communications
          </h1>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            Review platform messages, imported emails, notes, and attachment
            references in chronological order.
          </p>
        </div>
        {canWrite ? (
          <div className="flex min-w-0 w-full flex-wrap items-center gap-2 sm:w-auto">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setComposing((c) => !c);
                setSending(false);
              }}
              data-testid="comm-log-toggle"
            >
              <Plus className="h-4 w-4" aria-hidden />
              {composing ? "Cancel" : "Log communication"}
            </Button>
            <Button
              type="button"
              onClick={() => {
                setSending((c) => !c);
                setComposing(false);
              }}
              data-testid="comm-send-toggle"
            >
              <Send className="h-4 w-4" aria-hidden />
              {sending ? "Cancel" : "Compose & send"}
            </Button>
          </div>
        ) : null}
      </header>

      {composing ? (
        <LogForm
          submitting={createMutation.isPending}
          onSubmit={(input) => createMutation.mutate(input)}
        />
      ) : null}

      {sending ? (
        <ComposeEmailForm
          matterId={matterId}
          templates={templatesQuery.data?.templates ?? []}
          loading={templatesQuery.isPending}
          templateError={templatesQuery.isError ? apiErrorMessage(templatesQuery.error, "Could not load templates.") : null}
          submitting={sendMutation.isPending}
          onSubmit={(input) => sendMutation.mutate(input)}
        />
      ) : null}

      <TimelineFilterBar
        selected={timelineFilter}
        onSelect={setTimelineFilter}
      />

      {query.isError ? (
        <QueryErrorState
          title="Could not load communication timeline"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : query.data && query.data.items.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {query.data.items.map((row) => (
            <CommunicationTimelineRow key={row.id} row={row} />
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

function TimelineFilterBar({
  selected,
  onSelect,
}: {
  selected: CommunicationTimelineFilter;
  onSelect: (filter: CommunicationTimelineFilter) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Timeline filters">
      {TIMELINE_FILTERS.map((filter) => (
        <button
          key={filter.key}
          type="button"
          onClick={() => onSelect(filter.key)}
          className={cn(
            "rounded-md border px-3 py-1.5 text-xs font-medium transition",
            selected === filter.key
              ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
              : "border-[var(--color-line)] bg-white text-[var(--color-ink-2)] hover:border-[var(--color-accent)]",
          )}
          data-testid={`comm-timeline-filter-${filter.key}`}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}

function CommunicationTimelineRow({ row }: { row: CommunicationTimelineItem }) {
  const Icon =
    row.item_type === "attachment"
      ? Paperclip
      : row.item_type === "internal_note"
        ? ShieldCheck
        : row.channel
          ? CHANNEL_ICON[row.channel]
          : MessageSquare;
  const accent =
    row.direction === "outbound"
      ? "bg-[var(--color-accent)]"
      : row.item_type === "internal_note"
        ? "bg-[var(--color-warning-500)]"
        : row.item_type === "attachment"
          ? "bg-[var(--color-success-500)]"
      : "bg-[var(--color-info-500)]";
  return (
    <li
      className="rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`communication-timeline-${row.id}`}
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
              {row.title}
            </span>
            <span className="text-xs text-[var(--color-mute)]">
              <CalendarClock className="mr-1 inline h-3 w-3" aria-hidden />
              {formatLocal(row.occurred_at)}
            </span>
            {row.actor_label ? (
              <span className="text-xs text-[var(--color-mute)]">
                {row.actor_label}
              </span>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded bg-[var(--color-line-1)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-ink-2)]">
              {ITEM_TYPE_LABEL[row.item_type]}
            </span>
            <span className="rounded bg-[var(--color-line-1)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-ink-2)]">
              {VISIBILITY_LABEL[row.visibility]}
            </span>
            {row.thread_key ? (
              <span className="rounded bg-[var(--color-line-1)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-mute)]">
                Threaded
              </span>
            ) : null}
          </div>
          {row.preview ? (
            <p className="mt-2 whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">
              {row.preview}
            </p>
          ) : null}
          {row.attachment ? (
            <div className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 px-3 py-2 text-xs text-[var(--color-ink-2)]">
              <Paperclip className="mr-1 inline h-3.5 w-3.5" aria-hidden />
              <span className="font-medium">{row.attachment.filename}</span>
              {row.attachment.size_bytes !== null ? (
                <span className="text-[var(--color-mute)]">
                  {" "}
                  ({formatBytes(row.attachment.size_bytes)})
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
