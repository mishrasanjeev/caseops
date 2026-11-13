import { beforeEach, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./client", () => ({ apiRequest: request }));

import { deliverMatterEmail, previewMatterEmail } from "./communications-email";
import { sendMatterEmail } from "./endpoints";

beforeEach(() => { request.mockReset(); });

const message = {
  template_id: null, subject: "Reviewed", body: "Reviewed message", variables: {},
  recipient_email: "client@example.com", recipient_name: "Reviewed recipient",
};
const row = {
  id: "communication", company_id: "tenant", matter_id: "matter", client_id: null,
  direction: "outbound", channel: "email", subject: message.subject, body: message.body,
  recipient_name: message.recipient_name, recipient_email: message.recipient_email, recipient_phone: null,
  status: "sent", occurred_at: "2026-11-11T00:00:00Z", delivered_at: null, opened_at: null,
  external_message_id: "offline", created_by_membership_id: "actor", created_at: "2026-11-11T00:00:00Z",
};

it("previews the recipient and preserves the server's signed token and expiry", async () => {
  const rendered = { subject: message.subject, body: message.body, missing_variables: [],
    invalid_placeholders: [], resolved_variables: {}, preview_token: "signed-preview",
    preview_expires_at: "2026-11-11T00:05:00Z" };
  request.mockResolvedValue(rendered);
  expect(await previewMatterEmail("matter", message)).toEqual(rendered);
  expect(request).toHaveBeenCalledWith("/api/matters/matter/communications/preview-email", { method: "POST", body: message });
});

it("passes the reviewed token unchanged through the current send adapter", async () => {
  request.mockResolvedValue(row);
  await deliverMatterEmail("matter", { ...message, preview_token: "signed-preview" });
  expect(request).toHaveBeenCalledWith("/api/matters/matter/communications/send-email", {
    method: "POST", body: { ...message, preview_token: "signed-preview" },
  });
});

it("does not leave a tokenless legacy send adapter", async () => {
  request.mockResolvedValue(row);
  await sendMatterEmail({ matterId: "matter", templateId: "template", recipient_email: message.recipient_email,
    recipient_name: message.recipient_name, variables: {}, preview_token: "signed-preview" });
  expect(request).toHaveBeenCalledWith("/api/matters/matter/communications/send-email", {
    method: "POST", body: { template_id: "template", recipient_email: message.recipient_email,
      recipient_name: message.recipient_name, variables: {}, client_id: undefined, preview_token: "signed-preview" },
  });
});
