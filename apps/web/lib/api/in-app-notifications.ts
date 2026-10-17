import { z } from "zod";

import { apiRequest } from "./client";

export const notificationState = z.enum(["unread", "read", "dismissed"]);
export const recipientNotification = z.object({
  id: z.string(), docket_id: z.string(), title: z.string(), body: z.string().nullable(),
  status: notificationState, created_at: z.string(), read_at: z.string().nullable(),
});
const notificationPage = z.object({
  items: z.array(recipientNotification), next_cursor: z.string().nullable(),
});
export type RecipientNotification = z.infer<typeof recipientNotification>;

export async function listRecipientNotifications(input: {
  docketId: string; dismissed: boolean; cursor?: string | null;
}) {
  const query = new URLSearchParams({ docket_id: input.docketId, dismissed: String(input.dismissed) });
  if (input.cursor) query.set("cursor", input.cursor);
  return notificationPage.parse(await apiRequest(`/api/in-app-notifications?${query}`));
}

export async function updateRecipientNotification(input: {
  docketId: string; notificationId: string; expectedStatus: RecipientNotification["status"];
  status: RecipientNotification["status"];
}) {
  const query = new URLSearchParams({ docket_id: input.docketId });
  return recipientNotification.parse(await apiRequest(`/api/in-app-notifications/${input.notificationId}?${query}`, {
    method: "PATCH", body: { expected_status: input.expectedStatus, status: input.status },
  }));
}
