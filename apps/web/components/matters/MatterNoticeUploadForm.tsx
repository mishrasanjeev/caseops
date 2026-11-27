"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Bell, Inbox, Loader2, Send, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { ApiError, apiErrorMessage } from "@/lib/api/config";
import { uploadMatterAttachment } from "@/lib/api/endpoints";
import { formatLegalDate, todayLocalDateInput } from "@/lib/dates";
import {
  NOTICE_FIELD_ORDER,
  NOTICE_MAX_DATE,
  NOTICE_MIN_DATE,
  acceptAttribute,
  noticeDuplicateFromApi,
  noticeDuplicateHref,
  noticeErrorsFromApi,
  parseAmountMinor,
  uploadPolicyHint,
  validateNoticeDraft,
  validateNoticeFile,
  type NoticeDuplicate,
  type NoticeFieldErrors,
  type NoticeFieldKey,
  type NoticeFilePolicy,
} from "@/lib/notice-rules";

export type NoticeDirection = "received" | "sent";

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

const EMPTY_DRAFT: NoticeUploadDraft = {
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

/** DOM ids of the inputs each rule anchors to; focus moves to the first. */
const FIELD_INPUT_ID: Record<NoticeFieldKey, string> = {
  received_on: "notice-received-on",
  sent_on: "notice-sent-on",
  type: "notice-type",
  subject: "notice-subject",
  amount_minor: "notice-amount",
  reply_due_on: "notice-reply-due-on",
  reply_sent_on: "notice-reply-sent-on",
  dispute_amount_minor: "notice-dispute-amount",
  recovered_amount_minor: "notice-recovered-amount",
  currency: "notice-currency",
  file: "notice-file",
};

const DATE_FIELDS = new Set<NoticeFieldKey>([
  "received_on",
  "sent_on",
  "reply_due_on",
  "reply_sent_on",
]);

const FILE_ERROR_PATTERN = /upload|file|attachment|extension|signature|bytes/i;

function RequiredMark() {
  return (
    <span className="ml-0.5 text-[var(--color-danger-text)]" aria-hidden>
      *
    </span>
  );
}

export function MatterNoticeUploadForm({
  matterId,
  direction,
  filePolicy,
  onUploaded,
}: {
  matterId: string;
  direction: NoticeDirection;
  filePolicy: NoticeFilePolicy | null;
  onUploaded: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<NoticeUploadDraft>(EMPTY_DRAFT);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<NoticeFieldErrors>({});
  const [unparsableDates, setUnparsableDates] = useState<Set<NoticeFieldKey>>(new Set());
  const [duplicate, setDuplicate] = useState<NoticeDuplicate | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const received = direction === "received";
  const today = todayLocalDateInput();

  useEffect(() => {
    setErrors({});
    setDuplicate(null);
  }, [direction]);

  const update = <K extends keyof NoticeUploadDraft>(
    key: K,
    value: NoticeUploadDraft[K],
    field?: NoticeFieldKey,
  ) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setDuplicate(null);
    if (field) {
      setErrors((current) => {
        if (!current[field]) return current;
        const next = { ...current };
        delete next[field];
        return next;
      });
    }
  };

  const updateDate = (
    key: "receivedOn" | "sentOn" | "replyDueOn" | "replySentOn",
    field: NoticeFieldKey,
    input: HTMLInputElement,
  ) => {
    setUnparsableDates((current) => {
      const next = new Set(current);
      if (input.validity?.badInput) next.add(field);
      else next.delete(field);
      return next;
    });
    update(key, input.value, field);
  };

  const focusFirst = (found: NoticeFieldErrors) => {
    const first = NOTICE_FIELD_ORDER.find((key) => found[key]);
    if (first) document.getElementById(FIELD_INPUT_ID[first])?.focus();
  };

  const showErrors = (found: NoticeFieldErrors) => {
    setErrors(found);
    focusFirst(found);
  };

  const resetForm = () => {
    setDraft(EMPTY_DRAFT);
    setFile(null);
    setErrors({});
    setUnparsableDates(new Set());
    setDuplicate(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const uploadMutation = useMutation({
    mutationFn: ({ notice, allowDuplicate }: { notice: File; allowDuplicate: boolean }) => {
      const amount = parseAmountMinor(draft.amount, "Amount");
      const dispute = parseAmountMinor(draft.disputeAmount, "Dispute amount");
      const recovered = parseAmountMinor(draft.recoveredAmount, "Recovered amount");
      const minor = (parsed: typeof amount) => (parsed.ok ? parsed.minor : null);
      const replySent = received && draft.replySent;
      return uploadMatterAttachment({
        matterId,
        file: notice,
        documentType: "notice",
        lifecycleStage: "initiation",
        documentDate: received ? draft.receivedOn : draft.sentOn,
        noticeDirection: direction,
        noticeDocumentRole: "notice",
        noticeType: draft.noticeType.trim(),
        noticeMode: received ? draft.mode.trim() || null : null,
        noticeSource: received ? draft.receivedFrom.trim() || null : null,
        noticeSubject: draft.subject.trim(),
        noticeReceivedOn: received ? draft.receivedOn : null,
        noticeResponse: received ? draft.response.trim() || null : null,
        noticeAuthority: draft.authority.trim() || null,
        noticeReceivedFrom: received ? draft.receivedFrom.trim() || null : null,
        noticeSummary: draft.summary.trim() || null,
        noticeRemarks: draft.remarks.trim() || null,
        noticeStatus: draft.status.trim() || null,
        noticeDepartment: draft.department.trim() || null,
        noticeInternalSpoc: draft.internalSpoc.trim() || null,
        noticeInternalRemarks: draft.internalRemarks.trim() || null,
        noticeAmountMinor: received ? minor(amount) : null,
        noticeDisputeAmountMinor: received ? null : minor(dispute),
        noticeRecoveredAmountMinor: received ? null : minor(recovered),
        noticeCurrency: draft.currency.trim().toUpperCase() || "INR",
        noticeReplyDueOn: received ? draft.replyDueOn || null : null,
        noticeReplyRequired: received ? draft.replyRequired : false,
        noticeReplySent: replySent,
        noticeReplySentOn: replySent ? draft.replySentOn || today : null,
        noticeSentOn: received ? null : draft.sentOn,
        noticeCounselEngaged: received ? null : draft.counselEngaged.trim() || null,
        sequenceIndex: null,
        linkedCourtOrderId: null,
        hearingId: null,
        allowDuplicate,
      });
    },
    onSuccess: async () => {
      resetForm();
      await onUploaded();
      toast.success(received ? "Notice received uploaded." : "Notice sent uploaded.");
    },
    onError: (error) => {
      const found = noticeErrorsFromApi(error);
      if (Object.keys(found).length > 0) {
        showErrors(found);
        return;
      }
      const conflict = noticeDuplicateFromApi(error);
      if (conflict) {
        setDuplicate(conflict);
        return;
      }
      if (
        error instanceof ApiError &&
        (error.status === 413 || error.status === 400) &&
        FILE_ERROR_PATTERN.test(error.detail)
      ) {
        showErrors({ file: error.detail });
        return;
      }
      toast.error(apiErrorMessage(error, "Could not upload the notice."));
    },
  });

  const submit = (allowDuplicate: boolean) => {
    // A partly typed date leaves value "" with badInput set and may fire no
    // change event, so read the controls themselves at submit time too.
    const unparsable = new Set(unparsableDates);
    for (const key of DATE_FIELDS) {
      const input = document.getElementById(FIELD_INPUT_ID[key]) as HTMLInputElement | null;
      if (input?.validity?.badInput) unparsable.add(key);
    }
    const found: NoticeFieldErrors = validateNoticeDraft(
      { ...draft, direction, unparsableDates: unparsable },
      today,
    );
    const fileError = validateNoticeFile(file, filePolicy);
    if (fileError) found.file = fileError;
    if (Object.keys(found).length > 0 || !file) {
      setDuplicate(null);
      showErrors(found);
      return;
    }
    setErrors({});
    uploadMutation.mutate({ notice: file, allowDuplicate });
  };

  const describe = (field: NoticeFieldKey) =>
    errors[field]
      ? { "aria-invalid": true as const, "aria-describedby": `${FIELD_INPUT_ID[field]}-error` }
      : {};

  const fieldError = (field: NoticeFieldKey) =>
    errors[field] ? (
      <p
        id={`${FIELD_INPUT_ID[field]}-error`}
        className="mt-1 text-xs text-[var(--color-danger-text)]"
        data-testid={`${FIELD_INPUT_ID[field]}-error`}
      >
        {errors[field]}
      </p>
    ) : null;

  const field = (
    id: string,
    label: ReactNode,
    control: ReactNode,
    error: ReactNode = null,
    className = "",
  ) => (
    <div className={className}>
      <Label htmlFor={id}>{label}</Label>
      {control}
      {error}
    </div>
  );

  const text = (
    id: string,
    label: string,
    key: keyof NoticeUploadDraft,
    testId: string,
    className = "",
  ) =>
    field(
      id,
      label,
      <Input
        id={id}
        className="mt-1.5"
        maxLength={255}
        value={String(draft[key])}
        onChange={(event) => update(key, event.target.value as never)}
        data-testid={testId}
      />,
      null,
      className,
    );

  const errorCount = Object.keys(errors).length;
  const replyDueRequired = received && draft.replyRequired && !draft.replySent;

  return (
    <form
      noValidate
      className="mb-5 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4"
      data-testid="matter-notice-upload-template"
      aria-labelledby="matter-notice-upload-heading"
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        submit(false);
      }}
    >
      <div
        id="matter-notice-upload-heading"
        className="mb-1 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]"
      >
        {received ? <Inbox className="h-4 w-4" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
        {received ? "Upload Notice Received" : "Upload Notice Sent"}
      </div>
      <p className="mb-3 text-xs text-[var(--color-mute)]">
        Fields marked <span className="text-[var(--color-danger-text)]">*</span> are required.
      </p>
      <div className="grid gap-3 md:grid-cols-4">
        {received
          ? field(
              "notice-received-on",
              <>Date of receipt<RequiredMark /></>,
              <Input
                id="notice-received-on"
                className="mt-1.5"
                type="date"
                required
                min={NOTICE_MIN_DATE}
                max={today}
                value={draft.receivedOn}
                onChange={(event) => updateDate("receivedOn", "received_on", event.target)}
                data-testid="matter-notice-received-on"
                {...describe("received_on")}
              />,
              fieldError("received_on"),
            )
          : field(
              "notice-sent-on",
              <>Notice sent date<RequiredMark /></>,
              <Input
                id="notice-sent-on"
                className="mt-1.5"
                type="date"
                required
                min={NOTICE_MIN_DATE}
                max={today}
                value={draft.sentOn}
                onChange={(event) => updateDate("sentOn", "sent_on", event.target)}
                data-testid="matter-notice-sent-on"
                {...describe("sent_on")}
              />,
              fieldError("sent_on"),
            )}
        {field(
          "notice-type",
          <>Type of notice<RequiredMark /></>,
          <Input
            id="notice-type"
            className="mt-1.5"
            required
            maxLength={120}
            value={draft.noticeType}
            onChange={(event) => update("noticeType", event.target.value, "type")}
            data-testid="matter-notice-type"
            {...describe("type")}
          />,
          fieldError("type"),
        )}
        {text("notice-status", "Status", "status", "matter-notice-status")}
        {text("notice-department", "Department / SPOC", "department", "matter-notice-department")}
        {field(
          "notice-subject",
          <>Subject<RequiredMark /></>,
          <Input
            id="notice-subject"
            className="mt-1.5"
            required
            maxLength={500}
            value={draft.subject}
            onChange={(event) => update("subject", event.target.value, "subject")}
            data-testid="matter-notice-subject"
            {...describe("subject")}
          />,
          fieldError("subject"),
          "md:col-span-2",
        )}
        {text("notice-authority", "Authority", "authority", "matter-notice-authority")}
        {text("notice-spoc", "Internal SPOC", "internalSpoc", "matter-notice-internal-spoc")}
        {received ? (
          <>
            {text("notice-mode", "Mode of receiving", "mode", "matter-notice-mode")}
            {text("notice-received-from", "Received from", "receivedFrom", "matter-notice-source")}
            {field(
              "notice-amount",
              "Amount",
              <Input
                id="notice-amount"
                className="mt-1.5"
                inputMode="decimal"
                value={draft.amount}
                onChange={(event) => update("amount", event.target.value, "amount_minor")}
                data-testid="matter-notice-amount"
                {...describe("amount_minor")}
              />,
              fieldError("amount_minor"),
            )}
            {field(
              "notice-reply-due-on",
              <>Reply due date{replyDueRequired ? <RequiredMark /> : null}</>,
              <Input
                id="notice-reply-due-on"
                className="mt-1.5"
                type="date"
                required={replyDueRequired}
                min={draft.receivedOn || NOTICE_MIN_DATE}
                max={NOTICE_MAX_DATE}
                value={draft.replyDueOn}
                onChange={(event) => updateDate("replyDueOn", "reply_due_on", event.target)}
                data-testid="matter-notice-reply-due-on"
                {...describe("reply_due_on")}
              />,
              fieldError("reply_due_on"),
            )}
            <div className="flex items-center gap-2 pt-6">
              <input
                id="notice-reply-required"
                type="checkbox"
                checked={draft.replyRequired}
                onChange={(event) => update("replyRequired", event.target.checked, "reply_due_on")}
                data-testid="matter-notice-reply-required"
              />
              <Label htmlFor="notice-reply-required">Reply required</Label>
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input
                id="notice-reply-sent"
                type="checkbox"
                checked={draft.replySent}
                onChange={(event) => update("replySent", event.target.checked, "reply_due_on")}
                data-testid="matter-notice-reply-sent"
              />
              <Label htmlFor="notice-reply-sent">Reply sent</Label>
            </div>
            {draft.replySent
              ? field(
                  "notice-reply-sent-on",
                  "Reply sent date",
                  <Input
                    id="notice-reply-sent-on"
                    className="mt-1.5"
                    type="date"
                    min={draft.receivedOn || NOTICE_MIN_DATE}
                    max={today}
                    value={draft.replySentOn}
                    onChange={(event) => updateDate("replySentOn", "reply_sent_on", event.target)}
                    data-testid="matter-notice-reply-sent-on"
                    {...describe("reply_sent_on")}
                  />,
                  fieldError("reply_sent_on"),
                )
              : null}
            <div className="md:col-span-2">
              <Label htmlFor="notice-response">Response / reply plan</Label>
              <Textarea
                id="notice-response"
                className="mt-1.5"
                value={draft.response}
                onChange={(event) => update("response", event.target.value)}
                data-testid="matter-notice-response"
              />
            </div>
          </>
        ) : (
          <>
            {text("notice-counsel", "Counsel engaged", "counselEngaged", "matter-notice-counsel")}
            {field(
              "notice-dispute-amount",
              "Dispute amount",
              <Input
                id="notice-dispute-amount"
                className="mt-1.5"
                inputMode="decimal"
                value={draft.disputeAmount}
                onChange={(event) =>
                  update("disputeAmount", event.target.value, "dispute_amount_minor")
                }
                data-testid="matter-notice-dispute-amount"
                {...describe("dispute_amount_minor")}
              />,
              fieldError("dispute_amount_minor"),
            )}
            {field(
              "notice-recovered-amount",
              "Recovered amount",
              <Input
                id="notice-recovered-amount"
                className="mt-1.5"
                inputMode="decimal"
                value={draft.recoveredAmount}
                onChange={(event) =>
                  update("recoveredAmount", event.target.value, "recovered_amount_minor")
                }
                data-testid="matter-notice-recovered-amount"
                {...describe("recovered_amount_minor")}
              />,
              fieldError("recovered_amount_minor"),
            )}
          </>
        )}
        {field(
          "notice-currency",
          "Currency",
          <Input
            id="notice-currency"
            className="mt-1.5 uppercase"
            maxLength={3}
            value={draft.currency}
            onChange={(event) => update("currency", event.target.value.toUpperCase(), "currency")}
            data-testid="matter-notice-currency"
            {...describe("currency")}
          />,
          fieldError("currency"),
        )}
        <div className="md:col-span-2">
          <Label htmlFor="notice-summary">Summary</Label>
          <Textarea
            id="notice-summary"
            className="mt-1.5"
            value={draft.summary}
            onChange={(event) => update("summary", event.target.value)}
            data-testid="matter-notice-summary"
          />
        </div>
        <div>
          <Label htmlFor="notice-remarks">Remarks</Label>
          <Textarea
            id="notice-remarks"
            className="mt-1.5"
            value={draft.remarks}
            onChange={(event) => update("remarks", event.target.value)}
            data-testid="matter-notice-remarks"
          />
        </div>
        <div>
          <Label htmlFor="notice-internal-remarks">Internal remarks</Label>
          <Textarea
            id="notice-internal-remarks"
            className="mt-1.5"
            value={draft.internalRemarks}
            onChange={(event) => update("internalRemarks", event.target.value)}
            data-testid="matter-notice-internal-remarks"
          />
        </div>
        <div className="md:col-span-2">
          <Label htmlFor="notice-file">
            Notice document<RequiredMark />
          </Label>
          <Input
            ref={fileInput}
            id="notice-file"
            type="file"
            className="mt-1.5 h-auto"
            required
            accept={acceptAttribute(filePolicy)}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setDuplicate(null);
              setErrors((current) => {
                if (!current.file) return current;
                const next = { ...current };
                delete next.file;
                return next;
              });
            }}
            data-testid="matter-notice-file-input"
            aria-describedby={
              errors.file ? "notice-file-error notice-file-hint" : "notice-file-hint"
            }
            aria-invalid={errors.file ? true : undefined}
          />
          <p id="notice-file-hint" className="mt-1 text-xs text-[var(--color-mute)]">
            {uploadPolicyHint(filePolicy) ?? "Supported document formats only."}
          </p>
          {fieldError("file")}
        </div>
      </div>

      {duplicate ? (
        <div
          role="alert"
          className="mt-3 rounded-md border border-[var(--color-warning)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-ink)]"
          data-testid="matter-notice-duplicate"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning)]" aria-hidden />
            <div className="min-w-0">
              <p className="font-medium">{duplicate.message}</p>
              <p className="mt-1 text-xs text-[var(--color-ink-2)]">
                Existing notice: {duplicate.existing.subject ?? duplicate.existing.filename ?? "Untitled notice"}
                {duplicate.existing.notice_date
                  ? `, ${duplicate.existing.direction === "sent" ? "sent" : "received"} ${formatLegalDate(duplicate.existing.notice_date, { day: "2-digit", month: "short", year: "numeric" })}`
                  : ""}
                .
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Link
                  href={noticeDuplicateHref(duplicate.existing, matterId) ?? `/app/matters/${matterId}/documents/${duplicate.existing.id}/view`}
                  className="text-xs font-medium text-[var(--color-brand-700)] underline underline-offset-2"
                  data-testid="matter-notice-duplicate-link"
                >
                  {duplicate.existing.source_kind === "standalone"
                    ? "Open the existing notice in the register"
                    : "Open the existing notice"}
                </Link>
                {duplicate.overrideAllowed ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={uploadMutation.isPending}
                    onClick={() => submit(true)}
                    data-testid="matter-notice-upload-anyway"
                  >
                    Upload anyway as a separate notice
                  </Button>
                ) : (
                  <span className="text-xs text-[var(--color-mute)]">
                    The same file cannot be recorded twice on this matter.
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center gap-2 text-xs text-[var(--color-mute)]">
          <Bell className="h-4 w-4" aria-hidden />
          Reply reminders are tracked 7, 3, and 1 day before due date.
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {errorCount > 0 ? (
            <p
              role="alert"
              className="text-xs font-medium text-[var(--color-danger-text)]"
              data-testid="matter-notice-form-error"
            >
              {errorCount === 1
                ? "1 field needs attention before this notice can be uploaded."
                : `${errorCount} fields need attention before this notice can be uploaded.`}
            </p>
          ) : null}
          <Button type="submit" disabled={uploadMutation.isPending} data-testid="matter-notice-upload">
            {uploadMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Upload className="h-4 w-4" aria-hidden />
            )}
            {received ? "Upload received notice" : "Upload sent notice"}
          </Button>
        </div>
      </div>
    </form>
  );
}
