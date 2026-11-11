import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { preview } = vi.hoisted(() => ({ preview: vi.fn() }));
vi.mock("@/lib/api/communications-email", () => ({ previewMatterEmail: preview }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { ComposeEmailForm } from "./ComposeEmailForm";

beforeEach(() => { preview.mockReset(); });
const result = { subject: "Update", body: "Reviewed message", missing_variables: [], invalid_placeholders: [], resolved_variables: {} };

function setup() {
  const submit = vi.fn();
  render(<ComposeEmailForm matterId="matter" templates={[]} loading={false} templateError={null} submitting={false} onSubmit={submit} />);
  fireEvent.change(screen.getByLabelText("Recipient email"), { target: { value: "client@example.com" } });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Update" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Reviewed message" } });
  return submit;
}

it("requires a current preview and invalidates it after every message edit", async () => {
  preview.mockResolvedValue(result);
  const submit = setup();
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-submit")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Changed message" } });
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  fireEvent.click(screen.getByTestId("comm-send-submit"));
  expect(submit).not.toHaveBeenCalled();
});

it("keeps missing and persisted legacy placeholders behind the send guard", async () => {
  preview.mockResolvedValue({ ...result, body: "Hi {[client_name]}", missing_variables: ["hearing_date"], invalid_placeholders: ["Malformed or nested placeholder"] });
  const submit = setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  expect(await screen.findByRole("alert")).toHaveTextContent("hearing_date");
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  expect(submit).not.toHaveBeenCalled();
});

it("ignores an old preview response after the operator edits the message", async () => {
  let finish!: (value: typeof result) => void;
  preview.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "New subject" } });
  finish(result);
  await waitFor(() => expect(screen.getByTestId("comm-send-preview")).toBeEnabled());
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  expect(screen.queryByTestId("comm-send-preview-result")).not.toBeInTheDocument();
});

it("passes the explicit manual message through the existing delivery owner", async () => {
  preview.mockResolvedValue(result);
  const submit = setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("comm-send-submit"));
  expect(submit).toHaveBeenCalledWith({ template_id: null, subject: "Update", body: "Reviewed message", variables: {}, recipient_email: "client@example.com", recipient_name: null });
});

it("does not treat a preview failure as a valid empty result", async () => {
  preview.mockRejectedValue(new Error("Preview unavailable"));
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Preview unavailable");
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});
