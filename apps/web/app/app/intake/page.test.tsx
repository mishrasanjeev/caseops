import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listIntakeMock, useCapabilityMock } = vi.hoisted(() => ({
  listIntakeMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listIntakeRequests: listIntakeMock,
  createIntakeRequest: vi.fn(),
  updateIntakeRequest: vi.fn(),
  promoteIntakeRequest: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import IntakePage from "@/app/app/intake/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IntakePage", () => {
  beforeEach(() => {
    listIntakeMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    listIntakeMock.mockResolvedValue({ requests: [] });
  });

  it("renders the intake heading and calls listIntakeRequests", async () => {
    render(withClient(<IntakePage />));
    expect(screen.getByText(/Legal intake queue/i)).toBeInTheDocument();
    await waitFor(() => expect(listIntakeMock).toHaveBeenCalledTimes(1));
  });
});
