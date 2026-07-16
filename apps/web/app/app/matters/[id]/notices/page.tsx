"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Filter,
  Inbox,
  Loader2,
  Paperclip,
  Search,
  Send,
  Upload,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
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
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  updateMatterAttachmentMetadata,
  uploadMatterAttachment,
} from "@/lib/api/endpoints";
import {
  downloadNoticeFile,
  listNotices,
  type NoticeRecord,
} from "@/lib/api/notices";
import type { WorkspaceAttachment } from "@/lib/api/workspace-types";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate, todayLocalDateInput } from "@/lib/dates";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

type NoticeDirection = "received" | "sent";
type RelatedDocumentRole = "reply" | "supporting";

type NoticeUploadDraft = {
  receivedOn: string;
  noticeType: string;
  mode: string;
  subject: string;
  authority: string;
  receivedFrom: string;
  summary: string;
  response: string;
  remarks: string;
  status: string;
  department: string;
  internalSpoc: string;
  internalRemarks: string;
  amount: string;
  replyDueOn: string;
  replyRequired: boolean;
  replySent: boolean;
  replySentOn: string;
  sentOn: string;
  counselEngaged: string;
  disputeAmount: string;
  recoveredAmount: string;
  currency: string;
};

type NoticeFilters = {
  query: string;
  status: string;
  replyStatus: string;
  dueFrom: string;
  dueTo: string;
  authority: string;
  matter: string;
  department: string;
};

type RelatedUploadTarget = {
  parentId: string;
  parentSubject: string;
  direction: NoticeDirection;
  role: RelatedDocumentRole;
};

const EMPTY_NOTICE_UPLOAD_DRAFT: NoticeUploadDraft = {
  receivedOn: "",
  noticeType: "",
  mode: "",
  subject: "",
  authority: "",
  receivedFrom: "",
  summary: "",
  response: "",
  remarks: "",
  status: "Open",
  department: "",
  internalSpoc: "",
  internalRemarks: "",
  amount: "",
  replyDueOn: "",
  replyRequired: true,
  replySent: false,
  replySentOn: "",
  sentOn: "",
  counselEngaged: "",
  disputeAmount: "",
  recoveredAmount: "",
  currency: "INR",
};

const EMPTY_FILTERS: NoticeFilters = {
  query: "",
  status: "",
  replyStatus: "",
  dueFrom: "",
  dueTo: "",
  authority: "",
  matter: "",
  department: "",
};

const selectClass =
  "flex h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1";

function displayName(doc: WorkspaceAttachment): string {
  return doc.original_filename ?? doc.filename ?? "Notice document";
}

function formatDate(value: string | null | undefined): string {
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function todayIso(): string {
  return todayLocalDateInput();
}

function humanSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let size = bytes;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function amountToMinor(value: string): number | null {
  const cleaned = value.trim().replace(/,/g, "");
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * 100);
}

