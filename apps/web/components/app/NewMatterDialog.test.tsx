import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createMatterMock, toastSuccess, toastError } = vi.hoisted(() => ({
  createMatterMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatter: createMatterMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewMatterDialog } from "@/components/app/NewMatterDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("new-matter-trigger"));
}

describe("NewMatterDialog", () => {
  beforeEach(() => {
    createMatterMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("announces validation errors with aria-invalid + aria-describedby wired to the error id", async () => {
    const user = userEvent.setup();
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    // Submitting the dialog with no fields filled trips the zod schema.
    await user.click(await screen.findByRole("button", { name: /Create matter/i }));

    const titleInput = await screen.findByLabelText("Title");
    expect(titleInput).toHaveAttribute("aria-invalid", "true");
    const errorId = titleInput.getAttribute("aria-describedby");
    expect(errorId).toBeTruthy();
    const errorNode = document.getElementById(errorId as string);
    expect(errorNode).toBeInTheDocument();
    expect(errorNode).toHaveAttribute("role", "alert");
    expect(errorNode?.textContent).toMatch(/At least 3 characters/i);

    expect(createMatterMock).not.toHaveBeenCalled();
  });

  it("uppercases the matter code and trims whitespace before calling the API", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-1",
      matter_code: "BLR-001",
      title: "Test matter",
      created_at: "2026-04-17T10:00:00Z",
      status: "active",
    });
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await user.type(await screen.findByLabelText("Title"), "  Spine matter  ");
    await user.type(screen.getByLabelText("Matter code"), "  blr-001  ");
    await user.type(screen.getByLabelText("Practice area"), "Commercial");
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Spine matter",
        matter_code: "BLR-001",
        practice_area: "Commercial",
        forum_level: "high_court",
        status: "active",
      }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });
});
