import { z } from "zod";

import { apiRequest } from "./client";
import { communicationRecord, emailTemplateListResponse } from "./schemas";

export type MatterEmailMessage = {
  template_id: string | null;
  subject?: string;
  body?: string;
  variables: Record<string, string>;
  recipient_email: string;
  recipient_name: string | null;
};

const previewSchema = z.object({
  subject: z.string(), body: z.string(),
  missing_variables: z.array(z.string()),
  invalid_placeholders: z.array(z.string()),
  resolved_variables: z.record(z.string(), z.string()),
  preview_token: z.string().nullable(),
  preview_expires_at: z.string().nullable(),
});
export type MatterEmailPreview = z.infer<typeof previewSchema>;

export async function listMatterEmailTemplates(matterId: string) {
  return emailTemplateListResponse.parse(await apiRequest<unknown>(
    `/api/matters/${matterId}/communications/email-templates`,
  ));
}

export async function previewMatterEmail(matterId: string, message: MatterEmailMessage) {
  return previewSchema.parse(await apiRequest<unknown>(
    `/api/matters/${matterId}/communications/preview-email`,
    { method: "POST", body: message },
  ));
}

export async function deliverMatterEmail(matterId: string, message: MatterEmailMessage & {
  preview_token: string;
}) {
  return communicationRecord.parse(await apiRequest<unknown>(
    `/api/matters/${matterId}/communications/send-email`,
    { method: "POST", body: message },
  ));
}
