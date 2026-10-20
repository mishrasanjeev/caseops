import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformApi } from "@/lib/platform/client";

import { PlatformResendInvitation } from "./PlatformResendInvitation";

vi.mock("@/lib/platform/client", () => ({ platformApi: { resendInvitation: vi.fn() }, consoleErrorMessage: () => "Request outcome could not be confirmed." }));
describe("explicit setup email recovery", () => {
  beforeEach(() => { vi.mocked(platformApi.resendInvitation).mockReset(); });
  it("makes no automatic call and submits one generic recovery request", async () => {
    vi.mocked(platformApi.resendInvitation).mockResolvedValue({ status: "accepted" });
    render(<PlatformResendInvitation />);
    expect(platformApi.resendInvitation).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "recipient@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Resend setup email" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If this account is eligible");
    expect(platformApi.resendInvitation).toHaveBeenCalledExactlyOnceWith("recipient@example.invalid");
    expect(screen.getByRole("button", { name: "Resend setup email" })).toBeDisabled();
  });
  it("does not automatically retry an unconfirmed result or expose raw detail", async () => {
    vi.mocked(platformApi.resendInvitation).mockRejectedValue(new Error("private-response"));
    render(<PlatformResendInvitation />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "recipient@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Resend setup email" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed"));
    expect(platformApi.resendInvitation).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("private-response")).not.toBeInTheDocument();
  });
});
