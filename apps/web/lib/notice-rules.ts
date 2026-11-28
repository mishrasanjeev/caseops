/**
 * Client mirror of the API notice rules (apps/api/.../services/notice_rules.py).
 *
 * The API is the authority: it refuses the same cases with the same messages,
 * field by field, and `noticeErrorsFromApi` anchors any server refusal to the
 * input it names. These checks only stop the browser from sending a notice
 * the API would refuse, so the user sees every problem inline at once.
 */
import { ApiError, apiValidationIssues } from "@/lib/api/config";
import { todayLocalDateInput } from "@/lib/dates";

export type NoticeRuleDirection = "received" | "sent";

/** Canonical field names, shared with the API's `errors[].loc`. */
export type NoticeFieldKey =
  | "subject"
  | "type"
  | "received_on"
  | "sent_on"
  | "reply_due_on"
  | "reply_sent_on"
  | "amount_minor"
  | "dispute_amount_minor"
  | "recovered_amount_minor"
  | "currency"
  | "file";

export type NoticeFieldErrors = Partial<Record<NoticeFieldKey, string>>;

export type NoticeRuleInput = {
  direction: NoticeRuleDirection;
  subject: string;
  noticeType: string;
  receivedOn: string;
  sentOn: string;
  replyRequired: boolean;
  replySent: boolean;
  replyDueOn: string;
  replySentOn: string;
  amount: string;
  disputeAmount: string;
  recoveredAmount: string;
  currency: string;
  /** Date inputs whose typed text is not a real date (`validity.badInput`). */
  unparsableDates?: ReadonlySet<NoticeFieldKey>;
};

export type NoticeFilePolicy = {
  allowed_upload_extensions: string[];
  max_upload_size_bytes: number;
};

export const NOTICE_MESSAGES = {
  receivedOnRequired: "Enter the date of receipt.",
  receivedOnFuture: "Date of receipt cannot be in the future.",
  sentOnRequired: "Enter the notice sent date.",
  sentOnFuture: "Notice sent date cannot be in the future.",
  invalidDate: "Enter a real calendar date.",
  dateRange: "Enter a date between 1900 and 2100.",
  subjectRequired: "Enter the notice subject.",
  typeRequired: "Enter the type of notice.",
  replyDueRequired: "Enter the reply due date, or clear Reply required.",
  replyDueBeforeReceipt: "Reply due date cannot be earlier than the date of receipt.",
  replySentBeforeReceipt: "Reply sent date cannot be earlier than the date of receipt.",
  replySentFuture: "Reply sent date cannot be in the future.",
  recoveredAboveDispute: "Recovered amount cannot exceed the dispute amount.",
  currency: "Enter a three-letter currency code, for example INR.",
  fileRequired: "Attach the notice document.",
  fileEmpty: "The selected file is empty.",
} as const;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** The API's NOTICE_MIN_DATE / NOTICE_MAX_DATE; also the date pickers' min/max. */
export const NOTICE_MIN_DATE = "1900-01-01";
export const NOTICE_MAX_DATE = "2100-12-31";

/** A browser completes a half-typed year as 0001 or 0020; that is not a notice date. */
function outOfRange(value: string): boolean {
  return value < NOTICE_MIN_DATE || value > NOTICE_MAX_DATE;
}

/** True for a real `YYYY-MM-DD` calendar date (rejects 2026-02-30). */
export function isRealIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(0);
  // Date.UTC maps years 0-99 to 1900-1999; setUTCFullYear keeps 0020 as 0020.
  parsed.setUTCFullYear(year, month - 1, day);
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

const AMOUNT = /^\d+(\.\d{1,2})?$/;

export type AmountParse =
  | { ok: true; minor: number | null }
  | { ok: false; message: string };

/**
 * Major units as typed ("1,25,000.50") to integer minor units, exactly.
 * Negative, non-numeric, more than two decimals and unsafe magnitudes are
 * refused with a message instead of silently becoming "no amount".
 */
export function parseAmountMinor(raw: string, label: string): AmountParse {
  const value = raw.trim().replace(/,/g, "");
  if (!value) return { ok: true, minor: null };
  if (value.startsWith("-")) return { ok: false, message: `${label} cannot be negative.` };
  if (!AMOUNT.test(value)) {
    return /^\d+\.\d{3,}$/.test(value)
      ? { ok: false, message: `${label} can have at most two decimal places.` }
      : { ok: false, message: `Enter ${label.toLowerCase()} as a number, for example 12500.50.` };
  }
  const [whole, fraction = ""] = value.split(".");
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(minor)) {
    return { ok: false, message: `${label} is too large.` };
  }
  return { ok: true, minor };
}

