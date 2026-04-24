"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  FileBadge,
  MessageCircle,
  Send,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchPortalMatter,
  fetchPortalMatterCommunications,
  fetchPortalMatterHearings,
  postPortalMatterReply,
  submitPortalMatterKyc,
  type PortalKycDocument,
} from "@/lib/api/portal";

export default function PortalMatterDetailPage() {
  const params = useParams<{ id: string }>();
  const matterId = params?.id ?? "";
  const queryClient = useQueryClient();

  const matterQuery = useQuery({
    queryKey: ["portal", "matter", matterId],
    queryFn: () => fetchPortalMatter(matterId),
    enabled: matterId.length > 0,
    retry: 0,
  });

  if (matterQuery.isError) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
        <QueryErrorState
          error={matterQuery.error}
          title="We could not load this matter"
        />
        <Link href="/portal">
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Back to your matters
          </Button>
        </Link>
      </main>
    );
  }

  const matter = matterQuery.data;
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 px-6 py-10">
      <PageHeader
        eyebrow={matter?.matter_code ?? "Matter"}
        title={matter?.title ?? "Matter"}
        description={
          matter
            ? [matter.court_name, matter.practice_area].filter(Boolean).join(" · ")
            : "Loading…"
        }
        actions={
          <Link href="/portal">
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Back
            </Button>
          </Link>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="comms">
            <MessageCircle className="mr-1 h-3.5 w-3.5" /> Comms
          </TabsTrigger>
          <TabsTrigger value="hearings">
            <CalendarClock className="mr-1 h-3.5 w-3.5" /> Hearings
          </TabsTrigger>
          <TabsTrigger value="kyc">
            <FileBadge className="mr-1 h-3.5 w-3.5" /> KYC
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewCard matter={matter} />
        </TabsContent>

        <TabsContent value="comms">
          <CommsCard
            matterId={matterId}
            onPosted={() =>
              queryClient.invalidateQueries({
                queryKey: ["portal", "matter", matterId, "comms"],
              })
            }
          />
        </TabsContent>

        <TabsContent value="hearings">
          <HearingsCard matterId={matterId} />
        </TabsContent>

        <TabsContent value="kyc">
          <KycCard matterId={matterId} />
        </TabsContent>
      </Tabs>
    </main>
  );
}

function OverviewCard({
  matter,
}: {
  matter:
    | {
        title: string;
        matter_code: string | null;
        status: string;
        practice_area: string | null;
        forum_level: string | null;
        court_name: string | null;
        next_hearing_on: string | null;
      }
    | undefined;
}) {
  if (!matter) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Status</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm md:grid-cols-2">
        <Row label="Status" value={<Badge tone="brand">{matter.status}</Badge>} />
        <Row label="Practice area" value={matter.practice_area ?? "—"} />
        <Row label="Court" value={matter.court_name ?? "—"} />
        <Row label="Forum level" value={matter.forum_level ?? "—"} />
        <Row
          label="Next hearing"
          value={
            matter.next_hearing_on
              ? new Date(matter.next_hearing_on).toLocaleDateString()
              : "Not scheduled"
          }
        />
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--color-line)] px-3 py-2">
      <span className="text-xs uppercase tracking-wide text-[var(--color-mute)]">
        {label}
      </span>
      <span className="text-sm text-[var(--color-ink)]">{value}</span>
    </div>
  );
}

