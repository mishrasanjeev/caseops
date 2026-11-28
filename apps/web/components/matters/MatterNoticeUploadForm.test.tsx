import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { todayLocalDateInput } from "@/lib/dates";

const { uploadMock, toastSuccess, toastError } = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({ uploadMatterAttachment: uploadMock }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

import { MatterNoticeUploadForm } from "@/components/matters/MatterNoticeUploadForm";

// The API's own allow-list and cap, as the workspace returns them.
const POLICY = {
  allowed_upload_extensions: [".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png", ".txt"],
  max_upload_size_bytes: 1024,
};

function shiftDays(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return todayLocalDateInput(value);
}

const RECEIVED_ON = shiftDays(-10);

function renderForm(direction: "received" | "sent", onUploaded = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MatterNoticeUploadForm
        matterId="m1"
        direction={direction}
        filePolicy={POLICY}
        onUploaded={onUploaded}
      />
    </QueryClientProvider>,
  );
  return { page: within(view.container), onUploaded };
}

async function fill(user: UserEvent, field: HTMLElement, value: string) {
  await user.clear(field);
  if (value) {
    await user.click(field);
    await user.paste(value);
  }
}

function noticeFile(name = "notice.pdf", body = "%PDF-1.4 notice"): File {
  return new File([body], name, { type: "application/pdf" });
}

type Page = ReturnType<typeof within>;

async function fillValidReceived(user: UserEvent, page: Page) {
  await fill(user, page.getByTestId("matter-notice-received-on"), RECEIVED_ON);
  await fill(user, page.getByTestId("matter-notice-type"), "Legal demand");
  await fill(user, page.getByTestId("matter-notice-subject"), "Demand notice");
  await fill(user, page.getByTestId("matter-notice-reply-due-on"), shiftDays(5));
  await user.upload(page.getByTestId("matter-notice-file-input"), noticeFile());
}

async function fillValidSent(user: UserEvent, page: Page) {
  await fill(user, page.getByTestId("matter-notice-sent-on"), RECEIVED_ON);
  await fill(user, page.getByTestId("matter-notice-type"), "Recovery notice");
  await fill(user, page.getByTestId("matter-notice-subject"), "Recovery notice");
  await fill(user, page.getByTestId("matter-notice-dispute-amount"), "15000");
  await fill(user, page.getByTestId("matter-notice-recovered-amount"), "2500");
  await user.upload(page.getByTestId("matter-notice-file-input"), noticeFile());
}

/** The tester's complaint, as an assertion: a specific inline message, an
 * accessible link from the input to it, focus on it, and nothing sent. */
async function expectRefused(
  user: UserEvent,
  page: Page,
  inputTestId: string,
  message: string,
) {
  await user.click(page.getByTestId("matter-notice-upload"));
  const input = page.getByTestId(inputTestId);
  await waitFor(() => expect(input).toHaveAttribute("aria-invalid", "true"));
  const describedBy = input.getAttribute("aria-describedby") ?? "";
  const errorId = describedBy.split(" ").find((id: string) => id.endsWith("-error"));
  expect(errorId).toBeTruthy();
  expect(document.getElementById(errorId as string)).toHaveTextContent(message);
  expect(page.getByTestId("matter-notice-form-error")).toBeInTheDocument();
  expect(uploadMock).not.toHaveBeenCalled();
}

