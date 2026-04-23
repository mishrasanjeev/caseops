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
  Send,
  StickyNote,
  Users,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
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
  listEmailTemplates,
  renderEmailTemplate,
  sendMatterEmail,
} from "@/lib/api/endpoints";
import type {
  CommunicationChannel,
  CommunicationRecord,
  EmailTemplateRecord,
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
  const [sending, setSending] = useState(false);

  const query = useQuery({
    queryKey: ["matters", matterId, "communications"],
    queryFn: () => fetchMatterCommunications(matterId),
  });

  const templatesQuery = useQuery({
    queryKey: ["matters", matterId, "communications", "templates"],
    queryFn: () => listEmailTemplates(),
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
    mutationFn: (input: {
      templateId: string;
      recipient_email: string;
      recipient_name: string | null;
      variables: Record<string, string>;
    }) =>
      sendMatterEmail({
        matterId,
        templateId: input.templateId,
        recipient_email: input.recipient_email,
        recipient_name: input.recipient_name,
        variables: input.variables,
      }),
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
            Log calls, meetings, emails, and notes against this matter.
          </p>
        </div>
        {canWrite ? (
          <div className="flex items-center gap-2">
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
        <ComposeSendForm
          templates={templatesQuery.data?.templates ?? []}
          loadingTemplates={templatesQuery.isPending}
          submitting={sendMutation.isPending}
          onSubmit={(input) => sendMutation.mutate(input)}
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

// Phase B M11 slice 2 — Compose & send (template picker + variables).
const PLACEHOLDER_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;

function detectVarsFromTemplate(t: EmailTemplateRecord): string[] {
  const seen = new Set<string>();
  for (const text of [t.subject_template, t.body_template]) {
    let m: RegExpExecArray | null;
    while ((m = PLACEHOLDER_RE.exec(text)) !== null) {
      seen.add(m[1]);
    }
  }
  return [...seen];
}

function ComposeSendForm({
  templates,
  loadingTemplates,
  submitting,
  onSubmit,
}: {
  templates: EmailTemplateRecord[];
  loadingTemplates: boolean;
  submitting: boolean;
  onSubmit: (input: {
    templateId: string;
    recipient_email: string;
    recipient_name: string | null;
    variables: Record<string, string>;
  }) => void;
}) {
  const [templateId, setTemplateId] = useState<string>("");
  const [recipientEmail, setRecipientEmail] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [previewSubject, setPreviewSubject] = useState<string | null>(null);
  const [previewBody, setPreviewBody] = useState<string | null>(null);

  const selected = useMemo(
    () => templates.find((t) => t.id === templateId) ?? null,
    [templates, templateId],
  );
  const requiredVarNames = useMemo(
    () => (selected ? detectVarsFromTemplate(selected) : []),
    [selected],
  );

  const onPreview = async () => {
    if (!selected) return;
    try {
      const r = await renderEmailTemplate({
        templateId: selected.id,
        variables,
      });
      setPreviewSubject(r.subject);
      setPreviewBody(r.body);
    } catch (err) {
      toast.error(apiErrorMessage(err, "Could not render preview."));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          Compose & send
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!templateId || !recipientEmail.trim()) return;
            onSubmit({
              templateId,
              recipient_email: recipientEmail.trim(),
              recipient_name: recipientName.trim() || null,
              variables,
            });
          }}
        >
          {loadingTemplates ? (
            <Skeleton className="h-10 w-full" />
          ) : templates.length === 0 ? (
            <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3 text-xs">
              No active templates. Ask a workspace admin to create one
              under{" "}
              <a
                href="/app/admin/email-templates"
                className="underline"
              >
                /app/admin/email-templates
              </a>
              .
            </div>
          ) : (
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Template
              <select
                value={templateId}
                onChange={(e) => {
                  setTemplateId(e.target.value);
                  setVariables({});
                  setPreviewSubject(null);
                  setPreviewBody(null);
                }}
                required
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-send-template"
              >
                <option value="">— Pick a template —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Recipient email
              <input
                type="email"
                value={recipientEmail}
                onChange={(e) => setRecipientEmail(e.target.value)}
                required
                placeholder="client@example.com"
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-send-recipient-email"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Recipient name (optional)
              <input
                type="text"
                value={recipientName}
                onChange={(e) => setRecipientName(e.target.value)}
                placeholder="Hari Gupta"
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="comm-send-recipient-name"
              />
            </label>
          </div>

          {requiredVarNames.length > 0 ? (
            <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3">
              <div className="mb-2 text-xs font-medium text-[var(--color-ink)]">
                Variables
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {requiredVarNames.map((name) => (
                  <label
                    key={name}
                    className="flex flex-col gap-1 text-xs"
                  >
                    <span className="font-mono text-[var(--color-mute)]">
                      {`{{${name}}}`}
                    </span>
                    <input
                      type="text"
                      value={variables[name] ?? ""}
                      onChange={(e) =>
                        setVariables((v) => ({ ...v, [name]: e.target.value }))
                      }
                      className="rounded-md border border-[var(--color-line)] px-2 py-1 text-sm"
                      data-testid={`comm-send-var-${name}`}
                    />
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          {previewSubject !== null ? (
            <div className="rounded-md border border-[var(--color-line)] bg-white p-3">
              <div className="text-xs font-medium text-[var(--color-mute)]">
                Preview
              </div>
              <div className="mt-1 text-sm font-semibold">{previewSubject}</div>
              <div className="mt-2 whitespace-pre-wrap text-xs text-[var(--color-ink-2)]">
                {previewBody}
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!templateId}
              onClick={onPreview}
              data-testid="comm-send-preview"
            >
              Preview
            </Button>
            <Button
              type="submit"
              disabled={
                submitting || !templateId || !recipientEmail.trim()
              }
              data-testid="comm-send-submit"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Sending…
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" aria-hidden /> Send
                </>
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
