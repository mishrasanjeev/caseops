"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  Download,
  Filter,
  Inbox,
  Loader2,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Send,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { listMatters } from "@/lib/api/endpoints";
import {
  type CreateNoticeInput,
  createNotice,
  downloadNoticeFile,
  getNotice,
  listNotices,
  listNoticeOwners,
  type NoticeDirection,
  type NoticeListParams,
  type NoticeRecord,
  type UpdateNoticeInput,
  updateNotice,
  uploadNoticeFile,
} from "@/lib/api/notices";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate, todayLocalDateInput } from "@/lib/dates";
import { getStoredContext } from "@/lib/session";

type NoticeFilters = {
  query: string;
  status: string;
  matterId: string;
  ownerId: string;
  dueFrom: string;
  dueTo: string;
};

type MatterOption = { id: string; matter_code: string; title: string };
type OwnerOption = { membership_id: string; full_name: string };

type NoticeDraft = {
  direction: NoticeDirection;
  subject: string;
  noticeType: string;
  mode: string;
  authority: string;
  receivedFrom: string;
  summary: string;
  response: string;
  remarks: string;
  status: string;
  department: string;
  ownerMembershipId: string;
  receivedOn: string;
  sentOn: string;
  replyDueOn: string;
  replyRequired: boolean;
  replySent: boolean;
  replySentOn: string;
  amount: string;
  disputeAmount: string;
  recoveredAmount: string;
  currency: string;
  counselEngaged: string;
  internalSpoc: string;
  internalRemarks: string;
};

const EMPTY_FILTERS: NoticeFilters = {
  query: "",
  status: "",
  matterId: "all",
  ownerId: "all",
  dueFrom: "",
  dueTo: "",
};

const STATUS_OPTIONS = ["Open", "Under Review", "Response Pending", "Responded", "Closed"];
const selectClass =
  "flex h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-60";

function emptyDraft(): NoticeDraft {
  const today = todayLocalDateInput();
  return {
    direction: "received",
    subject: "",
    noticeType: "",
    mode: "",
    authority: "",
    receivedFrom: "",
    summary: "",
    response: "",
    remarks: "",
    status: "Open",
    department: "",
    ownerMembershipId: "",
    receivedOn: today,
    sentOn: today,
    replyDueOn: "",
    replyRequired: false,
    replySent: false,
    replySentOn: "",
    amount: "",
    disputeAmount: "",
    recoveredAmount: "",
    currency: "INR",
    counselEngaged: "",
    internalSpoc: "",
    internalRemarks: "",
  };
}

function minorToInput(value: number | null): string {
  return value === null ? "" : String(value / 100);
}

function noticeDraft(notice: NoticeRecord): NoticeDraft {
  return {
    direction: notice.direction,
    subject: notice.subject,
    noticeType: notice.type ?? "",
    mode: notice.mode ?? "",
    authority: notice.authority ?? "",
    receivedFrom: notice.received_from ?? "",
    summary: notice.summary ?? "",
    response: notice.response ?? "",
    remarks: notice.remarks ?? "",
    status: notice.status,
    department: notice.department ?? "",
    ownerMembershipId: notice.owner_membership_id ?? "",
    receivedOn: notice.received_on?.slice(0, 10) ?? "",
    sentOn: notice.sent_on?.slice(0, 10) ?? "",
    replyDueOn: notice.reply_due_on?.slice(0, 10) ?? "",
    replyRequired: notice.reply_required,
    replySent: notice.reply_sent,
    replySentOn: notice.reply_sent_on?.slice(0, 10) ?? "",
    amount: minorToInput(notice.amount_minor),
    disputeAmount: minorToInput(notice.dispute_amount_minor),
    recoveredAmount: minorToInput(notice.recovered_amount_minor),
    currency: notice.currency,
    counselEngaged: notice.counsel_engaged ?? "",
    internalSpoc: notice.internal_spoc ?? "",
    internalRemarks: notice.internal_remarks ?? "",
  };
}

function amountToMinor(value: string): number | null {
  const normalized = value.trim().replace(/,/g, "");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed * 100) : null;
}