function CommsCard({
  matterId,
  onPosted,
}: {
  matterId: string;
  onPosted: () => void;
}) {
  const [body, setBody] = useState("");
  const commsQuery = useQuery({
    queryKey: ["portal", "matter", matterId, "comms"],
    queryFn: () => fetchPortalMatterCommunications(matterId),
    enabled: matterId.length > 0,
  });
  const replyMutation = useMutation({
    mutationFn: () => postPortalMatterReply(matterId, body),
    onSuccess: () => {
      setBody("");
      onPosted();
      toast.success("Reply sent.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not send your reply."));
    },
  });
  const rows = commsQuery.data?.communications ?? [];

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Reply to the firm</CardTitle>
          <CardDescription>
            Lands directly in your firm's matter inbox. They get notified
            and can reply in this thread.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (body.trim().length === 0) return;
              replyMutation.mutate();
            }}
          >
            <Textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Write your message…"
              rows={3}
              data-testid="portal-reply-body"
            />
            <Button
              type="submit"
              disabled={body.trim().length === 0 || replyMutation.isPending}
              data-testid="portal-reply-submit"
            >
              <Send className="mr-1 h-3.5 w-3.5" />
              {replyMutation.isPending ? "Sending…" : "Send reply"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Conversation</CardTitle>
        </CardHeader>
        <CardContent>
          {commsQuery.isError ? (
            <QueryErrorState
              error={commsQuery.error}
              title="Could not load the conversation"
              onRetry={() => commsQuery.refetch()}
            />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={MessageCircle}
              title="No messages yet"
              description="When the firm posts an update or you send a reply it will appear here."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {rows.map((c) => (
                <li
                  key={c.id}
                  className="flex flex-col gap-1 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-comm-${c.id}`}
                >
                  <div className="flex items-center justify-between gap-2 text-xs text-[var(--color-mute)]">
                    <span>
                      {c.posted_by_portal_user
                        ? "You"
                        : c.direction === "outbound"
                          ? "From the firm"
                          : "Inbound"}
                    </span>
                    <span>{new Date(c.occurred_at).toLocaleString()}</span>
                  </div>
                  {c.subject ? (
                    <div className="text-sm font-medium text-[var(--color-ink)]">
                      {c.subject}
                    </div>
                  ) : null}
                  <div className="whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">
                    {c.body}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function HearingsCard({ matterId }: { matterId: string }) {
  const hearingsQuery = useQuery({
    queryKey: ["portal", "matter", matterId, "hearings"],
    queryFn: () => fetchPortalMatterHearings(matterId),
    enabled: matterId.length > 0,
  });
  const rows = hearingsQuery.data?.hearings ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Upcoming + past hearings</CardTitle>
        <CardDescription>
          Read-only. The firm sets dates and outcomes; you'll see updates
          here as they happen.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hearingsQuery.isError ? (
          <QueryErrorState
            error={hearingsQuery.error}
            title="Could not load hearings"
            onRetry={() => hearingsQuery.refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title="No hearings scheduled"
            description="When the firm schedules a hearing on your matter it will show up here."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {rows.map((h) => (
              <li
                key={h.id}
                className="rounded-md border border-[var(--color-line)] px-3 py-2"
                data-testid={`portal-hearing-${h.id}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-[var(--color-ink)]">
                    {new Date(h.hearing_on).toLocaleDateString()} · {h.purpose}
                  </span>
                  <Badge tone="neutral">{h.status}</Badge>
                </div>
                <div className="text-xs text-[var(--color-mute)]">
                  {[h.forum_name, h.judge_name].filter(Boolean).join(" · ")}
                </div>
                {h.outcome_note ? (
                  <div className="mt-1 text-xs text-[var(--color-ink-2)]">
                    Outcome: {h.outcome_note}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function KycCard({ matterId }: { matterId: string }) {
  const [docs, setDocs] = useState<PortalKycDocument[]>([
    { name: "PAN", note: "" },
    { name: "Aadhaar", note: "" },
  ]);
  const [submittedAt, setSubmittedAt] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => submitPortalMatterKyc(matterId, docs),
    onSuccess: (result) => {
      setSubmittedAt(result.submitted_at);
      toast.success("KYC submitted. The firm will review.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not submit KYC."));
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Submit KYC</CardTitle>
        <CardDescription>
          Tell the firm which identity documents you have on file. They'll
          verify on their side and you'll see the status update here.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {docs.map((d, i) => (
          <div key={i} className="flex flex-col gap-2 md:flex-row">
            <div className="md:w-1/3">
              <Label htmlFor={`portal-kyc-doc-${i}-name`}>Document</Label>
              <Input
                id={`portal-kyc-doc-${i}-name`}
                value={d.name}
                onChange={(e) =>
                  setDocs((prev) =>
                    prev.map((p, idx) =>
                      idx === i ? { ...p, name: e.target.value } : p,
                    ),
                  )
                }
                data-testid={`portal-kyc-name-${i}`}
              />
            </div>
            <div className="md:flex-1">
              <Label htmlFor={`portal-kyc-doc-${i}-note`}>Note (optional)</Label>
              <Input
                id={`portal-kyc-doc-${i}-note`}
                value={d.note ?? ""}
                onChange={(e) =>
                  setDocs((prev) =>
                    prev.map((p, idx) =>
                      idx === i ? { ...p, note: e.target.value } : p,
                    ),
                  )
                }
                data-testid={`portal-kyc-note-${i}`}
              />
            </div>
          </div>
        ))}
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setDocs((p) => [...p, { name: "", note: "" }])}
            disabled={docs.length >= 20}
          >
            Add another document
          </Button>
          <Button
            type="button"
            disabled={
              mutation.isPending || docs.every((d) => d.name.trim() === "")
            }
            onClick={() => mutation.mutate()}
            data-testid="portal-kyc-submit"
          >
            <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
            {mutation.isPending ? "Submitting…" : "Submit KYC"}
          </Button>
        </div>
        {submittedAt ? (
          <p className="text-xs text-[var(--color-mute)]">
            Submitted {new Date(submittedAt).toLocaleString()}. The firm
            will reach out if anything is missing.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
