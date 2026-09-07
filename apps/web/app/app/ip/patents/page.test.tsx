import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const list = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
vi.mock("@/lib/api/ip-patents", () => ({ fetchPatentFamilies: list }));
import Page from "./page";

it("renders the authorized family index and its empty state", async () => {
  list.mockResolvedValue({ families: [], next_cursor: null });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <Page />
  </QueryClientProvider>);
  expect(await screen.findByText("No accessible patent families on this page.")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Patent families", level: 1 })).toBeVisible();
  expect(screen.getByRole("button", { name: "New disclosure" })).toBeEnabled();
  expect(list).toHaveBeenCalledWith("", undefined, expect.any(AbortSignal), "active");
  fireEvent.change(screen.getByLabelText("Lifecycle", { exact: true }), { target: { value: "terminal" } });
  await waitFor(() => expect(list).toHaveBeenCalledWith("", undefined, expect.any(AbortSignal), "terminal"));
});
