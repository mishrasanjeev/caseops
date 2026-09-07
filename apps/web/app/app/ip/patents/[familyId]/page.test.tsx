import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useParams: () => ({ familyId: "selected-family" }) }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
vi.mock("@/lib/api/ip-patents", () => ({ fetchPatentFamily: get }));
import Page from "./page";

it("uses the URL family identity and fails closed when access was revoked", async () => {
  get.mockRejectedValue(new Error("Patent family not found."));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <Page />
  </QueryClientProvider>);
  expect(await screen.findByText("Could not open patent family")).toBeVisible();
  expect(get).toHaveBeenCalledWith("selected-family", undefined, expect.any(AbortSignal));
  expect(screen.queryByRole("button", { name: "Edit disclosure" })).not.toBeInTheDocument();
});
