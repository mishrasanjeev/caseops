import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import type { IpDocket, IpDocketListPage } from "@/lib/api/endpoints";

const { fetchIpDocketsMock, fetchIpDocketMock } = vi.hoisted(() => ({
  fetchIpDocketsMock: vi.fn(),
  fetchIpDocketMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDockets: fetchIpDocketsMock,
  fetchIpDocket: fetchIpDocketMock,
}));

import { IpDocketPicker, ipDocketCaption } from "@/components/ip/IpDocketPicker";

function docket(id: string, title: string, identifier: string | null = null, recordType = "trademark") {
  return { id, title, primary_identifier: identifier, record_type: recordType } as IpDocket;
}

function page(
  dockets: IpDocket[],
  { total = dockets.length, next = null }: { total?: number; next?: string | null } = {},
): IpDocketListPage {
  return { dockets, count: dockets.length, has_more: next !== null, next_cursor: next, total_count: total };
}

const FIRST_PAGE = Array.from({ length: 50 }, (_, index) =>
  docket(`d-${index}`, `Recent mark ${index}`, `TM-${index}`),
);
const SECOND_PAGE = Array.from({ length: 50 }, (_, index) =>
  docket(`d-${index + 50}`, `Older mark ${index + 50}`, `TM-${index + 50}`),
);
const PINE = docket("pine", "PINE LABS", "4009154");
const TASTYBITE = docket("tasty", "TASTYBITE International Portfolio", null, "international_registration");

function Harness({
  initial = "",
  onChange,
  ...props
}: {
  initial?: string;
  onChange?: (id: string, record: IpDocket | null) => void;
  emptyOptionLabel?: string;
  error?: string;
  excludeIds?: string[];
}) {
  const [value, setValue] = useState(initial);
  return (
    <IpDocketPicker
      id="docket"
      value={value}
      onChange={(next, record) => {
        setValue(next);
        onChange?.(next, record);
      }}
      {...props}
    />
  );
}

