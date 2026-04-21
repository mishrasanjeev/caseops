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

import IntakePage, { suggestNextMatterCode } from "@/app/app/intake/page";

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


// BUG-017 Hari 2026-04-21: PromoteButton catches the backend's
// ``already in use`` 400 and auto-suggests a bumped code. The pure
// helper is exported so we can pin the bump logic here.
describe("suggestNextMatterCode", () => {
  it("bumps a trailing numeric segment by 1", () => {
    expect(suggestNextMatterCode("CORP-ARB-99")).toBe("CORP-ARB-100");
    expect(suggestNextMatterCode("HARI-DUP-1")).toBe("HARI-DUP-2");
  });
  it("preserves zero-padding on the bump", () => {
    expect(suggestNextMatterCode("CASE-0009")).toBe("CASE-0010");
    expect(suggestNextMatterCode("CASE-099")).toBe("CASE-100");
  });
  it("appends -2 when the code has no trailing digits", () => {
    expect(suggestNextMatterCode("BAIL-NEW")).toBe("BAIL-NEW-2");
  });
  it("returns null for empty input", () => {
    expect(suggestNextMatterCode("")).toBeNull();
    expect(suggestNextMatterCode("A")).toBeNull();
  });
});
