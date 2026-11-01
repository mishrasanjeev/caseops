import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FileSignature } from "lucide-react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMattersMock } = vi.hoisted(() => ({ listMattersMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listMatters: listMattersMock }));

import { MatterHubList } from "@/components/app/MatterHubList";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function matter(index: number, title = `Matter ${index}`) {
  return {
    id: `m${index}`,
    matter_code: `M-${index}`,
    title,
    status: "active",
    practice_area: null,
    client_name: null,
    forum_level: null,
    next_hearing_on: null,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-15T00:00:00Z",
  };
}

function renderHub() {
  return render(withClient(
    <MatterHubList
      scope="test-hub"
      testIdPrefix="test-hub"
      hrefFor={(row) => `/app/matters/${row.id}/drafts`}
      emptyIcon={FileSignature}
      noMattersText="Create a matter to start drafting."
    />,
  ));
}

describe("MatterHubList (B4-ADJ-03)", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
  });

  it("states its cap and reaches Matters past the first and second server pages", async () => {
    listMattersMock.mockImplementation(async ({ q, cursor }: { q?: string; cursor?: string }) => {
      if (q === "ZEBRA") return { matters: [matter(999, "Zebra v Union")], next_cursor: null };
      if (cursor === "c3") return { matters: [matter(100, "Oldest matter")], next_cursor: null };
      if (cursor === "c2") return { matters: Array.from({ length: 50 }, (_, i) => matter(50 + i)), next_cursor: "c3" };
      return { matters: Array.from({ length: 50 }, (_, i) => matter(i)), next_cursor: "c2" };
    });
    renderHub();
    expect(await screen.findByText("Showing the 50 most recently updated matters. Search, or load more.")).toBeVisible();
    expect(screen.queryByText("Oldest matter")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load more matters" }));
    expect(await screen.findByText("Showing the 100 most recently updated matters. Search, or load more.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load more matters" }));
    expect(await screen.findByText("Oldest matter")).toBeVisible();
    expect(screen.getByTestId("test-hub-count")).toHaveTextContent("101 matters.");
    expect(screen.queryByRole("button", { name: "Load more matters" })).toBeNull();
    expect(listMattersMock).toHaveBeenCalledWith({ q: undefined, cursor: "c3", limit: 50 });
    expect(screen.getByTestId("test-hub-open-M-100")).toHaveAttribute("href", "/app/matters/m100/drafts");
  });

  it("searches every visible Matter on the server, not the loaded rows", async () => {
    listMattersMock.mockImplementation(async ({ q }: { q?: string }) =>
      q === "ZEBRA"
        ? { matters: [matter(999, "Zebra v Union")], next_cursor: null }
        : { matters: [matter(1)], next_cursor: "c2" });
    renderHub();
    await screen.findByText("Matter 1");
    fireEvent.change(screen.getByLabelText("Search matters"), { target: { value: "ZEBRA" } });
    await waitFor(() => expect(screen.getByText("Zebra v Union")).toBeVisible(), { timeout: 5_000 });
    expect(listMattersMock).toHaveBeenCalledWith({ q: "ZEBRA", cursor: undefined, limit: 50 });
    expect(screen.getByTestId("test-hub-count")).toHaveTextContent("1 matter matching “ZEBRA”.");

    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });
    fireEvent.change(screen.getByLabelText("Search matters"), { target: { value: "NOPE" } });
    expect(await screen.findByText("No matter matches", undefined, { timeout: 5_000 })).toBeVisible();
  });

  it("says when there are no matters and retries a failed load", async () => {
    listMattersMock.mockRejectedValueOnce(new Error("network")).mockResolvedValue({ matters: [], next_cursor: null });
    renderHub();
    expect(await screen.findByText(/Could not load matters/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Create a matter to start drafting.")).toBeVisible();
  });
});