function renderPicker(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function picker() {
  return screen.getByRole<HTMLSelectElement>("combobox", { name: "Docket" });
}

function optionValues() {
  return Array.from(picker().options, (option) => option.value);
}

describe("IpDocketPicker", () => {
  beforeEach(() => {
    fetchIpDocketsMock.mockReset();
    fetchIpDocketMock.mockReset();
  });

  it("labels dockets so a Madrid record and an unnumbered docket are distinguishable", () => {
    expect(ipDocketCaption(PINE)).toBe("PINE LABS · 4009154");
    expect(ipDocketCaption(TASTYBITE)).toBe(
      "TASTYBITE International Portfolio · No primary identifier · International registration",
    );
  });

  it("shows loading, then says how much of the portfolio it shows, and pages by cursor", async () => {
    let resolveFirst: (value: IpDocketListPage) => void = () => {};
    fetchIpDocketsMock.mockImplementationOnce(
      () => new Promise<IpDocketListPage>((resolve) => { resolveFirst = resolve; }),
    );
    renderPicker(<Harness />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading dockets…");
    expect(picker()).toBeDisabled();

    resolveFirst(page(FIRST_PAGE, { total: 3726, next: "cursor-1" }));
    await waitFor(() => expect(picker()).toBeEnabled());
    expect(fetchIpDocketsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "", cursor: null, limit: 50 }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 50 of 3,726 dockets — refine your search or load more.",
    );
    expect(optionValues()).toHaveLength(51);

    fetchIpDocketsMock.mockResolvedValueOnce(page(SECOND_PAGE, { total: 3726, next: "cursor-2" }));
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(optionValues()).toHaveLength(101));
    expect(fetchIpDocketsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "", cursor: "cursor-1", limit: 50 }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Showing 100 of 3,726 dockets");
  });

  it("finds a docket beyond the loaded page by server search and describes the full caption", async () => {
    const change = vi.fn();
    fetchIpDocketsMock.mockImplementation(async ({ query }: { query: string }) =>
      query === "4009154" ? page([PINE]) : page(FIRST_PAGE, { total: 3726, next: "cursor-1" }),
    );
    renderPicker(<Harness onChange={change} />);
    await waitFor(() => expect(picker()).toBeEnabled());
    expect(optionValues()).not.toContain("pine");

    fireEvent.change(screen.getByLabelText("Find docket"), { target: { value: " 4009154 " } });
    await waitFor(() => expect(optionValues()).toEqual(["", "pine"]));
    expect(fetchIpDocketsMock).toHaveBeenLastCalledWith(expect.objectContaining({ query: "4009154" }));
    expect(screen.getByRole("status")).toHaveTextContent("1 matching docket.");

    fireEvent.change(picker(), { target: { value: "pine" } });
    expect(change).toHaveBeenCalledWith("pine", PINE);
    expect(picker()).toHaveValue("pine");
    expect(picker()).toHaveAccessibleDescription(expect.stringContaining("PINE LABS · 4009154"));
  });

  it("keeps the chosen docket selected when a later search no longer returns it", async () => {
    fetchIpDocketsMock.mockImplementation(async ({ query }: { query: string }) =>
      query ? page([docket("other", "Other mark", "TM-9")]) : page([PINE]),
    );
    renderPicker(<Harness />);
    await waitFor(() => expect(picker()).toBeEnabled());
    fireEvent.change(picker(), { target: { value: "pine" } });
    fireEvent.change(screen.getByLabelText("Find docket"), { target: { value: "other" } });
    await waitFor(() => expect(optionValues()).toEqual(["", "pine", "other"]));
    expect(picker()).toHaveValue("pine");
    expect(fetchIpDocketMock).not.toHaveBeenCalled();
  });

  it("resolves a deep-linked docket that is not on the first page", async () => {
    fetchIpDocketsMock.mockResolvedValue(page(FIRST_PAGE, { total: 3726, next: "cursor-1" }));
    fetchIpDocketMock.mockResolvedValue(PINE);
    const change = vi.fn();
    renderPicker(<Harness initial="pine" onChange={change} />);
    // While the lookup runs the field says so instead of showing a blank select.
    expect(picker().selectedOptions[0]).toHaveTextContent("Loading the selected docket…");
    await waitFor(() =>
      expect(picker()).toHaveAccessibleDescription(expect.stringContaining("PINE LABS · 4009154")),
    );
    expect(picker()).toHaveValue("pine");
    expect(fetchIpDocketMock).toHaveBeenCalledWith("pine");
    expect(optionValues().slice(0, 2)).toEqual(["", "pine"]);
    expect(optionValues()).toHaveLength(52);
    // A deep link is the caller's choice; the picker reports nothing on its own.
    expect(change).not.toHaveBeenCalled();
  });

  it("says when a deep-linked docket is hidden and lets the user clear it", async () => {
    fetchIpDocketsMock.mockResolvedValue(page(FIRST_PAGE));
    fetchIpDocketMock.mockRejectedValue(new ApiError(404, "IP docket not found.", {}));
    const change = vi.fn();
    renderPicker(<Harness initial="walled" onChange={change} />);
    const alert = await screen.findByText("The selected docket is not available to you or no longer exists.");
    expect(picker()).toHaveAttribute("aria-invalid", "true");
    expect(picker()).toHaveAccessibleDescription(
      expect.stringContaining("The selected docket is not available to you or no longer exists."),
    );
    expect(picker().selectedIndex).toBe(-1);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    fireEvent.click(within(alert.parentElement!).getByRole("button", { name: "Clear selection" }));
    expect(change).toHaveBeenCalledWith("", null);
    await waitFor(() => expect(picker()).toHaveValue(""));
  });

  it("shows a failed load with a retry, never as an empty portfolio", async () => {
    fetchIpDocketsMock.mockRejectedValueOnce(new ApiError(503, "The database is temporarily unavailable.", {}));
    renderPicker(<Harness />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Dockets could not be loaded: The database is temporarily unavailable.");
    expect(screen.queryByText(/No trademark dockets are visible/)).toBeNull();
    expect(picker()).toBeDisabled();

    fetchIpDocketsMock.mockResolvedValueOnce(page([PINE]));
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(optionValues()).toEqual(["", "pine"]));
    expect(picker()).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("explains an empty portfolio and links to where a docket is created", async () => {
    fetchIpDocketsMock.mockResolvedValue(page([]));
    renderPicker(<Harness />);
    await screen.findByText(/No trademark dockets are visible to you/);
    expect(picker()).toBeDisabled();
    expect(screen.getByRole("link", { name: "Create one in the trademark docket" })).toHaveAttribute("href", "/app/ip");
    expect(screen.getByRole("link", { name: "Import a portfolio" })).toHaveAttribute(
      "href",
      "/app/ip/portfolio/imports",
    );
  });

  it("names the search that matched nothing and offers no option that can only fail", async () => {
    fetchIpDocketsMock.mockImplementation(async ({ query }: { query: string }) =>
      query ? page([]) : page([PINE]),
    );
    renderPicker(<Harness />);
    await waitFor(() => expect(picker()).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Find docket"), { target: { value: "zzzz" } });
    await screen.findByText(/No visible docket matches “zzzz”/);
    expect(optionValues()).toEqual([""]);
    expect(picker()).toBeDisabled();
  });

  it("never selects a docket on its own", async () => {
    const change = vi.fn();
    fetchIpDocketsMock.mockResolvedValue(page([TASTYBITE, PINE]));
    renderPicker(<Harness onChange={change} />);
    await waitFor(() => expect(picker()).toBeEnabled());
    expect(picker()).toHaveValue("");
    expect(picker().selectedOptions[0]).toHaveTextContent("Select a docket");
    expect(picker().selectedOptions[0]).toBeDisabled();
    expect(change).not.toHaveBeenCalled();
  });

  it("keeps an explicit empty choice selectable", async () => {
    const change = vi.fn();
    fetchIpDocketsMock.mockResolvedValue(page([PINE]));
    renderPicker(<Harness initial="pine" onChange={change} emptyOptionLabel="All accessible dockets" />);
    await waitFor(() => expect(picker()).toHaveValue("pine"));
    fireEvent.change(picker(), { target: { value: "" } });
    expect(change).toHaveBeenLastCalledWith("", null);
    expect(picker()).toHaveValue("");
    expect(picker().selectedOptions[0]).toHaveTextContent("All accessible dockets");
    expect(picker().selectedOptions[0]).toBeEnabled();
  });

  it("anchors a caller's field error to the select", async () => {
    fetchIpDocketsMock.mockResolvedValue(page([PINE]));
    renderPicker(<Harness error="Docket: Select the docket to reconcile." />);
    await waitFor(() => expect(picker()).toBeEnabled());
    expect(picker()).toHaveAttribute("aria-invalid", "true");
    expect(picker()).toHaveAccessibleDescription(expect.stringContaining("Docket: Select the docket to reconcile."));
  });

  it("never offers an excluded docket, such as a transfer's own docket as its successor", async () => {
    fetchIpDocketsMock.mockResolvedValue(page([PINE, TASTYBITE], { total: 2 }));
    renderPicker(<Harness excludeIds={["pine"]} />);
    await waitFor(() => expect(picker()).toBeEnabled());
    expect(optionValues()).toEqual(["", "tasty"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 docket.");
  });

  it("explains when the only visible docket is excluded", async () => {
    fetchIpDocketsMock.mockResolvedValue(page([PINE]));
    renderPicker(<Harness excludeIds={["pine"]} />);
    expect(await screen.findByText(/No other trademark docket is visible to you/)).toBeVisible();
    expect(optionValues()).toEqual([""]);
    expect(picker()).toBeDisabled();
  });
});