function formatMoney(
  minor: number | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (minor === null || minor === undefined) return null;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency || "INR",
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

function noticeDirection(notice: WorkspaceAttachment): NoticeDirection {
  return notice.notice_direction === "sent" ? "sent" : "received";
}

function noticeDocumentRole(notice: WorkspaceAttachment): string {
  return notice.notice_document_role ?? "notice";
}

function noticeDate(notice: WorkspaceAttachment): string | null | undefined {
  return noticeDirection(notice) === "sent"
    ? notice.notice_sent_on ?? notice.document_date ?? notice.created_at
    : notice.notice_received_on ?? notice.document_date ?? notice.created_at;
}

function replyStatus(notice: WorkspaceAttachment): string | null {
  if (noticeDirection(notice) !== "received") return null;
  return notice.notice_reply_status ?? "not_required";
}

function replyStatusLabel(notice: WorkspaceAttachment): string {
  const status = replyStatus(notice);
  if (status === "reply_sent") return "Reply Sent";
  if (status === "reply_overdue") return "Reply Overdue";
  if (status === "reply_due_today") return "Reply Due Today";
  if (status === "reply_due_in_days") {
    return `Reply Due in ${notice.notice_reply_days_remaining ?? "?"} Days`;
  }
  if (status === "reply_pending") return "Reply Pending";
  return "No Reply Required";
}

function replyBadgeTone(notice: WorkspaceAttachment): "neutral" | "brand" | "success" | "warning" {
  const status = replyStatus(notice);
  if (status === "reply_sent") return "success";
  if (status === "reply_due_today" || status === "reply_overdue") return "warning";
  if (status === "reply_due_in_days" || status === "reply_pending") return "brand";
  return "neutral";
}

function searchableText(notice: WorkspaceAttachment): string {
  return [
    displayName(notice),
    notice.notice_subject,
    notice.notice_type,
    notice.notice_authority,
    notice.notice_source,
    notice.notice_received_from,
    notice.notice_summary,
    notice.notice_response,
    notice.notice_remarks,
    notice.notice_status,
    notice.notice_department,
    notice.notice_internal_spoc,
    notice.notice_internal_remarks,
    notice.notice_counsel_engaged,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function dateInRange(value: string | null | undefined, from: string, to: string): boolean {
  if (!from && !to) return true;
  if (!value) return false;
  const dateValue = value.slice(0, 10);
  if (from && dateValue < from) return false;
  if (to && dateValue > to) return false;
  return true;
}

function globalNoticeSearchableText(notice: NoticeRecord): string {
  return [
    notice.subject,
    notice.type,
    notice.authority,
    notice.received_from,
    notice.summary,
    notice.response,
    notice.remarks,
    notice.department,
    notice.owner_name,
    notice.filename,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

async function loadAllLinkedGlobalNotices(
  matterId: string,
): Promise<NoticeRecord[]> {
  const notices = new Map<string, NoticeRecord>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;

  do {
    const page = await listNotices({ matter_id: matterId, limit: 100, cursor });
    for (const notice of page.notices) notices.set(notice.id, notice);

    const next = page.next_cursor ?? null;
    if (!next || seenCursors.has(next)) break;
    seenCursors.add(next);
    cursor = next;
  } while (cursor);

  return Array.from(notices.values());
}

export default function MatterNoticesPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const noticeFileInput = useRef<HTMLInputElement | null>(null);
  const relatedFileInput = useRef<HTMLInputElement | null>(null);
  const [activeTab, setActiveTab] = useState<NoticeDirection>("received");
  const [noticeDraft, setNoticeDraft] = useState<NoticeUploadDraft>(
    EMPTY_NOTICE_UPLOAD_DRAFT,
  );
  const [filters, setFilters] = useState<NoticeFilters>(EMPTY_FILTERS);
  const [relatedUploadTarget, setRelatedUploadTarget] =
    useState<RelatedUploadTarget | null>(null);
  const [replySentDates, setReplySentDates] = useState<Record<string, string>>({});
  const [downloadingGlobalId, setDownloadingGlobalId] = useState<string | null>(null);
  const canUpload = useCapability("documents:upload");
  const canManageDocuments = useCapability("documents:manage");
  const { data } = useMatterWorkspace(matterId);
  const linkedGlobalNoticesQuery = useQuery({
    queryKey: ["notices", "matter", matterId],
    queryFn: () => loadAllLinkedGlobalNotices(matterId),
  });

  const linkedGlobalNotices = useMemo(
    () =>
      (linkedGlobalNoticesQuery.data ?? []).filter(
        (notice) => notice.source_kind === "standalone" && !notice.read_only,
      ),
    [linkedGlobalNoticesQuery.data],
  );

  const allNoticeDocuments = useMemo(
    () => (data?.attachments ?? []).filter((attachment) => attachment.document_type === "notice"),
    [data?.attachments],
  );

  const primaryNotices = useMemo(
    () =>
      allNoticeDocuments
        .filter(
          (attachment) =>
            noticeDocumentRole(attachment) === "notice" &&
            !attachment.notice_parent_attachment_id,
        )
        .sort((left, right) => {
          const leftDate = noticeDate(left) ?? "";
          const rightDate = noticeDate(right) ?? "";
          return rightDate.localeCompare(leftDate);
        }),
    [allNoticeDocuments],
  );

  const childDocumentsByParent = useMemo(() => {
    const grouped = new Map<string, WorkspaceAttachment[]>();
    for (const document of allNoticeDocuments) {
      const parentId = document.notice_parent_attachment_id;
      if (!parentId) continue;
      const group = grouped.get(parentId) ?? [];
      group.push(document);
      grouped.set(parentId, group);
    }
    for (const group of grouped.values()) {
      group.sort((left, right) => (right.created_at ?? "").localeCompare(left.created_at ?? ""));
    }
    return grouped;
  }, [allNoticeDocuments]);

  const receivedNotices = primaryNotices.filter(
    (notice) => noticeDirection(notice) === "received",
  );
  const sentNotices = primaryNotices.filter((notice) => noticeDirection(notice) === "sent");
  const receivedGlobalNotices = linkedGlobalNotices.filter(
    (notice) => notice.direction === "received",
  );
  const sentGlobalNotices = linkedGlobalNotices.filter(
    (notice) => notice.direction === "sent",
  );
  const pendingReplies = receivedNotices.filter((notice) =>
    ["reply_pending", "reply_due_in_days"].includes(replyStatus(notice) ?? ""),
  );
  const overdueReplies = receivedNotices.filter(
    (notice) => replyStatus(notice) === "reply_overdue",
  );
  const dueTodayReplies = receivedNotices.filter(
    (notice) => replyStatus(notice) === "reply_due_today",
  );
  const dueThisWeekReplies = receivedNotices.filter((notice) => {
    const days = notice.notice_reply_days_remaining;
    return replyStatus(notice) === "reply_due_in_days" && days !== null && days !== undefined && days <= 7;
  });
  const pendingGlobalReplies = receivedGlobalNotices.filter(
    (notice) => notice.reply_required && !notice.reply_sent,
  );
  const overdueGlobalReplies = pendingGlobalReplies.filter(
    (notice) =>
      Boolean(
        notice.reply_due_on && notice.reply_due_on.slice(0, 10) < todayIso(),
      ),
  );
  const dueTodayGlobalReplies = pendingGlobalReplies.filter(
    (notice) => notice.reply_due_on?.slice(0, 10) === todayIso(),
  );
  const sevenDaysFromNow = new Date();
  sevenDaysFromNow.setDate(sevenDaysFromNow.getDate() + 7);
  const weekEnd = sevenDaysFromNow.toISOString().slice(0, 10);
  const dueThisWeekGlobalReplies = pendingGlobalReplies.filter((notice) => {
    const due = notice.reply_due_on?.slice(0, 10);
    return Boolean(due && due >= todayIso() && due <= weekEnd);
  });

  const visibleNotices = primaryNotices.filter((notice) => {
    if (noticeDirection(notice) !== activeTab) return false;
    if (filters.query && !searchableText(notice).includes(filters.query.toLowerCase())) {
      return false;
    }
    if (filters.status && (notice.notice_status || "Open") !== filters.status) {
      return false;
    }
    if (filters.replyStatus && replyStatus(notice) !== filters.replyStatus) {
      return false;
    }
    if (!dateInRange(notice.notice_reply_due_on, filters.dueFrom, filters.dueTo)) {
      return false;
    }
    if (
      filters.authority &&
      !(notice.notice_authority ?? "").toLowerCase().includes(filters.authority.toLowerCase())
    ) {
      return false;
    }
    if (
      filters.department &&
      !(notice.notice_department ?? "").toLowerCase().includes(filters.department.toLowerCase())
    ) {
      return false;
    }
    if (filters.matter && data?.matter) {
      const matterText = `${data.matter.matter_code} ${data.matter.title}`.toLowerCase();
      if (!matterText.includes(filters.matter.toLowerCase())) return false;
    }
    return true;
  });

  const visibleGlobalNotices = linkedGlobalNotices.filter((notice) => {
    if (notice.direction !== activeTab) return false;
    if (
      filters.query &&
      !globalNoticeSearchableText(notice).includes(filters.query.toLowerCase())
    ) {
      return false;
    }
    if (filters.status && notice.status !== filters.status) return false;
    if (
      filters.replyStatus &&
      (filters.replyStatus === "reply_sent"
        ? !notice.reply_sent
        : filters.replyStatus === "not_required"
          ? notice.reply_required
          : filters.replyStatus === "reply_overdue"
            ? !(
                notice.reply_required &&
                !notice.reply_sent &&
                notice.reply_due_on &&
                notice.reply_due_on.slice(0, 10) < todayIso()
              )
            : !(notice.reply_required && !notice.reply_sent))
    ) {
      return false;
    }
    if (!dateInRange(notice.reply_due_on, filters.dueFrom, filters.dueTo)) return false;
    if (
      filters.authority &&
      !(notice.authority ?? "").toLowerCase().includes(filters.authority.toLowerCase())
    ) return false;
    if (
      filters.department &&
      !(notice.department ?? "").toLowerCase().includes(filters.department.toLowerCase())
    ) return false;
    if (filters.matter && data?.matter) {
      const matterText = `${data.matter.matter_code} ${data.matter.title}`.toLowerCase();
      if (!matterText.includes(filters.matter.toLowerCase())) return false;
    }
    return true;
  });

  const statusOptions = Array.from(
    new Set([
      ...primaryNotices.map((notice) => notice.notice_status || "Open"),
      ...linkedGlobalNotices.map((notice) => notice.status),
    ]),
  ).sort();

  const invalidateWorkspace = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["matters", matterId, "workspace"],
    });
  };

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadMatterAttachment({
        matterId,
        file,
        documentType: "notice",
        lifecycleStage: "initiation",
        documentDate:
          activeTab === "received"
            ? noticeDraft.receivedOn || null
            : noticeDraft.sentOn || null,
        noticeDirection: activeTab,
        noticeDocumentRole: "notice",
        noticeType: noticeDraft.noticeType || null,
        noticeMode: activeTab === "received" ? noticeDraft.mode || null : null,
        noticeSource: activeTab === "received" ? noticeDraft.receivedFrom || null : null,
        noticeSubject: noticeDraft.subject || null,
        noticeReceivedOn: activeTab === "received" ? noticeDraft.receivedOn || null : null,
        noticeResponse:
          activeTab === "received" ? noticeDraft.response || null : null,
        noticeAuthority: noticeDraft.authority || null,
        noticeReceivedFrom:
          activeTab === "received" ? noticeDraft.receivedFrom || null : null,
        noticeSummary: noticeDraft.summary || null,
        noticeRemarks: noticeDraft.remarks || null,
        noticeStatus: noticeDraft.status || null,
        noticeDepartment: noticeDraft.department || null,
        noticeInternalSpoc: noticeDraft.internalSpoc || null,
        noticeInternalRemarks: noticeDraft.internalRemarks || null,
        noticeAmountMinor:
          activeTab === "received" ? amountToMinor(noticeDraft.amount) : null,
        noticeDisputeAmountMinor:
          activeTab === "sent" ? amountToMinor(noticeDraft.disputeAmount) : null,
        noticeRecoveredAmountMinor:
          activeTab === "sent" ? amountToMinor(noticeDraft.recoveredAmount) : null,
        noticeCurrency: noticeDraft.currency || "INR",
        noticeReplyDueOn:
          activeTab === "received" ? noticeDraft.replyDueOn || null : null,
        noticeReplyRequired: activeTab === "received" ? noticeDraft.replyRequired : false,
        noticeReplySent: activeTab === "received" ? noticeDraft.replySent : false,
        noticeReplySentOn:
          activeTab === "received" && noticeDraft.replySent
            ? noticeDraft.replySentOn || todayIso()
            : null,
        noticeSentOn: activeTab === "sent" ? noticeDraft.sentOn || null : null,
        noticeCounselEngaged:
          activeTab === "sent" ? noticeDraft.counselEngaged || null : null,
        sequenceIndex: null,
        linkedCourtOrderId: null,
        hearingId: null,
      }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success(activeTab === "received" ? "Notice received uploaded." : "Notice sent uploaded.");
      setNoticeDraft(EMPTY_NOTICE_UPLOAD_DRAFT);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not upload the notice."));
    },
    onSettled: () => {
      if (noticeFileInput.current) noticeFileInput.current.value = "";
    },
  });

  const relatedUploadMutation = useMutation({
    mutationFn: ({ file, target }: { file: File; target: RelatedUploadTarget }) => {
      const sentOn = target.role === "reply" ? replySentDates[target.parentId] || todayIso() : null;
      return uploadMatterAttachment({
        matterId,
        file,
        documentType: "notice",
        lifecycleStage: "initiation",
        documentDate: sentOn,
        noticeDirection: target.direction,
        noticeDocumentRole: target.role,
        noticeParentAttachmentId: target.parentId,
        noticeSubject:
          target.role === "reply"
            ? `Reply - ${target.parentSubject}`
            : `Supporting - ${target.parentSubject}`,
        noticeReplySentOn: sentOn,
        sequenceIndex: null,
        linkedCourtOrderId: null,
        hearingId: null,
      });
    },
    onSuccess: async (_result, variables) => {
      await invalidateWorkspace();
      toast.success(
        variables.target.role === "reply"
          ? "Reply document uploaded."
          : "Supporting document uploaded.",
      );
      setRelatedUploadTarget(null);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not upload the notice document."));
    },
    onSettled: () => {
      if (relatedFileInput.current) relatedFileInput.current.value = "";
    },
  });

  const markReplySentMutation = useMutation({
    mutationFn: (notice: WorkspaceAttachment) =>
      updateMatterAttachmentMetadata({
        matterId,
        attachmentId: notice.id,
        notice_reply_sent: true,
        notice_reply_sent_on: replySentDates[notice.id] || todayIso(),
      }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Reply status updated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update reply status."));
    },
  });

  const downloadGlobalNotice = async (notice: NoticeRecord) => {
    setDownloadingGlobalId(notice.id);
    try {
      await downloadNoticeFile(
        notice.id,
        notice.filename ?? "notice-document",
      );
    } catch (error) {
      toast.error(
        apiErrorMessage(error, "Could not download the linked notice document."),
      );
    } finally {
      setDownloadingGlobalId(null);
    }
  };

  if (!data) return null;

  const matterLabel = `${data.matter.matter_code} - ${data.matter.title}`;

  return (
    <div className="flex flex-col gap-5" data-testid="matter-notices-page">
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Pending replies</CardTitle>
            <CardDescription>Received notices awaiting response.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold text-[var(--color-ink)]">
              {pendingReplies.length + pendingGlobalReplies.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Overdue replies</CardTitle>
            <CardDescription>Past due with no reply sent.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-3xl font-semibold text-amber-800">
              {overdueReplies.length + overdueGlobalReplies.length}
              {overdueReplies.length + overdueGlobalReplies.length > 0 ? <AlertTriangle className="h-5 w-5" aria-hidden /> : null}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Due today</CardTitle>
            <CardDescription>Reply deadline expires today.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold text-[var(--color-ink)]">
              {dueTodayReplies.length + dueTodayGlobalReplies.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Due this week</CardTitle>
            <CardDescription>Replies due in the next 7 days.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold text-[var(--color-ink)]">
              {dueThisWeekReplies.length + dueThisWeekGlobalReplies.length}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle as="h1">Notices</CardTitle>
            <CardDescription>
              Notice received and notice sent workflows linked to {matterLabel}.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button href={`/app/matters/${matterId}/documents`} variant="outline">
              <FileText className="h-4 w-4" aria-hidden />
              Documents
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-5 flex flex-wrap gap-2" role="tablist" aria-label="Notice workflows">
            <Button
              type="button"
              variant={activeTab === "received" ? "primary" : "outline"}
              onClick={() => setActiveTab("received")}
              data-testid="notice-received-tab"
            >
              <Inbox className="h-4 w-4" aria-hidden />
              Notice Received
              <Badge tone={activeTab === "received" ? "neutral" : "brand"}>
                {receivedNotices.length + receivedGlobalNotices.length}
              </Badge>
            </Button>
            <Button
              type="button"
              variant={activeTab === "sent" ? "primary" : "outline"}
              onClick={() => setActiveTab("sent")}
              data-testid="notice-sent-tab"
            >
              <Send className="h-4 w-4" aria-hidden />
              Notice Sent
              <Badge tone={activeTab === "sent" ? "neutral" : "brand"}>
                {sentNotices.length + sentGlobalNotices.length}
              </Badge>
            </Button>
          </div>

          {canUpload ? (
            <div
              className="mb-5 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4"
              data-testid="matter-notice-upload-template"
            >
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
                {activeTab === "received" ? (
                  <Inbox className="h-4 w-4" aria-hidden />
                ) : (
                  <Send className="h-4 w-4" aria-hidden />
                )}
                {activeTab === "received" ? "Upload Notice Received" : "Upload Notice Sent"}
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                {activeTab === "received" ? (
                  <div>
                    <Label htmlFor="notice-received-on">Date of receipt</Label>
                    <Input
                      id="notice-received-on"
                      className="mt-1.5"
                      type="date"
                      value={noticeDraft.receivedOn}
                      onChange={(event) =>
                        setNoticeDraft((current) => ({
                          ...current,
                          receivedOn: event.target.value,
                        }))
                      }
                      data-testid="matter-notice-received-on"
                    />
                  </div>
                ) : (
                  <div>
                    <Label htmlFor="notice-sent-on">Notice sent date</Label>
                    <Input
                      id="notice-sent-on"
                      className="mt-1.5"
                      type="date"
                      value={noticeDraft.sentOn}
                      onChange={(event) =>
                        setNoticeDraft((current) => ({
                          ...current,
                          sentOn: event.target.value,
                        }))
                      }
                      data-testid="matter-notice-sent-on"
                    />
                  </div>
                )}
                <div>
                  <Label htmlFor="notice-type">Type of notice</Label>
                  <Input
                    id="notice-type"
                    className="mt-1.5"
                    value={noticeDraft.noticeType}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        noticeType: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-type"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-status">Status</Label>
                  <Input
                    id="notice-status"
                    className="mt-1.5"
                    value={noticeDraft.status}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        status: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-status"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-department">Department / SPOC</Label>
                  <Input
                    id="notice-department"
                    className="mt-1.5"
                    value={noticeDraft.department}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        department: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-department"
                  />
                </div>
                <div className="md:col-span-2">
                  <Label htmlFor="notice-subject">Subject</Label>
                  <Input
                    id="notice-subject"
                    className="mt-1.5"
                    value={noticeDraft.subject}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        subject: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-subject"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-authority">Authority</Label>
                  <Input
                    id="notice-authority"
                    className="mt-1.5"
                    value={noticeDraft.authority}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        authority: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-authority"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-spoc">Internal SPOC</Label>
                  <Input
                    id="notice-spoc"
                    className="mt-1.5"
                    value={noticeDraft.internalSpoc}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        internalSpoc: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-internal-spoc"
                  />
                </div>
                {activeTab === "received" ? (
                  <>
                    <div>
                      <Label htmlFor="notice-mode">Mode of receiving</Label>
                      <Input
                        id="notice-mode"
                        className="mt-1.5"
                        value={noticeDraft.mode}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            mode: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-mode"
                      />
                    </div>
                    <div>
                      <Label htmlFor="notice-received-from">Received from</Label>
                      <Input
                        id="notice-received-from"
                        className="mt-1.5"
                        value={noticeDraft.receivedFrom}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            receivedFrom: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-source"
                      />
                    </div>
                    <div>
                      <Label htmlFor="notice-amount">Amount</Label>
                      <Input
                        id="notice-amount"
                        className="mt-1.5"
                        inputMode="decimal"
                        value={noticeDraft.amount}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            amount: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-amount"
                      />
                    </div>
                    <div>
                      <Label htmlFor="notice-reply-due-on">Reply due date</Label>
                      <Input
                        id="notice-reply-due-on"
                        className="mt-1.5"
                        type="date"
                        value={noticeDraft.replyDueOn}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            replyDueOn: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-reply-due-on"
                      />
                    </div>
                    <div className="flex items-center gap-2 pt-6">
                      <input
                        id="notice-reply-required"
                        type="checkbox"
                        checked={noticeDraft.replyRequired}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            replyRequired: event.target.checked,
                          }))
                        }
                        data-testid="matter-notice-reply-required"
                      />
                      <Label htmlFor="notice-reply-required">Reply required</Label>
                    </div>
                    <div className="flex items-center gap-2 pt-6">
                      <input
                        id="notice-reply-sent"
                        type="checkbox"
                        checked={noticeDraft.replySent}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            replySent: event.target.checked,
                          }))
                        }
                        data-testid="matter-notice-reply-sent"
                      />
                      <Label htmlFor="notice-reply-sent">Reply sent</Label>
                    </div>
                    {noticeDraft.replySent ? (
                      <div>
                        <Label htmlFor="notice-reply-sent-on">Reply sent date</Label>
                        <Input
                          id="notice-reply-sent-on"
                          className="mt-1.5"
                          type="date"
                          value={noticeDraft.replySentOn}
                          onChange={(event) =>
                            setNoticeDraft((current) => ({
                              ...current,
                              replySentOn: event.target.value,
                            }))
                          }
                          data-testid="matter-notice-reply-sent-on"
                        />
                      </div>
                    ) : null}
                    <div className="md:col-span-2">
                      <Label htmlFor="notice-response">Response / reply plan</Label>
                      <Textarea
                        id="notice-response"
                        className="mt-1.5"
                        value={noticeDraft.response}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            response: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-response"
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <Label htmlFor="notice-counsel">Counsel engaged</Label>
                      <Input
                        id="notice-counsel"
                        className="mt-1.5"
                        value={noticeDraft.counselEngaged}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            counselEngaged: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-counsel"
                      />
                    </div>
                    <div>
                      <Label htmlFor="notice-dispute-amount">Dispute amount</Label>
                      <Input
                        id="notice-dispute-amount"
                        className="mt-1.5"
                        inputMode="decimal"
                        value={noticeDraft.disputeAmount}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            disputeAmount: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-dispute-amount"
                      />
                    </div>
                    <div>
                      <Label htmlFor="notice-recovered-amount">Recovered amount</Label>
                      <Input
                        id="notice-recovered-amount"
                        className="mt-1.5"
                        inputMode="decimal"
                        value={noticeDraft.recoveredAmount}
                        onChange={(event) =>
                          setNoticeDraft((current) => ({
                            ...current,
                            recoveredAmount: event.target.value,
                          }))
                        }
                        data-testid="matter-notice-recovered-amount"
                      />
                    </div>
                  </>
                )}
                <div>
                  <Label htmlFor="notice-currency">Currency</Label>
                  <Input
                    id="notice-currency"
                    className="mt-1.5 uppercase"
                    maxLength={3}
                    value={noticeDraft.currency}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        currency: event.target.value.toUpperCase(),
                      }))
                    }
                    data-testid="matter-notice-currency"
                  />
                </div>
                <div className="md:col-span-2">
                  <Label htmlFor="notice-summary">Summary</Label>
                  <Textarea
                    id="notice-summary"
                    className="mt-1.5"
                    value={noticeDraft.summary}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        summary: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-summary"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-remarks">Remarks</Label>
                  <Textarea
                    id="notice-remarks"
                    className="mt-1.5"
                    value={noticeDraft.remarks}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        remarks: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-remarks"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-internal-remarks">Internal remarks</Label>
                  <Textarea
                    id="notice-internal-remarks"
                    className="mt-1.5"
                    value={noticeDraft.internalRemarks}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        internalRemarks: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-internal-remarks"
                  />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="inline-flex items-center gap-2 text-xs text-[var(--color-mute)]">
                  <Bell className="h-4 w-4" aria-hidden />
                  Reply reminders are tracked 7, 3, and 1 day before due date.
                </div>
                <input
                  ref={noticeFileInput}
                  type="file"
                  className="hidden"
                  data-testid="matter-notice-file-input"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) uploadMutation.mutate(file);
                  }}
                />
                <Button
                  type="button"
                  disabled={uploadMutation.isPending}
                  onClick={() => noticeFileInput.current?.click()}
                  data-testid="matter-notice-upload"
                >
                  {uploadMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Upload className="h-4 w-4" aria-hidden />
                  )}
                  {activeTab === "received" ? "Upload received notice" : "Upload sent notice"}
                </Button>
              </div>
            </div>
          ) : null}

          <div className="mb-5 rounded-lg border border-[var(--color-line)] bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <Filter className="h-4 w-4" aria-hidden />
              Search and filters
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <div className="md:col-span-2">
                <Label htmlFor="notice-filter-query">Search</Label>
                <div className="relative mt-1.5">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[var(--color-mute)]" />
                  <Input
                    id="notice-filter-query"
                    className="pl-9"
                    value={filters.query}
                    onChange={(event) =>
                      setFilters((current) => ({
                        ...current,
                        query: event.target.value,
                      }))
                    }
                    data-testid="notice-filter-query"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="notice-filter-status">Status</Label>
                <select
                  id="notice-filter-status"
                  className={`${selectClass} mt-1.5`}
                  value={filters.status}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, status: event.target.value }))
                  }
                  data-testid="notice-filter-status"
                >
                  <option value="">All statuses</option>
                  {statusOptions.map((statusValue) => (
                    <option key={statusValue} value={statusValue}>
                      {statusValue}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="notice-filter-reply-status">Reply status</Label>
                <select
                  id="notice-filter-reply-status"
                  className={`${selectClass} mt-1.5`}
                  value={filters.replyStatus}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      replyStatus: event.target.value,
                    }))
                  }
                  disabled={activeTab === "sent"}
                  data-testid="notice-filter-reply-status"
                >
                  <option value="">All reply statuses</option>
                  <option value="reply_pending">Reply pending</option>
                  <option value="reply_sent">Reply sent</option>
                  <option value="reply_overdue">Reply overdue</option>
                  <option value="reply_due_today">Reply due today</option>
                  <option value="reply_due_in_days">Reply due in days</option>
                  <option value="not_required">No reply required</option>
                </select>
              </div>
              <div>
                <Label htmlFor="notice-filter-due-from">Due from</Label>
                <Input
                  id="notice-filter-due-from"
                  className="mt-1.5"
                  type="date"
                  value={filters.dueFrom}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, dueFrom: event.target.value }))
                  }
                  data-testid="notice-filter-due-from"
                />
              </div>
              <div>
                <Label htmlFor="notice-filter-due-to">Due to</Label>
                <Input
                  id="notice-filter-due-to"
                  className="mt-1.5"
                  type="date"
                  value={filters.dueTo}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, dueTo: event.target.value }))
                  }
                  data-testid="notice-filter-due-to"
                />
              </div>
              <div>
                <Label htmlFor="notice-filter-authority">Authority</Label>
                <Input
                  id="notice-filter-authority"
                  className="mt-1.5"
                  value={filters.authority}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      authority: event.target.value,
                    }))
                  }
                  data-testid="notice-filter-authority"
                />
              </div>
              <div>
                <Label htmlFor="notice-filter-matter">Matter</Label>
                <Input
                  id="notice-filter-matter"
                  className="mt-1.5"
                  value={filters.matter}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, matter: event.target.value }))
                  }
                  data-testid="notice-filter-matter"
                />
              </div>
              <div>
                <Label htmlFor="notice-filter-department">Department</Label>
                <Input
                  id="notice-filter-department"
                  className="mt-1.5"
                  value={filters.department}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      department: event.target.value,
                    }))
                  }
                  data-testid="notice-filter-department"
                />
              </div>
            </div>
          </div>

          <input
            ref={relatedFileInput}
            type="file"
            className="hidden"
            data-testid="matter-notice-related-file-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file && relatedUploadTarget) {
                relatedUploadMutation.mutate({ file, target: relatedUploadTarget });
              }
            }}
          />

          {visibleGlobalNotices.length > 0 ? (
            <div className="mb-4 space-y-3" data-testid="linked-global-notices">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                    Linked global notices
                  </h2>
                  <p className="text-xs text-[var(--color-mute)]">
                    One source record shared with this matter; the file is not duplicated.
                  </p>
                </div>
                <Button href="/app/notices" variant="outline" size="sm">
                  Manage global register
                </Button>
              </div>
              {visibleGlobalNotices.map((notice) => (
                <article
                  key={notice.id}
                  className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4"
                  data-testid={`matter-global-notice-${notice.id}`}
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                          {notice.subject}
                        </h3>
                        <Badge tone="success">Global notice</Badge>
                        <Badge tone={notice.direction === "received" ? "brand" : "neutral"}>
                          {notice.direction === "received" ? "Received" : "Sent"}
                        </Badge>
                        <Badge>{notice.status}</Badge>
                      </div>
                      <div className="mt-2 grid gap-2 text-xs text-[var(--color-ink-2)] sm:grid-cols-2 lg:grid-cols-3">
                        <span>
                          {notice.direction === "received" ? "Received" : "Sent"}{" "}
                          {formatDate(
                            notice.direction === "received"
                              ? notice.received_on
                              : notice.sent_on,
                          )}
                        </span>
                        {notice.type ? <span>Type: {notice.type}</span> : null}
                        {notice.authority ? <span>Authority: {notice.authority}</span> : null}
                        {notice.department ? <span>Department: {notice.department}</span> : null}
                        {notice.owner_name ? <span>Owner: {notice.owner_name}</span> : null}
                        {notice.reply_due_on ? (
                          <span>Reply due: {formatDate(notice.reply_due_on)}</span>
                        ) : null}
                        {notice.filename ? <span>File: {notice.filename}</span> : null}
                      </div>
                      {notice.summary ? (
                        <p className="mt-2 text-xs leading-5 text-[var(--color-ink-2)]">
                          {notice.summary}
                        </p>
                      ) : null}
                    </div>
                    {notice.has_file ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={downloadingGlobalId === notice.id}
                        onClick={() => downloadGlobalNotice(notice)}
                        aria-label={`Download linked ${notice.filename ?? "notice document"}`}
                      >
                        {downloadingGlobalId === notice.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <Download className="h-4 w-4" aria-hidden />
                        )}
                        Download
                      </Button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : null}

          {visibleNotices.length === 0 && visibleGlobalNotices.length === 0 ? (
            <EmptyState
              icon={activeTab === "received" ? Inbox : Send}
              title={activeTab === "received" ? "No received notices" : "No sent notices"}
              description={
                canUpload
                  ? "No notices on file yet. Upload a notice with structured metadata, or adjust the filters."
                  : "Classified notice documents will appear here when available."
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line)] rounded-lg border border-[var(--color-line)] bg-white">
              {visibleNotices.map((notice) => {
                const viewHref = `/app/matters/${matterId}/documents/${notice.id}/view`;
                const children = childDocumentsByParent.get(notice.id) ?? [];
                const isOverdue = replyStatus(notice) === "reply_overdue";
                const replySentOn = replySentDates[notice.id] ?? notice.notice_reply_sent_on ?? "";
                const amount =
                  noticeDirection(notice) === "received"
                    ? formatMoney(notice.notice_amount_minor, notice.notice_currency)
                    : formatMoney(
                        notice.notice_dispute_amount_minor,
                        notice.notice_currency,
                      );
                const recovered = formatMoney(
                  notice.notice_recovered_amount_minor,
                  notice.notice_currency,
                );
                const receivedFrom = notice.notice_received_from ?? notice.notice_source;
                return (
                  <li
                    key={notice.id}
                    className={`px-4 py-4 ${isOverdue ? "border-l-4 border-l-amber-500 bg-amber-50/50" : ""}`}
                    data-testid="matter-notice-row"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                            {notice.notice_subject ?? displayName(notice)}
                          </h2>
                          <Badge tone={noticeDirection(notice) === "received" ? "brand" : "neutral"}>
                            {noticeDirection(notice) === "received" ? "Received" : "Sent"}
                          </Badge>
                          <Badge tone="neutral">{notice.notice_status || "Open"}</Badge>
                          {noticeDirection(notice) === "received" ? (
                            <Badge tone={replyBadgeTone(notice)}>
                              {replyStatusLabel(notice)}
                            </Badge>
                          ) : null}
                          <StatusBadge status={notice.processing_status ?? "unknown"} />
                        </div>
                        {notice.notice_subject ? (
                          <div className="mt-1 truncate text-xs text-[var(--color-mute)]">
                            {displayName(notice)}
                          </div>
                        ) : null}
                        <div className="mt-2 grid gap-2 text-xs text-[var(--color-ink-2)] sm:grid-cols-2 lg:grid-cols-3">
                          <span>
                            {noticeDirection(notice) === "received" ? "Received" : "Sent"}{" "}
                            {formatDate(noticeDate(notice))}
                          </span>
                          {notice.notice_type ? <span>Type: {notice.notice_type}</span> : null}
                          {notice.notice_authority ? <span>Authority: {notice.notice_authority}</span> : null}
                          {receivedFrom ? <span>From: {receivedFrom}</span> : null}
                          {notice.notice_department ? <span>Department: {notice.notice_department}</span> : null}
                          {notice.notice_internal_spoc ? <span>SPOC: {notice.notice_internal_spoc}</span> : null}
                          {amount ? <span>Amount: {amount}</span> : null}
                          {recovered ? <span>Recovered: {recovered}</span> : null}
                          {notice.notice_reply_due_on ? (
                            <span>Reply due: {formatDate(notice.notice_reply_due_on)}</span>
                          ) : null}
                          {notice.notice_reply_sent_on ? (
                            <span>Reply sent: {formatDate(notice.notice_reply_sent_on)}</span>
                          ) : null}
                          {notice.notice_counsel_engaged ? (
                            <span>Counsel: {notice.notice_counsel_engaged}</span>
                          ) : null}
                          <span>{humanSize(notice.size_bytes)}</span>
                        </div>
                        {notice.notice_summary ? (
                          <p className="mt-2 text-xs leading-5 text-[var(--color-ink-2)]">
                            {notice.notice_summary}
                          </p>
                        ) : null}
                        {notice.notice_response ? (
                          <p className="mt-2 text-xs leading-5 text-[var(--color-ink-2)]">
                            Response: {notice.notice_response}
                          </p>
                        ) : null}
                        {notice.notice_internal_remarks ? (
                          <p className="mt-2 text-xs leading-5 text-[var(--color-mute)]">
                            Internal: {notice.notice_internal_remarks}
                          </p>
                        ) : null}
                        {noticeDirection(notice) === "received" ? (
                          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                            <Bell className="h-4 w-4" aria-hidden />
                            Reminders: {(notice.notice_reminder_offsets ?? [7, 3, 1]).join(", ")} days before
                          </div>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <Button href={viewHref} variant="outline" size="sm">
                          <Eye className="h-4 w-4" aria-hidden />
                          View
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={relatedUploadMutation.isPending}
                          onClick={() => {
                            setRelatedUploadTarget({
                              parentId: notice.id,
                              parentSubject: notice.notice_subject ?? displayName(notice),
                              direction: noticeDirection(notice),
                              role: "supporting",
                            });
                            relatedFileInput.current?.click();
                          }}
                        >
                          <Paperclip className="h-4 w-4" aria-hidden />
                          Add document
                        </Button>
                        {noticeDirection(notice) === "received" ? (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={relatedUploadMutation.isPending}
                            onClick={() => {
                              setRelatedUploadTarget({
                                parentId: notice.id,
                                parentSubject: notice.notice_subject ?? displayName(notice),
                                direction: "received",
                                role: "reply",
                              });
                              relatedFileInput.current?.click();
                            }}
                          >
                            <Upload className="h-4 w-4" aria-hidden />
                            Reply document
                          </Button>
                        ) : null}
                        {canManageDocuments ? (
                          <Button
                            href={`/app/matters/${matterId}/documents`}
                            variant="ghost"
                            size="sm"
                          >
                            Manage
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {noticeDirection(notice) === "received" ? (
                      <div className="mt-3 flex flex-wrap items-end gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
                        <div>
                          <Label htmlFor={`reply-sent-on-${notice.id}`}>Reply sent date</Label>
                          <Input
                            id={`reply-sent-on-${notice.id}`}
                            className="mt-1.5 w-44"
                            type="date"
                            value={replySentOn}
                            onChange={(event) =>
                              setReplySentDates((current) => ({
                                ...current,
                                [notice.id]: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={markReplySentMutation.isPending}
                          onClick={() => markReplySentMutation.mutate(notice)}
                        >
                          {markReplySentMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                          ) : (
                            <CheckCircle2 className="h-4 w-4" aria-hidden />
                          )}
                          Mark reply sent
                        </Button>
                      </div>
                    ) : null}
                    {children.length > 0 ? (
                      <div className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
                        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">
                          <Paperclip className="h-4 w-4" aria-hidden />
                          Documents and reply history
                        </div>
                        <ul className="space-y-2">
                          {children.map((child) => (
                            <li
                              key={child.id}
                              className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--color-ink-2)]"
                            >
                              <div className="flex min-w-0 flex-wrap items-center gap-2">
                                <Badge tone={noticeDocumentRole(child) === "reply" ? "success" : "neutral"}>
                                  {noticeDocumentRole(child) === "reply" ? "Reply" : "Supporting"}
                                </Badge>
                                <span className="truncate">{displayName(child)}</span>
                                <span>{formatDate(child.document_date ?? child.created_at)}</span>
                              </div>
                              <Button
                                href={`/app/matters/${matterId}/documents/${child.id}/view`}
                                variant="ghost"
                                size="sm"
                              >
                                <Eye className="h-4 w-4" aria-hidden />
                                View
                              </Button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