/** Every rule the API enforces on a primary notice, as inline field errors. */
export function validateNoticeDraft(
  input: NoticeRuleInput,
  today: string = todayLocalDateInput(),
): NoticeFieldErrors {
  const errors: NoticeFieldErrors = {};
  const received = input.direction === "received";
  const bad = input.unparsableDates ?? new Set<NoticeFieldKey>();

  const checkDate = (
    key: NoticeFieldKey,
    value: string,
    required: string,
    future: string,
  ): string | null => {
    if (bad.has(key)) {
      errors[key] = NOTICE_MESSAGES.invalidDate;
      return null;
    }
    if (!value) {
      errors[key] = required;
      return null;
    }
    if (!isRealIsoDate(value)) {
      errors[key] = NOTICE_MESSAGES.invalidDate;
      return null;
    }
    if (outOfRange(value)) {
      errors[key] = NOTICE_MESSAGES.dateRange;
      return null;
    }
    if (value > today) {
      errors[key] = future;
      return null;
    }
    return value;
  };

  const receivedOn = received
    ? checkDate(
        "received_on",
        input.receivedOn,
        NOTICE_MESSAGES.receivedOnRequired,
        NOTICE_MESSAGES.receivedOnFuture,
      )
    : null;
  if (!received) {
    checkDate("sent_on", input.sentOn, NOTICE_MESSAGES.sentOnRequired, NOTICE_MESSAGES.sentOnFuture);
  }
  if (!input.subject.trim()) errors.subject = NOTICE_MESSAGES.subjectRequired;
  if (!input.noticeType.trim()) errors.type = NOTICE_MESSAGES.typeRequired;

  if (received) {
    if (bad.has("reply_due_on") || (input.replyDueOn && !isRealIsoDate(input.replyDueOn))) {
      errors.reply_due_on = NOTICE_MESSAGES.invalidDate;
    } else if (input.replyDueOn && outOfRange(input.replyDueOn)) {
      errors.reply_due_on = NOTICE_MESSAGES.dateRange;
    } else if (input.replyRequired && !input.replySent && !input.replyDueOn) {
      errors.reply_due_on = NOTICE_MESSAGES.replyDueRequired;
    } else if (input.replyDueOn && receivedOn && input.replyDueOn < receivedOn) {
      errors.reply_due_on = NOTICE_MESSAGES.replyDueBeforeReceipt;
    }
    if (input.replySent) {
      if (bad.has("reply_sent_on") || (input.replySentOn && !isRealIsoDate(input.replySentOn))) {
        errors.reply_sent_on = NOTICE_MESSAGES.invalidDate;
      } else if (input.replySentOn && outOfRange(input.replySentOn)) {
        errors.reply_sent_on = NOTICE_MESSAGES.dateRange;
      } else if (input.replySentOn && receivedOn && input.replySentOn < receivedOn) {
        errors.reply_sent_on = NOTICE_MESSAGES.replySentBeforeReceipt;
      } else if (input.replySentOn && input.replySentOn > today) {
        errors.reply_sent_on = NOTICE_MESSAGES.replySentFuture;
      }
    }
    const amount = parseAmountMinor(input.amount, "Amount");
    if (!amount.ok) errors.amount_minor = amount.message;
  } else {
    const dispute = parseAmountMinor(input.disputeAmount, "Dispute amount");
    const recovered = parseAmountMinor(input.recoveredAmount, "Recovered amount");
    if (!dispute.ok) errors.dispute_amount_minor = dispute.message;
    if (!recovered.ok) errors.recovered_amount_minor = recovered.message;
    if (
      dispute.ok &&
      recovered.ok &&
      dispute.minor !== null &&
      recovered.minor !== null &&
      recovered.minor > dispute.minor
    ) {
      errors.recovered_amount_minor = NOTICE_MESSAGES.recoveredAboveDispute;
    }
  }
  if (!/^[A-Za-z]{3}$/.test(input.currency.trim())) errors.currency = NOTICE_MESSAGES.currency;
  return errors;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

export function formatUploadLimit(bytes: number): string {
  const [size, unit] = bytes >= 1024 * 1024 ? [bytes / (1024 * 1024), "MB"] : [bytes / 1024, "KB"];
  return `${Number.isInteger(size) ? size : size.toFixed(1)} ${unit}`;
}

/** "PDF, ... up to 25 MB." from the API policy, or null when it has none. */
export function uploadPolicyHint(policy: NoticeFilePolicy | null | undefined): string | null {
  const extensions = policy?.allowed_upload_extensions;
  if (!policy || !extensions?.length) return null;
  return `${extensions.join(", ")} up to ${formatUploadLimit(policy.max_upload_size_bytes)}.`;
}

/** The `accept` attribute for a picker, from the API's own allow-list. */
export function acceptAttribute(policy: NoticeFilePolicy | null | undefined): string | undefined {
  // An API that predates the exposed allow-list (deploy skew) sends none.
  const extensions = policy?.allowed_upload_extensions;
  return extensions?.length ? extensions.join(",") : undefined;
}

/**
 * The API's file rules for one selected file. With no policy loaded yet only
 * presence is checked; the API still refuses an unsupported or oversize file.
 */
export function validateNoticeFile(
  file: File | null,
  policy: NoticeFilePolicy | null | undefined,
  { required = true }: { required?: boolean } = {},
): string | null {
  if (!file) return required ? NOTICE_MESSAGES.fileRequired : null;
  if (file.size === 0) return NOTICE_MESSAGES.fileEmpty;
  if (!policy) return null;
  const extension = extensionOf(file.name);
  const extensions = policy.allowed_upload_extensions ?? [];
  if (extensions.length > 0 && !extensions.includes(extension)) {
    const allowed = extensions.join(", ");
    return `${extension ? `${extension} files are` : "This file type is"} not supported. Upload one of: ${allowed}.`;
  }
  if (policy.max_upload_size_bytes > 0 && file.size > policy.max_upload_size_bytes) {
    return `The file is larger than the ${formatUploadLimit(policy.max_upload_size_bytes)} upload limit.`;
  }
  return null;
}

const FIELD_KEYS = new Set<NoticeFieldKey>([
  "subject",
  "type",
  "received_on",
  "sent_on",
  "reply_due_on",
  "reply_sent_on",
  "amount_minor",
  "dispute_amount_minor",
  "recovered_amount_minor",
  "currency",
  "file",
]);

/**
 * A 422 from either notice writer as inline field errors. The matter upload
 * form prefixes its fields with `notice_`; the register does not.
 */
export function noticeErrorsFromApi(error: unknown): NoticeFieldErrors {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const errors: NoticeFieldErrors = {};
  for (const issue of apiValidationIssues(error.data)) {
    const last = issue.loc[issue.loc.length - 1];
    if (typeof last !== "string") continue;
    const key = (last.startsWith("notice_") ? last.slice("notice_".length) : last) as NoticeFieldKey;
    if (FIELD_KEYS.has(key) && !errors[key]) {
      errors[key] = issue.msg.replace(/^Value error, /, "");
    }
  }
  return errors;
}

export type NoticeDuplicate = {
  kind: "same_file" | "same_details";
  overrideAllowed: boolean;
  message: string;
  existing: {
    id: string;
    subject: string | null;
    direction: string;
    notice_date: string | null;
    filename: string | null;
    /** Which store holds it: a register row or a matter attachment. */
    source_kind?: "standalone" | "legacy_attachment" | null;
    /** The matter of a `legacy_attachment` match. */
    matter_id?: string | null;
  };
};

/**
 * Where the matched notice opens. The register and a matter's Notices view
 * list both stores, so a match can be either: a register notice opens in the
 * register; a matter notice opens as that matter's document.
 */
export function noticeDuplicateHref(
  existing: NoticeDuplicate["existing"],
  currentMatterId?: string,
): string | null {
  if (existing.source_kind === "standalone") {
    return `/app/notices?notice=${encodeURIComponent(existing.id)}`;
  }
  const matterId = existing.matter_id ?? currentMatterId;
  return matterId
    ? `/app/matters/${encodeURIComponent(matterId)}/documents/${encodeURIComponent(existing.id)}/view`
    : null;
}

/** The 409 duplicate refusal both notice writers return, or null. */
export function noticeDuplicateFromApi(error: unknown): NoticeDuplicate | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const data = error.data as Record<string, unknown> | null;
  const existing = data?.existing_notice as NoticeDuplicate["existing"] | undefined;
  const kind = data?.duplicate_kind;
  if (!existing || (kind !== "same_file" && kind !== "same_details")) return null;
  return {
    kind,
    overrideAllowed: data?.override_allowed === true,
    message: error.detail,
    existing,
  };
}

/** Field keys in the order they appear on the form, for focusing the first. */
export const NOTICE_FIELD_ORDER: NoticeFieldKey[] = [
  "received_on",
  "sent_on",
  "type",
  "subject",
  "amount_minor",
  "reply_due_on",
  "reply_sent_on",
  "dispute_amount_minor",
  "recovered_amount_minor",
  "currency",
  "file",
];
