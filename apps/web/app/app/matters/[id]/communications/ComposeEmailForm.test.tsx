import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { preview } = vi.hoisted(() => ({ preview: vi.fn() }));
vi.mock("@/lib/api/communications-email", () => ({ previewMatterEmail: preview }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { ComposeEmailForm } from "./ComposeEmailForm";

beforeEach(() => { preview.mockReset(); });
const result = {
  subject: "Update", body: "Reviewed message", missing_variables: [], invalid_placeholders: [], resolved_variables: {},
  preview_token: "server-issued-token", preview_expires_at: new Date(Date.now() + 300_000).toISOString(),
};

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
  expect(submit).toHaveBeenCalledWith({ template_id: null, subject: "Update", body: "Reviewed message", variables: {}, recipient_email: "client@example.com", recipient_name: null, preview_token: "server-issued-token" });
});

it("does not treat a preview failure as a valid empty result", async () => {
  preview.mockRejectedValue(new Error("Preview unavailable"));
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Preview unavailable");
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});

it("does not revive a preview after editing away and back", async () => {
  preview.mockResolvedValue(result);
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-submit")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Changed message" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Reviewed message" } });
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});

it("does not offer an unfillable custom field for an undeclared manual token", () => {
  setup();
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Update {{reference}}" } });
  expect(screen.queryByTestId("comm-send-var-reference")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("reference");
  expect(screen.getByTestId("comm-send-preview")).toBeDisabled();
});

it("invalidates recipient edits even after returning to the original address", async () => {
  preview.mockResolvedValue(result);
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-submit")).toBeEnabled());
  expect(preview).toHaveBeenLastCalledWith("matter", expect.objectContaining({ recipient_email: "client@example.com", recipient_name: null }));
  fireEvent.change(screen.getByLabelText("Recipient email"), { target: { value: "another@example.com" } });
  fireEvent.change(screen.getByLabelText("Recipient email"), { target: { value: "client@example.com" } });
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});

it("rejects an in-flight response after editing away and back", async () => {
  let finish!: (value: typeof result) => void;
  preview.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Different message" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Reviewed message" } });
  finish(result);
  await waitFor(() => expect(screen.getByTestId("comm-send-preview")).toBeEnabled());
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  expect(screen.queryByTestId("comm-send-preview-result")).not.toBeInTheDocument();
});

it("never enables delivery without a live server-issued token", async () => {
  preview.mockResolvedValue({ ...result, preview_token: null, preview_expires_at: null });
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await screen.findByTestId("comm-send-preview-result");
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});

it("does not enable an already expired preview", async () => {
  preview.mockResolvedValue({ ...result, preview_expires_at: new Date(Date.now() - 1000).toISOString() });
  setup();
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-preview")).toBeEnabled());
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
});

it("only offers declared custom variables from the selected template", async () => {
  const template = {
    id: "template", company_id: "tenant", name: "Custom reference", kind: "general", description: null,
    subject_template: "Subject", body_template: "Reference {{reference}}", is_active: true,
    created_by_membership_id: "owner", created_at: "2026-11-11T00:00:00Z", updated_at: "2026-11-11T00:00:00Z",
    variables: [{ name: "reference", label: "Reference", required: true }],
  };
  render(<ComposeEmailForm matterId="matter" templates={[template]} loading={false} templateError={null} submitting={false} onSubmit={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Template"), { target: { value: "template" } });
  expect(screen.getByTestId("comm-send-var-reference")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.change(screen.getByTestId("comm-send-template"), { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Reference {{reference}}" } });
  expect(screen.queryByTestId("comm-send-var-reference")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("reference");
});

it("does not revive a preview after navigating away from its matter and back", async () => {
  preview.mockResolvedValue(result);
  const props = { templates: [], loading: false, templateError: null, submitting: false, onSubmit: vi.fn() };
  const view = render(<ComposeEmailForm matterId="matter" {...props} />);
  fireEvent.change(screen.getByLabelText("Recipient email"), { target: { value: "client@example.com" } });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Update" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Reviewed message" } });
  fireEvent.click(screen.getByTestId("comm-send-preview"));
  await waitFor(() => expect(screen.getByTestId("comm-send-submit")).toBeEnabled());
  view.rerender(<ComposeEmailForm matterId="other-matter" {...props} />);
  view.rerender(<ComposeEmailForm matterId="matter" {...props} />);
  expect(screen.getByTestId("comm-send-submit")).toBeDisabled();
  expect(screen.queryByTestId("comm-send-preview-result")).not.toBeInTheDocument();
});