function toPayload(draft: NoticeDraft, matterIds: string[]): CreateNoticeInput {
  const received = draft.direction === "received";
  return {
    direction: draft.direction,
    subject: draft.subject.trim(),
    type: draft.noticeType.trim() || null,
    mode: draft.mode.trim() || null,
    authority: draft.authority.trim() || null,
    received_from: received ? draft.receivedFrom.trim() || null : null,
    summary: draft.summary.trim() || null,
    response: draft.response.trim() || null,
    remarks: draft.remarks.trim() || null,
    status: draft.status,
    department: draft.department.trim() || null,
    owner_membership_id: draft.ownerMembershipId || null,
    received_on: received ? draft.receivedOn || null : null,
    sent_on: received ? null : draft.sentOn || null,
    reply_due_on: received && draft.replyRequired ? draft.replyDueOn || null : null,
    reply_required: received && draft.replyRequired,
    reply_sent: received && draft.replyRequired && draft.replySent,
    reply_sent_on:
      received && draft.replyRequired && draft.replySent
        ? draft.replySentOn || null
        : null,
    amount_minor: received ? amountToMinor(draft.amount) : null,
    dispute_amount_minor: received ? null : amountToMinor(draft.disputeAmount),
    recovered_amount_minor: received ? null : amountToMinor(draft.recoveredAmount),
    currency: draft.currency.trim().toUpperCase(),
    counsel_engaged: draft.counselEngaged.trim() || null,
    internal_spoc: draft.internalSpoc.trim() || null,
    internal_remarks: draft.internalRemarks.trim() || null,
    matter_ids: matterIds,
  };
}

async function loadAllMatters(): Promise<MatterOption[]> {
  const matters = new Map<string, MatterOption>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  while (true) {
    const page = await listMatters({ limit: 100, cursor });
    for (const matter of page.matters) {
      matters.set(matter.id, {
        id: matter.id,
        matter_code: matter.matter_code,
        title: matter.title,
      });
    }
    const next = page.next_cursor ?? null;
    if (!next || seenCursors.has(next)) break;
    seenCursors.add(next);
    cursor = next;
  }
  return Array.from(matters.values()).sort((left, right) =>
    `${left.matter_code} ${left.title}`.localeCompare(`${right.matter_code} ${right.title}`),
  );
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value: string | null): string {
  return value
    ? formatLegalDate(value, { day: "2-digit", month: "short", year: "numeric" })
    : "Not set";
}

function noticeDate(notice: NoticeRecord): string | null {
  return notice.direction === "received" ? notice.received_on : notice.sent_on;
}

function isLegacy(notice: NoticeRecord): boolean {
  return notice.read_only || notice.source_kind === "legacy_attachment";
}

function isClosed(notice: NoticeRecord): boolean {
  return ["closed", "responded", "disposed"].includes(notice.status.toLowerCase());
}

function isOverdue(notice: NoticeRecord, today: string): boolean {
  return Boolean(
    notice.direction === "received" &&
      notice.reply_required &&
      !notice.reply_sent &&
      !isClosed(notice) &&
      notice.reply_due_on &&
      notice.reply_due_on.slice(0, 10) < today,
  );
}

