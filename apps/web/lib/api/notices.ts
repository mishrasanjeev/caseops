import { apiBlobRequest, apiRequest } from "@/lib/api/client";

export type NoticeDirection = "received" | "sent";
export type NoticeSourceKind = "standalone" | "legacy_attachment";

export type NoticeMatterLink = {
  matter_id: string;
  matter_code: string;
  matter_title: string;
};

export type NoticeOwnerOption = {
  membership_id: string;
  name: string;
  email: string;
};

export type NoticeRecord = {
  id: string;
  direction: NoticeDirection;
  source_kind: NoticeSourceKind;
  read_only: boolean;
  subject: string;
  type: string | null;
  mode: string | null;
  authority: string | null;
  received_from: string | null;
  summary: string | null;
  response: string | null;
  remarks: string | null;
  internal_spoc: string | null;
  internal_remarks: string | null;
  status: string;
  department: string | null;
  owner_membership_id: string | null;
  owner_name: string | null;
  owner_email: string | null;
  received_on: string | null;
  sent_on: string | null;
  reply_due_on: string | null;
  reply_required: boolean;
  reply_sent: boolean;
  reply_sent_on: string | null;
  amount_minor: number | null;
  dispute_amount_minor: number | null;
  recovered_amount_minor: number | null;
  currency: string;
  counsel_engaged: string | null;
  matter_links: NoticeMatterLink[];
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
};

export type NoticeListResponse = {
  notices: NoticeRecord[];
  total: number;
  next_cursor: string | null;
};

export type NoticeListParams = {
  limit?: number;
  cursor?: string | null;
  query?: string;
  direction?: NoticeDirection;
  status?: string;
  matter_id?: string;
  owner_membership_id?: string;
  due_from?: string;
  due_to?: string;
};

export type CreateNoticeInput = {
  direction: NoticeDirection;
  subject: string;
  type?: string | null;
  mode?: string | null;
  authority?: string | null;
  received_from?: string | null;
  summary?: string | null;
  response?: string | null;
  remarks?: string | null;
  status?: string;
  department?: string | null;
  owner_membership_id?: string | null;
  received_on?: string | null;
  sent_on?: string | null;
  reply_due_on?: string | null;
  reply_required?: boolean;
  reply_sent?: boolean;
  reply_sent_on?: string | null;
  amount_minor?: number | null;
  dispute_amount_minor?: number | null;
  recovered_amount_minor?: number | null;
  currency?: string;
  counsel_engaged?: string | null;
  internal_spoc?: string | null;
  internal_remarks?: string | null;
  matter_ids: string[];
};

export type UpdateNoticeFields = Partial<
  Pick<
    CreateNoticeInput,
    | "direction"
    | "subject"
    | "type"
    | "mode"
    | "authority"
    | "received_from"
    | "summary"
    | "response"
    | "remarks"
    | "status"
    | "department"
    | "owner_membership_id"
    | "received_on"
    | "sent_on"
    | "reply_due_on"
    | "reply_required"
    | "reply_sent"
    | "reply_sent_on"
    | "amount_minor"
    | "dispute_amount_minor"
    | "recovered_amount_minor"
    | "currency"
    | "counsel_engaged"
    | "internal_spoc"
    | "internal_remarks"
    | "matter_ids"
  >
>;

/**
 * Standalone notices use optimistic concurrency just like matter lifecycle
 * changes.  Every browser PATCH must identify the version the user edited so
 * a second tab cannot silently overwrite newer metadata or matter links.
 */
export type UpdateNoticeInput = UpdateNoticeFields & {
  expected_updated_at: string;
};

export async function listNotices(
  params: NoticeListParams = {},
): Promise<NoticeListResponse> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  return apiRequest<NoticeListResponse>(
    `/api/notices/${query.size > 0 ? `?${query.toString()}` : ""}`,
  );
}

export async function listNoticeOwners(): Promise<NoticeOwnerOption[]> {
  return apiRequest<NoticeOwnerOption[]>("/api/notices/owners");
}

export async function createNotice(input: CreateNoticeInput): Promise<NoticeRecord> {
  return apiRequest<NoticeRecord>("/api/notices/", {
    method: "POST",
    body: input,
  });
}

export async function getNotice(noticeId: string): Promise<NoticeRecord> {
  return apiRequest<NoticeRecord>(
    `/api/notices/${encodeURIComponent(noticeId)}`,
  );
}

export async function updateNotice(
  noticeId: string,
  input: UpdateNoticeInput,
): Promise<NoticeRecord> {
  return apiRequest<NoticeRecord>(`/api/notices/${encodeURIComponent(noticeId)}`, {
    method: "PATCH",
    body: input,
  });
}

export async function uploadNoticeFile(
  noticeId: string,
  file: File,
  expectedUpdatedAt: string,
): Promise<NoticeRecord> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_updated_at", expectedUpdatedAt);
  return apiRequest<NoticeRecord>(
    `/api/notices/${encodeURIComponent(noticeId)}/file`,
    {
      method: "POST",
      body: form,
    },
  );
}

function downloadName(disposition: string | null, fallback: string): string {
  const utf8 = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8) {
    try {
      return decodeURIComponent(utf8);
    } catch {
      return utf8;
    }
  }
  return disposition?.match(/filename="([^"]+)"/i)?.[1] ?? fallback;
}

export async function downloadNoticeFile(
  noticeId: string,
  fallbackName = "notice-document",
): Promise<void> {
  const response = await apiBlobRequest(
    `/api/notices/${encodeURIComponent(noticeId)}/download`,
  );

  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = downloadName(
    response.headers.get("content-disposition"),
    fallbackName,
  );
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 30_000);
}
