import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlatformSignInForm } from "./PlatformSignInForm";

describe("platform sign-in skeleton", () => {
  it("has no workspace field and remains fail-closed before an adapter is bound", () => {
    render(<PlatformSignInForm />);
    expect(screen.queryByLabelText(/workspace/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });
  it("passes credentials only to its explicit handler and clears the password", async () => {
    const onSignIn = vi.fn().mockResolvedValue(undefined);
    render(<PlatformSignInForm onSignIn={onSignIn} />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@example.invalid" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "ephemeral-only" } });
    fireEvent.submit(screen.getByRole("form", { name: "Platform sign in" }));
    await waitFor(() => expect(onSignIn).toHaveBeenCalledExactlyOnceWith({ email: "admin@example.invalid", password: "ephemeral-only" }));
    await waitFor(() => expect(screen.getByLabelText("Password")).toHaveValue(""));
  });
  it("does not render an exception payload containing credentials", async () => {
    render(<PlatformSignInForm onSignIn={vi.fn().mockRejectedValue(new Error("private-payload"))} />);
    fireEvent.submit(screen.getByRole("form", { name: "Platform sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to sign in");
    expect(screen.queryByText(/private-payload/)).not.toBeInTheDocument();
  });
});