function NoticeFormDialog({
  open,
  onOpenChange,
  notice,
  matters,
  mattersPending,
  mattersError,
  owners,
  canAssignOwner,
  submitting,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  notice: NoticeRecord | null;
  matters: MatterOption[];
  mattersPending: boolean;
  mattersError: boolean;
  owners: OwnerOption[];
  canAssignOwner: boolean;
  submitting: boolean;
  onSubmit: (input: { payload: CreateNoticeInput; file: File | null }) => void;
}) {
  const [draft, setDraft] = useState<NoticeDraft>(emptyDraft);
  const [matterIds, setMatterIds] = useState<string[]>([]);
  const [matterSearch, setMatterSearch] = useState("");
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (!open) return;
    setDraft(notice ? noticeDraft(notice) : emptyDraft());
    setMatterIds(notice?.matter_links.map((matter) => matter.matter_id) ?? []);
    setMatterSearch("");
    setFile(null);
  }, [notice, open]);

  const visibleMatters = matters.filter((matter) =>
    `${matter.matter_code} ${matter.title}`
      .toLocaleLowerCase()
      .includes(matterSearch.trim().toLocaleLowerCase()),
  );
  const invalidAmount = [draft.amount, draft.disputeAmount, draft.recoveredAmount].some(
    (value) => value.trim() !== "" && amountToMinor(value) === null,
  );
  const valid =
    Boolean(draft.subject.trim()) &&
    /^[A-Za-z]{3}$/.test(draft.currency.trim()) &&
    !invalidAmount;

  const toggleMatter = (matterId: string, checked: boolean) => {
    setMatterIds((current) =>
      checked
        ? current.includes(matterId)
          ? current
          : [...current, matterId]
        : current.filter((id) => id !== matterId),
    );
  };

  const textField = (
    id: string,
    label: string,
    key: keyof NoticeDraft,
    options: { required?: boolean; type?: string; placeholder?: string; maxLength?: number } = {},
  ) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        required={options.required}
        type={options.type}
        placeholder={options.placeholder}
        maxLength={options.maxLength}
        value={String(draft[key])}
        onChange={(event) =>
          setDraft((current) => ({ ...current, [key]: event.target.value }))
        }
      />
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="create-notice-dialog">
        <DialogHeader>
          <DialogTitle>{notice ? "Manage notice" : "Create notice"}</DialogTitle>
          <DialogDescription>
            {notice
              ? "Update the complete standalone record and its matter links."
              : "Record a notice independently. Matter links and a document are optional."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-5"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            if (valid) onSubmit({ payload: toPayload(draft, matterIds), file });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-notice-direction">Direction</Label>
              <select
                id="new-notice-direction"
                className={selectClass}
                value={draft.direction}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    direction: event.target.value as NoticeDirection,
                  }))
                }
              >
                <option value="received">Received</option>
                <option value="sent">Sent</option>
              </select>
            </div>
            {textField(
              "new-notice-date",
              draft.direction === "received" ? "Received on" : "Sent on",
              draft.direction === "received" ? "receivedOn" : "sentOn",
              { type: "date" },
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-notice-status">Status</Label>
              <select
                id="new-notice-status"
                className={selectClass}
                value={draft.status}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, status: event.target.value }))
                }
              >
                {Array.from(new Set([...STATUS_OPTIONS, draft.status])).map((status) => (
                  <option key={status} value={status}>{humanize(status)}</option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2 lg:col-span-3">
              {textField("new-notice-subject", "Subject", "subject", {
                required: true,
                maxLength: 500,
                placeholder: "Short, identifiable notice subject",
              })}
            </div>
            {textField("new-notice-type", "Notice type", "noticeType")}
            {textField("new-notice-authority", "Authority / counterparty", "authority")}
            {textField("new-notice-mode", "Mode", "mode", { placeholder: "Email, post, portal..." })}
            {draft.direction === "received"
              ? textField("new-notice-from", "Received from", "receivedFrom")
              : null}
            {textField("new-notice-department", "Department", "department")}
            {textField("new-notice-spoc", "Internal SPOC", "internalSpoc")}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-notice-owner">Owner</Label>
              <select
                id="new-notice-owner"
                className={selectClass}
                disabled={!canAssignOwner}
                value={draft.ownerMembershipId}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, ownerMembershipId: event.target.value }))
                }
              >
                <option value="">Unassigned</option>
                {owners.map((owner) => (
                  <option key={owner.membership_id} value={owner.membership_id}>
                    {owner.full_name}
                  </option>
                ))}
              </select>
              {!canAssignOwner ? (
                <p className="text-xs text-[var(--color-mute)]">
                  Owner changes require document management permission.
                </p>
              ) : null}
            </div>
            {draft.direction === "received" ? (
              <>
                {textField("new-notice-amount", "Amount", "amount", { placeholder: "0.00" })}
                <div className="flex items-center gap-2 pt-7">
                  <input
                    id="new-notice-reply-required"
                    type="checkbox"
                    checked={draft.replyRequired}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, replyRequired: event.target.checked }))
                    }
                  />
                  <Label htmlFor="new-notice-reply-required">Reply required</Label>
                </div>
                {draft.replyRequired ? (
                  <>
                    {textField("new-notice-reply-due", "Reply due on", "replyDueOn", { type: "date" })}
                    <div className="flex items-center gap-2 pt-7">
                      <input
                        id="new-notice-reply-sent"
                        type="checkbox"
                        checked={draft.replySent}
                        onChange={(event) =>
                          setDraft((current) => ({ ...current, replySent: event.target.checked }))
                        }
                      />
                      <Label htmlFor="new-notice-reply-sent">Reply sent</Label>
                    </div>
                    {draft.replySent
                      ? textField("new-notice-reply-sent-on", "Reply sent on", "replySentOn", { type: "date" })
                      : null}
                  </>
                ) : null}
              </>
            ) : (
              <>
                {textField("new-notice-dispute-amount", "Dispute amount", "disputeAmount", { placeholder: "0.00" })}
                {textField("new-notice-recovered-amount", "Recovered amount", "recoveredAmount", { placeholder: "0.00" })}
              </>
            )}
            {textField("new-notice-currency", "Currency", "currency", { maxLength: 3 })}
            {textField("new-notice-counsel", "Counsel engaged", "counselEngaged")}
            <div className="sm:col-span-2 lg:col-span-3">
              <Label htmlFor="new-notice-summary">Summary</Label>
              <Textarea id="new-notice-summary" rows={3} value={draft.summary} onChange={(event) => setDraft((current) => ({ ...current, summary: event.target.value }))} />
            </div>
            <div className="sm:col-span-2 lg:col-span-3">
              <Label htmlFor="new-notice-response">Response / reply plan</Label>
              <Textarea id="new-notice-response" rows={3} value={draft.response} onChange={(event) => setDraft((current) => ({ ...current, response: event.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="new-notice-remarks">Remarks</Label>
              <Textarea id="new-notice-remarks" rows={3} value={draft.remarks} onChange={(event) => setDraft((current) => ({ ...current, remarks: event.target.value }))} />
            </div>
            <div>
              <Label htmlFor="new-notice-internal-remarks">Internal remarks</Label>
              <Textarea id="new-notice-internal-remarks" rows={3} value={draft.internalRemarks} onChange={(event) => setDraft((current) => ({ ...current, internalRemarks: event.target.value }))} />
            </div>
          </div>

          <fieldset className="rounded-xl border border-[var(--color-line)] p-4">
            <legend className="px-1 text-sm font-semibold text-[var(--color-ink)]">Link matters (optional)</legend>
            <p className="mb-3 text-xs text-[var(--color-mute)]">
              Add or remove any accessible matter. Leave all boxes clear for a standalone notice.
            </p>
            <Label htmlFor="notice-matter-search">Search accessible matters</Label>
            <Input
              id="notice-matter-search"
              className="mb-3 mt-1.5"
              value={matterSearch}
              onChange={(event) => setMatterSearch(event.target.value)}
              placeholder="Matter code, title, client, or party"
            />
            {mattersPending ? (
              <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading every accessible matter...
              </div>
            ) : mattersError ? (
              <p className="text-sm text-amber-800">Matters could not be loaded. Existing links are preserved until the picker is available.</p>
            ) : visibleMatters.length === 0 ? (
              <p className="text-sm text-[var(--color-mute)]">No accessible matters match this search.</p>
            ) : (
              <div className="grid max-h-48 gap-2 overflow-y-auto sm:grid-cols-2">
                {visibleMatters.map((matter) => (
                  <label key={matter.id} className="flex items-start gap-2 rounded-lg border border-[var(--color-line)] p-2 text-sm">
                    <input type="checkbox" className="mt-0.5" checked={matterIds.includes(matter.id)} onChange={(event) => toggleMatter(matter.id, event.target.checked)} />
                    <span><span className="font-medium">{matter.matter_code}</span> - {matter.title}</span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          {!notice ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-notice-file">Notice document (optional)</Label>
              <Input id="new-notice-file" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <p className="text-xs text-[var(--color-mute)]">The JSON record is saved first; a failed file step can be retried without duplicating the notice.</p>
            </div>
          ) : null}
          {invalidAmount ? <p className="text-sm text-red-700">Amounts must be zero or a positive number.</p> : null}
          {!/^[A-Za-z]{3}$/.test(draft.currency.trim()) ? <p className="text-sm text-red-700">Currency must be a three-letter code.</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting || !valid}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : notice ? <Pencil className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
              {submitting ? "Saving..." : notice ? "Save changes" : "Create notice"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SummaryCard({ title, value, description, warning = false }: { title: string; value: number; description: string; warning?: boolean }) {
  return (
    <Card data-testid={`notice-summary-${title.toLowerCase().replace(/\s/g, "-")}`}>
      <CardHeader className="pb-3"><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader>
      <CardContent className="pt-4"><div className={warning ? "flex items-center gap-2 text-3xl font-semibold text-amber-800" : "text-3xl font-semibold text-[var(--color-ink)]"}>{value}{warning && value > 0 ? <AlertTriangle className="h-5 w-5" aria-hidden /> : null}</div></CardContent>
    </Card>
  );
}

function NoticeCard({ notice, owners, canUpload, canManage, updating, downloading, onEdit, onUpdate, onUpload, onDownload }: {
  notice: NoticeRecord;
  owners: OwnerOption[];
  canUpload: boolean;
  canManage: boolean;
  updating: boolean;
  downloading: boolean;
  onEdit: (notice: NoticeRecord) => void;
  onUpdate: (noticeId: string, input: UpdateNoticeInput) => void;
  onUpload: (noticeId: string, file: File, expectedUpdatedAt: string) => void;
  onDownload: (notice: NoticeRecord) => void;
}) {
  const legacy = isLegacy(notice);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const canAttach = canUpload && !legacy && (!notice.has_file || canManage);
  return (
    <article className="rounded-xl border border-[var(--color-line)] bg-white p-5" data-testid={`notice-row-${notice.id}`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={notice.direction === "received" ? "brand" : "neutral"}>{notice.direction === "received" ? <Inbox className="h-3.5 w-3.5" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}{humanize(notice.direction)}</Badge>
            <Badge tone={legacy ? "warning" : "success"}>{legacy ? "Legacy matter attachment - read-only" : "Global notice"}</Badge>
            {notice.type ? <Badge>{notice.type}</Badge> : null}
          </div>
          <h2 className="mt-3 break-words text-lg font-semibold text-[var(--color-ink)]">{notice.subject || notice.filename || "Untitled notice"}</h2>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-[var(--color-mute)]">
            <span>{notice.direction === "received" ? "Received" : "Sent"}: {formatDate(noticeDate(notice))}</span>
            {notice.authority ? <span>Authority: {notice.authority}</span> : null}
            {notice.department ? <span>Department: {notice.department}</span> : null}
            <span>{notice.owner_name ? `Owner: ${notice.owner_name}` : "Unassigned"}</span>
            {notice.reply_due_on ? <span className={isOverdue(notice, todayLocalDateInput()) ? "font-medium text-amber-800" : undefined}>Reply due: {formatDate(notice.reply_due_on)}</span> : null}
          </div>
          {notice.summary ? <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)]">{notice.summary}</p> : null}
          <div className="mt-4 flex flex-wrap items-center gap-2" aria-label="Linked matters">
            {notice.matter_links.length ? notice.matter_links.map((matter) => (
              <Link key={matter.matter_id} href={`/app/matters/${matter.matter_id}`} className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg-2)] px-2.5 py-1 text-xs font-medium">{matter.matter_code} - {matter.matter_title}</Link>
            )) : <span className="text-xs text-[var(--color-mute)]">Standalone - no linked matters</span>}
          </div>
        </div>
        <div className="grid min-w-60 gap-3">
          {canManage && !legacy ? (
            <>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`notice-status-${notice.id}`}>Status</Label>
                <select id={`notice-status-${notice.id}`} aria-label={`Status for ${notice.subject}`} className={selectClass} value={notice.status} disabled={updating} onChange={(event) => onUpdate(notice.id, { status: event.target.value, expected_updated_at: notice.updated_at })}>
                  {Array.from(new Set([...STATUS_OPTIONS, notice.status])).map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`notice-owner-${notice.id}`}>Owner</Label>
                <select id={`notice-owner-${notice.id}`} aria-label={`Owner for ${notice.subject}`} className={selectClass} value={notice.owner_membership_id ?? ""} disabled={updating} onChange={(event) => onUpdate(notice.id, { owner_membership_id: event.target.value || null, expected_updated_at: notice.updated_at })}>
                  <option value="">Unassigned</option>
                  {owners.map((owner) => <option key={owner.membership_id} value={owner.membership_id}>{owner.full_name}</option>)}
                </select>
              </div>
              <Button type="button" variant="outline" onClick={() => onEdit(notice)}><Pencil className="h-4 w-4" aria-hidden /> Manage details & links</Button>
            </>
          ) : <div><p className="text-xs font-medium text-[var(--color-mute)]">Status</p><Badge className="mt-1">{humanize(notice.status)}</Badge></div>}
          <div className="flex flex-wrap gap-2">
            {notice.has_file ? <Button type="button" variant="outline" disabled={downloading} onClick={() => onDownload(notice)} aria-label={`Download ${notice.filename ?? "notice document"}`}>{downloading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Download className="h-4 w-4" aria-hidden />}{notice.filename ?? "Download document"}</Button> : null}
            {canAttach ? <><input ref={fileInput} type="file" className="sr-only" aria-label={`Document for ${notice.subject}`} disabled={updating} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(notice.id, file, notice.updated_at); event.target.value = ""; }} /><Button type="button" variant="outline" disabled={updating} onClick={() => fileInput.current?.click()} aria-label={`${notice.has_file ? "Replace" : "Attach"} document for ${notice.subject}`}><Paperclip className="h-4 w-4" aria-hidden />{notice.has_file ? "Replace document" : "Attach document"}</Button></> : null}
          </div>
        </div>
      </div>
    </article>
  );
}

export default function NoticesPage() {
  const queryClient = useQueryClient();
  const [activeDirection, setActiveDirection] = useState<NoticeDirection>("received");
  const [filters, setFilters] = useState<NoticeFilters>(EMPTY_FILTERS);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingNotice, setEditingNotice] = useState<NoticeRecord | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const canCreate = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const formOpen = createOpen || Boolean(editingNotice);
  const currentContext = useMemo(() => getStoredContext(), []);

  const registerParams = useMemo<NoticeListParams>(
    () => ({
      limit: 100,
      direction: activeDirection,
      query: filters.query.trim() || undefined,
      status: filters.status.trim() || undefined,
      matter_id: filters.matterId === "all" ? undefined : filters.matterId,
      owner_membership_id:
        filters.ownerId === "all" ? undefined : filters.ownerId,
      due_from: filters.dueFrom || undefined,
      due_to: filters.dueTo || undefined,
    }),
    [activeDirection, filters],
  );

  const noticesQuery = useInfiniteQuery({
    queryKey: ["notices", "register", registerParams],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      listNotices({ ...registerParams, cursor: pageParam }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const receivedTotalQuery = useQuery({
    queryKey: ["notices", "direction-total", "received"],
    queryFn: () => listNotices({ limit: 1, direction: "received" }),
  });
  const sentTotalQuery = useQuery({
    queryKey: ["notices", "direction-total", "sent"],
    queryFn: () => listNotices({ limit: 1, direction: "sent" }),
  });
  const mattersQuery = useQuery({
    queryKey: ["matters", "notice-options", "all"],
    queryFn: loadAllMatters,
  });
  const ownersQuery = useQuery({
    queryKey: ["notices", "owner-options"],
    queryFn: listNoticeOwners,
    enabled: canManage,
  });

  const createMutation = useMutation({
    mutationFn: async ({ payload, file }: { payload: CreateNoticeInput; file: File | null }): Promise<{ fileError: unknown | null }> => {
      const created = await createNotice(payload);
      if (!file) return { fileError: null };
      try { await uploadNoticeFile(created.id, file, created.updated_at); return { fileError: null }; }
      catch (fileError) { return { fileError }; }
    },
    onSuccess: async ({ fileError }) => {
      await queryClient.invalidateQueries({ queryKey: ["notices"] });
      setCreateOpen(false);
      if (fileError) toast.error(`Notice saved, but its document was not attached. ${apiErrorMessage(fileError, "Use Attach document on the saved notice to retry.")}`);
      else toast.success("Notice created.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the notice.")),
  });
  const updateMutation = useMutation({
    mutationFn: ({ noticeId, input }: { noticeId: string; input: UpdateNoticeInput; closeDialog?: boolean }) => updateNotice(noticeId, input),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["notices"] });
      if (variables.closeDialog) setEditingNotice(null);
      toast.success("Notice updated.");
    },
    onError: async (error, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["notices"] });
      if (variables.closeDialog) {
        try {
          setEditingNotice(await getNotice(variables.noticeId));
        } catch {
          // The list invalidation above remains the fallback when the record
          // is no longer visible under the current access policy.
        }
      }
      toast.error(apiErrorMessage(error, "Could not update the notice. Refresh and retry if another session changed it."));
    },
  });
  const fileMutation = useMutation({
    mutationFn: ({ noticeId, file, expectedUpdatedAt }: { noticeId: string; file: File; expectedUpdatedAt: string }) => uploadNoticeFile(noticeId, file, expectedUpdatedAt),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["notices"] }); toast.success("Notice document attached."); },
    onError: async (error) => {
      await queryClient.invalidateQueries({ queryKey: ["notices"] });
      toast.error(apiErrorMessage(error, "Could not attach the notice document. The notice was refreshed; retry with the latest version."));
    },
  });

  const notices = useMemo(() => {
    const records = new Map<string, NoticeRecord>();
    for (const page of noticesQuery.data?.pages ?? []) {
      for (const notice of page.notices) records.set(notice.id, notice);
    }
    return Array.from(records.values());
  }, [noticesQuery.data]);
  const matchingTotal = noticesQuery.data?.pages[0]?.total ?? 0;
  const receivedTotal = receivedTotalQuery.data?.total ?? 0;
  const sentTotal = sentTotalQuery.data?.total ?? 0;

  const directoryOwners = useMemo(() => {
    const options = new Map<string, OwnerOption>();
    for (const notice of notices) if (notice.owner_membership_id && notice.owner_name) options.set(notice.owner_membership_id, { membership_id: notice.owner_membership_id, full_name: notice.owner_name });
    if (currentContext?.membership.id && currentContext.user.full_name) options.set(currentContext.membership.id, { membership_id: currentContext.membership.id, full_name: currentContext.user.full_name });
    for (const owner of ownersQuery.data ?? []) options.set(owner.membership_id, { membership_id: owner.membership_id, full_name: owner.name });
    return Array.from(options.values()).sort((left, right) => left.full_name.localeCompare(right.full_name));
  }, [currentContext, notices, ownersQuery.data]);

  const matterOptions = useMemo(
    () =>
      (mattersQuery.data ?? []).map((matter) => ({
        id: matter.id,
        label: `${matter.matter_code} - ${matter.title}`,
      })),
    [mattersQuery.data],
  );
  const ownerOptions = useMemo(() => directoryOwners.map((owner) => ({ id: owner.membership_id, label: owner.full_name })), [directoryOwners]);
  const statusOptions = useMemo(
    () =>
      Array.from(
        new Set([...STATUS_OPTIONS, ...notices.map((notice) => notice.status)]),
      )
        .filter(Boolean)
        .sort(),
    [notices],
  );
  // The backend is the sole filter authority. Cursor pages are already sorted
  // and filtered; applying the filters again here would make unloaded matches
  // look absent and would turn `total` into a misleading client-page count.
  const visibleNotices = notices;
  const hasFilters = Object.entries(filters).some(([key, value]) =>
    key === "matterId" || key === "ownerId" ? value !== "all" : Boolean(value),
  );

  const download = async (notice: NoticeRecord) => {
    setDownloadingId(notice.id);
    try { await downloadNoticeFile(notice.id, notice.filename ?? "notice-document"); }
    catch (error) { toast.error(apiErrorMessage(error, "Could not download the notice document.")); }
    finally { setDownloadingId(null); }
  };

  return (
    <div className="flex flex-col gap-6" data-testid="notices-page">
      <PageHeader eyebrow="Workspace" title="Notice management" description="Receive, send, assign, track, and search notices across the workspace - with or without a linked matter." actions={canCreate ? <Button type="button" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" aria-hidden /> New notice</Button> : null} />
      {!canCreate ? <div className="rounded-xl border border-[var(--color-line)] bg-white px-4 py-3 text-sm text-[var(--color-mute)]" data-testid="notices-read-only">You have read-only notice access. Ask a workspace administrator for document upload permission to create notices.</div> : null}
      <>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><SummaryCard title="Received" value={receivedTotal} description="All received notices visible in this workspace." /><SummaryCard title="Sent" value={sentTotal} description="All sent notices visible in this workspace." /><SummaryCard title="Matching results" value={matchingTotal} description="Server-authoritative total for the active filters." /><SummaryCard title="Rows loaded" value={notices.length} description="Rows loaded from the current cursor result." /></div>
        <Card><CardHeader><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><CardTitle>Notice register</CardTitle><CardDescription>Global records and clearly identified legacy matter attachments.</CardDescription></div><div className="flex gap-2" role="tablist" aria-label="Notice direction"><Button type="button" size="sm" variant={activeDirection === "received" ? "primary" : "outline"} role="tab" aria-selected={activeDirection === "received"} onClick={() => setActiveDirection("received")} data-testid="notices-received-tab"><Inbox className="h-4 w-4" aria-hidden /> Received ({receivedTotal})</Button><Button type="button" size="sm" variant={activeDirection === "sent" ? "primary" : "outline"} role="tab" aria-selected={activeDirection === "sent"} onClick={() => setActiveDirection("sent")} data-testid="notices-sent-tab"><Send className="h-4 w-4" aria-hidden /> Sent ({sentTotal})</Button></div></div></CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6" aria-label="Notice filters">
              <div className="flex flex-col gap-1.5 md:col-span-2 xl:col-span-2"><Label htmlFor="notice-search">Search</Label><div className="relative"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-[var(--color-mute)]" aria-hidden /><Input id="notice-search" className="pl-9" value={filters.query} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="Subject, authority, owner, matter..." /></div></div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="notice-status-filter">Filter by status</Label><Input id="notice-status-filter" list="notice-status-suggestions" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))} placeholder="All statuses or enter exact status" /><datalist id="notice-status-suggestions">{statusOptions.map((status) => <option key={status} value={status} />)}</datalist></div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="notice-matter-filter">Filter by matter</Label><select id="notice-matter-filter" className={selectClass} value={filters.matterId} onChange={(event) => setFilters((current) => ({ ...current, matterId: event.target.value }))}><option value="all">All matters</option>{matterOptions.map((matter) => <option key={matter.id} value={matter.id}>{matter.label}</option>)}</select></div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="notice-owner-filter">Filter by owner</Label><select id="notice-owner-filter" className={selectClass} value={filters.ownerId} aria-describedby={!canManage ? "notice-owner-filter-scope" : undefined} onChange={(event) => setFilters((current) => ({ ...current, ownerId: event.target.value }))}><option value="all">All owners</option>{ownerOptions.map((owner) => <option key={owner.id} value={owner.id}>{owner.label}</option>)}</select>{!canManage ? <p id="notice-owner-filter-scope" data-testid="notice-owner-filter-scope" className="text-xs leading-4 text-[var(--color-mute)]">Owner choices are limited to you and owners in the loaded results. Document management access is required to browse the full active-member directory.</p> : null}</div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="notice-due-from">Due from</Label><Input id="notice-due-from" type="date" value={filters.dueFrom} onChange={(event) => setFilters((current) => ({ ...current, dueFrom: event.target.value }))} /></div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="notice-due-to">Due to</Label><Input id="notice-due-to" type="date" value={filters.dueTo} onChange={(event) => setFilters((current) => ({ ...current, dueTo: event.target.value }))} /></div>
              <div className="flex items-end gap-2 xl:col-span-2"><span className="inline-flex h-10 items-center gap-2 text-sm text-[var(--color-mute)]"><Filter className="h-4 w-4" aria-hidden /> {visibleNotices.length} of {matchingTotal} loaded</span>{hasFilters ? <Button type="button" variant="ghost" size="sm" onClick={() => setFilters(EMPTY_FILTERS)}><RotateCcw className="h-4 w-4" aria-hidden /> Reset</Button> : null}</div>
            </div>
            {noticesQuery.isPending ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-[var(--color-line)] p-8 text-sm text-[var(--color-mute)]" aria-label="Loading matching notices">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading matching notices...
              </div>
            ) : noticesQuery.isError ? (
              <QueryErrorState title="Could not load notices from this workspace" error={noticesQuery.error} onRetry={noticesQuery.refetch} />
            ) : visibleNotices.length === 0 ? <EmptyState icon={activeDirection === "received" ? Inbox : Send} title={hasFilters ? "No notices match these filters" : `No ${activeDirection} notices`} description={hasFilters ? "Reset or adjust the workspace notice filters." : canCreate ? `Create a ${activeDirection} notice here; linking a matter is optional.` : `There are no ${activeDirection} notices visible in this workspace.`} action={hasFilters ? <Button type="button" variant="outline" onClick={() => setFilters(EMPTY_FILTERS)}><RotateCcw className="h-4 w-4" aria-hidden /> Reset filters</Button> : canCreate ? <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" aria-hidden /> Create notice</Button> : null} /> : <div className="flex flex-col gap-3" aria-live="polite">{visibleNotices.map((notice) => <NoticeCard key={notice.id} notice={notice} owners={directoryOwners} canUpload={canCreate} canManage={canManage} updating={(updateMutation.isPending && updateMutation.variables?.noticeId === notice.id) || (fileMutation.isPending && fileMutation.variables?.noticeId === notice.id)} downloading={downloadingId === notice.id} onEdit={setEditingNotice} onUpdate={(noticeId, input) => updateMutation.mutate({ noticeId, input })} onUpload={(noticeId, file, expectedUpdatedAt) => fileMutation.mutate({ noticeId, file, expectedUpdatedAt })} onDownload={download} />)}</div>}
            {noticesQuery.hasNextPage ? (
              <div className="flex justify-center">
                <Button
                  type="button"
                  variant="outline"
                  disabled={noticesQuery.isFetchingNextPage}
                  onClick={() => noticesQuery.fetchNextPage()}
                >
                  {noticesQuery.isFetchingNextPage ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  {noticesQuery.isFetchingNextPage ? "Loading..." : "Load more notices"}
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </>
      {(canCreate || canManage) ? <NoticeFormDialog open={formOpen} onOpenChange={(open) => { if (!open) { setCreateOpen(false); setEditingNotice(null); } }} notice={editingNotice} matters={mattersQuery.data ?? []} mattersPending={mattersQuery.isPending && formOpen} mattersError={mattersQuery.isError} owners={directoryOwners} canAssignOwner={canManage || Boolean(currentContext?.membership.id)} submitting={createMutation.isPending || updateMutation.isPending} onSubmit={({ payload, file }) => { if (editingNotice) { updateMutation.mutate({ noticeId: editingNotice.id, input: { ...payload, expected_updated_at: editingNotice.updated_at }, closeDialog: true }); } else { createMutation.mutate({ payload, file }); } }} /> : null}
    </div>
  );
}