describe("MatterNoticeUploadForm", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("refuses an empty Notice Received submission with every required message and focuses the first", async () => {
    const user = userEvent.setup();
    const { page } = renderForm("received");

    await user.click(page.getByTestId("matter-notice-upload"));

    await waitFor(() => expect(page.getByTestId("matter-notice-received-on")).toHaveFocus());
    expect(page.getByTestId("notice-received-on-error")).toHaveTextContent("Enter the date of receipt.");
    expect(page.getByTestId("notice-subject-error")).toHaveTextContent("Enter the notice subject.");
    expect(page.getByTestId("notice-type-error")).toHaveTextContent("Enter the type of notice.");
    expect(page.getByTestId("notice-reply-due-on-error")).toHaveTextContent(
      "Enter the reply due date, or clear Reply required.",
    );
    expect(page.getByTestId("notice-file-error")).toHaveTextContent("Attach the notice document.");
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it.each([
    ["no date of receipt", "matter-notice-received-on", "", "Enter the date of receipt."],
    ["no subject", "matter-notice-subject", "", "Enter the notice subject."],
    ["future receipt", "matter-notice-received-on", shiftDays(1), "Date of receipt cannot be in the future."],
    ["year completed to 0020 by the browser", "matter-notice-received-on", "0020-03-02", "Enter a date between 1900 and 2100."],
    ["negative amount", "matter-notice-amount", "-500", "Amount cannot be negative."],
    ["non-numeric amount", "matter-notice-amount", "12,5x", "Enter amount as a number"],
    ["three decimals", "matter-notice-amount", "10.555", "Amount can have at most two decimal places."],
    ["reply required, no due date", "matter-notice-reply-due-on", "", "Enter the reply due date, or clear Reply required."],
    ["due before receipt", "matter-notice-reply-due-on", shiftDays(-11), "Reply due date cannot be earlier than the date of receipt."],
  ])("Notice Received: %s", async (_case, testId, value, message) => {
    const user = userEvent.setup();
    const { page } = renderForm("received");
    await fillValidReceived(user, page);
    await fill(user, page.getByTestId(testId), value);

    await expectRefused(user, page, testId, message);
  });

  it("Notice Received: an unparsable typed date is refused as invalid", async () => {
    const user = userEvent.setup();
    const { page } = renderForm("received");
    await fillValidReceived(user, page);
    const input = page.getByTestId("matter-notice-received-on") as HTMLInputElement;
    // A browser reports a half-typed or impossible date as badInput with "".
    Object.defineProperty(input, "validity", { value: { badInput: true }, configurable: true });
    await fill(user, input, "");

    await expectRefused(user, page, "matter-notice-received-on", "Enter a real calendar date.");
  });

  it("Notice Received: clearing Reply required removes the due-date requirement", async () => {
    uploadMock.mockResolvedValue({ id: "n1" });
    const user = userEvent.setup();
    const { page } = renderForm("received");
    await fillValidReceived(user, page);
    await fill(user, page.getByTestId("matter-notice-reply-due-on"), "");
    await user.click(page.getByTestId("matter-notice-reply-required"));

    await user.click(page.getByTestId("matter-notice-upload"));

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    expect(uploadMock.mock.calls[0][0]).toMatchObject({
      noticeReplyRequired: false,
      noticeReplyDueOn: null,
      noticeReceivedOn: RECEIVED_ON,
      allowDuplicate: false,
    });
  });

  it.each([
    ["no sent date", "matter-notice-sent-on", "", "Enter the notice sent date."],
    ["no subject", "matter-notice-subject", "", "Enter the notice subject."],
    ["empty type of notice", "matter-notice-type", "", "Enter the type of notice."],
    ["future sent date", "matter-notice-sent-on", shiftDays(1), "Notice sent date cannot be in the future."],
    ["year completed to 0001 by the browser", "matter-notice-sent-on", "0001-03-02", "Enter a date between 1900 and 2100."],
    ["negative dispute amount", "matter-notice-dispute-amount", "-1", "Dispute amount cannot be negative."],
    ["negative recovered amount", "matter-notice-recovered-amount", "-1", "Recovered amount cannot be negative."],
    ["recovered above dispute", "matter-notice-recovered-amount", "15000.01", "Recovered amount cannot exceed the dispute amount."],
  ])("Notice Sent: %s", async (_case, testId, value, message) => {
    const user = userEvent.setup();
    const { page } = renderForm("sent");
    await fillValidSent(user, page);
    await fill(user, page.getByTestId(testId), value);

    await expectRefused(user, page, testId, message);
  });

  it("Notice Sent: no document, unsupported format and oversize file are refused before upload", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { page } = renderForm("sent");
    await fillValidSent(user, page);
    const picker = page.getByTestId("matter-notice-file-input");
    expect(picker).toHaveAttribute("accept", POLICY.allowed_upload_extensions.join(","));

    await user.upload(picker, []);
    await expectRefused(user, page, "matter-notice-file-input", "Attach the notice document.");

    await user.upload(picker, new File(["MZ"], "notice.exe", { type: "application/octet-stream" }));
    await expectRefused(user, page, "matter-notice-file-input", ".exe files are not supported.");

    await user.upload(picker, noticeFile("big.pdf", "x".repeat(POLICY.max_upload_size_bytes + 1)));
    await expectRefused(user, page, "matter-notice-file-input", "larger than the 1 KB upload limit");
  });

  it("Notice Sent: a complete notice uploads exact minor units", async () => {
    uploadMock.mockResolvedValue({ id: "s1" });
    const user = userEvent.setup();
    const { page, onUploaded } = renderForm("sent");
    await fillValidSent(user, page);
    await fill(user, page.getByTestId("matter-notice-dispute-amount"), "1,25,000.10");
    await fill(user, page.getByTestId("matter-notice-recovered-amount"), "0.10");

    await user.click(page.getByTestId("matter-notice-upload"));

    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(uploadMock.mock.calls[0][0]).toMatchObject({
      noticeDirection: "sent",
      noticeSentOn: RECEIVED_ON,
      noticeDisputeAmountMinor: 12500010,
      noticeRecoveredAmountMinor: 10,
      noticeReplyRequired: false,
    });
  });

  it("a same-details duplicate links to the existing notice and offers an audited upload anyway", async () => {
    uploadMock
      .mockRejectedValueOnce(
        new ApiError(409, "A notice with the same direction, date, subject and counterparty already exists.", {
          duplicate_kind: "same_details",
          override_allowed: true,
          existing_notice: {
            id: "existing-1",
            subject: "Recovery notice",
            direction: "sent",
            notice_date: RECEIVED_ON,
            filename: "first.pdf",
          },
        }),
      )
      .mockResolvedValueOnce({ id: "s2" });
    const user = userEvent.setup();
    const { page } = renderForm("sent");
    await fillValidSent(user, page);

    await user.click(page.getByTestId("matter-notice-upload"));

    const panel = await page.findByTestId("matter-notice-duplicate");
    expect(panel).toHaveAttribute("role", "alert");
    expect(within(panel).getByTestId("matter-notice-duplicate-link")).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/existing-1/view",
    );
    await user.click(within(panel).getByTestId("matter-notice-upload-anyway"));
    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(2));
    expect(uploadMock.mock.calls[0][0].allowDuplicate).toBe(false);
    expect(uploadMock.mock.calls[1][0].allowDuplicate).toBe(true);
  });

  it("a match with a register notice linked to the matter opens it in the register", async () => {
    uploadMock.mockRejectedValueOnce(
      new ApiError(409, "A notice with the same direction, date, subject and counterparty already exists.", {
        duplicate_kind: "same_details",
        override_allowed: true,
        existing_notice: {
          id: "register-7",
          subject: "Recovery notice",
          direction: "sent",
          notice_date: RECEIVED_ON,
          filename: null,
          source_kind: "standalone",
          matter_id: null,
        },
      }),
    );
    const user = userEvent.setup();
    const { page } = renderForm("sent");
    await fillValidSent(user, page);

    await user.click(page.getByTestId("matter-notice-upload"));

    const link = within(await page.findByTestId("matter-notice-duplicate")).getByTestId(
      "matter-notice-duplicate-link",
    );
    expect(link).toHaveAttribute("href", "/app/notices?notice=register-7");
    expect(link).toHaveTextContent("Open the existing notice in the register");
  });

  it("a same-file duplicate cannot be overridden", async () => {
    uploadMock.mockRejectedValueOnce(
      new ApiError(409, "This file is already attached to this matter as a notice.", {
        duplicate_kind: "same_file",
        override_allowed: false,
        existing_notice: { id: "e2", subject: "Old", direction: "sent", notice_date: null, filename: "a.pdf" },
      }),
    );
    const user = userEvent.setup();
    const { page } = renderForm("sent");
    await fillValidSent(user, page);

    await user.click(page.getByTestId("matter-notice-upload"));

    const panel = await page.findByTestId("matter-notice-duplicate");
    expect(panel).toHaveTextContent("This file is already attached to this matter as a notice.");
    expect(within(panel).queryByTestId("matter-notice-upload-anyway")).toBeNull();
  });

  it("anchors an API 422 to the field it names", async () => {
    uploadMock.mockRejectedValueOnce(
      new ApiError(422, "Date of receipt cannot be in the future.", {
        errors: [
          {
            loc: ["body", "notice_received_on"],
            msg: "Date of receipt cannot be in the future.",
            type: "notice_received_on_in_future",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    const { page } = renderForm("received");
    await fillValidReceived(user, page);

    await user.click(page.getByTestId("matter-notice-upload"));

    await waitFor(() =>
      expect(page.getByTestId("notice-received-on-error")).toHaveTextContent(
        "Date of receipt cannot be in the future.",
      ),
    );
    expect(page.getByTestId("matter-notice-received-on")).toHaveFocus();
    expect(toastError).not.toHaveBeenCalled();
  });
});
