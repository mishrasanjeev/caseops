import { beforeEach, expect, it, vi } from "vitest";

import { listRecipientNotifications, recipientNotification, updateRecipientNotification } from "./in-app-notifications";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./client", () => ({ apiRequest: request }));
const note = { id: "note-1", docket_id: "docket-1", title: "Reminder", body: "Exact stored text",
  status: "unread", created_at: "2026-10-17T04:00:00Z", read_at: null };
beforeEach(() => { vi.clearAllMocks(); });

it("retains the full receipt contract and bounded page cursor", async () => {
  request.mockResolvedValue({ items: [note], next_cursor: "next-id" });
  expect(await listRecipientNotifications({ docketId: "docket-1", dismissed: true, cursor: "start-id" }))
    .toEqual({ items: [note], next_cursor: "next-id" });
  expect(request).toHaveBeenCalledExactlyOnceWith("/api/in-app-notifications?docket_id=docket-1&dismissed=true&cursor=start-id");
});

it("passes recipient state concurrency without client retries or receipt rewrites", async () => {
  request.mockResolvedValue({ ...note, status: "dismissed" });
  expect((await updateRecipientNotification({ docketId: "docket-1", notificationId: "note-1", expectedStatus: "unread", status: "dismissed" })).status).toBe("dismissed");
  expect(request).toHaveBeenCalledExactlyOnceWith("/api/in-app-notifications/note-1?docket_id=docket-1", {
    method: "PATCH", body: { expected_status: "unread", status: "dismissed" },
  });
});

it.each(["deleted", "queued", null])("rejects unsupported receipt state %s", (status) => {
  expect(recipientNotification.safeParse({ ...note, status }).success).toBe(false);
});

it("propagates rejection rather than substituting a successful update", async () => {
  request.mockRejectedValue(new Error("Permission revoked"));
  await expect(updateRecipientNotification({ docketId: "docket-1", notificationId: "note-1", expectedStatus: "unread", status: "dismissed" })).rejects.toThrow("Permission revoked");
  expect(request).toHaveBeenCalledTimes(1);
});
