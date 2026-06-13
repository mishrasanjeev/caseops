import { describe, expect, it, vi } from "vitest";

const redirectMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

import AppAccountSecurityRedirectPage from "@/app/app/account/security/page";

describe("AppAccountSecurityRedirectPage", () => {
  it("keeps /app/account/security as a compatibility route", () => {
    AppAccountSecurityRedirectPage();

    expect(redirectMock).toHaveBeenCalledWith("/account/security");
  });
});
