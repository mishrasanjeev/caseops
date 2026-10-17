import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { InAppNotificationCenter } from "./InAppNotificationCenter";

const { list, update } = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn() }));
vi.mock("@/lib/api/in-app-notifications", () => ({
  listRecipientNotifications: list, updateRecipientNotification: update,
}));
let state: "unread" | "read" | "dismissed";
const note = () => ({ id: "note-1", docket_id: "docket-1", title: "Renewal reminder",
  body: "Current mark <strong>not HTML</strong>\nDue tomorrow", status: state,
  created_at: "2026-10-17T04:00:00Z", read_at: null });
function mount(membershipId = "member-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><InAppNotificationCenter docketId="docket-1" membershipId={membershipId} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks(); state = "unread";
  list.mockImplementation(async ({ dismissed }) => ({ items: (state === "dismissed") === dismissed ? [note()] : [], next_cursor: null }));
  update.mockImplementation(async ({ status }) => { state = status; return note(); });
});

it("dismisses and restores the exact retained receipt without HTML interpretation", async () => {
  const first = mount();
  const row = await screen.findByTestId("in-app-notification-note-1");
  expect(within(row).getByTestId("in-app-notification-body-note-1")).toHaveTextContent("<strong>not HTML</strong>");
  expect(row.querySelector("strong")).toBeNull();
  fireEvent.click(within(row).getByRole("button", { name: "Dismiss alert" }));
  await screen.findByText("No current alerts.");
  expect(update).toHaveBeenCalledWith({ docketId: "docket-1", notificationId: "note-1", expectedStatus: "unread", status: "dismissed" });
  first.unmount();
  mount();
  await screen.findByText("No current alerts.");
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Dismissed alerts" }), { button: 0, ctrlKey: false });
  const restoredRow = await screen.findByTestId("in-app-notification-note-1");
  fireEvent.click(within(restoredRow).getByRole("button", { name: "Restore alert" }));
  await screen.findByText("No dismissed alerts.");
  expect(update).toHaveBeenLastCalledWith({ docketId: "docket-1", notificationId: "note-1", expectedStatus: "dismissed", status: "unread" });
});

it("retains the current alert and reports rejected mutation without success or retry", async () => {
  update.mockRejectedValue(new Error("Notification changed; reload its current state."));
  mount();
  const row = await screen.findByTestId("in-app-notification-note-1");
  fireEvent.click(within(row).getByRole("button", { name: "Dismiss alert" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Notification changed");
  expect(screen.getByTestId("in-app-notification-note-1")).toBeVisible();
  expect(state).toBe("unread");
  expect(update).toHaveBeenCalledTimes(1);
});

it("marks a receipt read and disables another action while awaiting the server", async () => {
  let complete!: (value: ReturnType<typeof note>) => void;
  update.mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  mount();
  const row = await screen.findByTestId("in-app-notification-note-1");
  fireEvent.click(within(row).getByRole("button", { name: "Mark read" }));
  await waitFor(() => expect(within(row).getByRole("button", { name: "Dismiss alert" })).toBeDisabled());
  expect(row).toHaveTextContent("unread");
  state = "read"; complete(note());
  await waitFor(() => expect(within(row).queryByRole("button", { name: "Mark read" })).toBeNull());
});

it("does not fetch a recipient body without an authenticated membership", async () => {
  mount("");
  expect(list).not.toHaveBeenCalled();
  expect(screen.queryByTestId("in-app-notification-note-1")).not.toBeInTheDocument();
});
