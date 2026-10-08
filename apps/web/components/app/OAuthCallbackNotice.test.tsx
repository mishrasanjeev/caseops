import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OAuthCallbackNotice } from "./OAuthCallbackNotice";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("OAuth callback recovery", () => {
  it.each(["google_calendar", "outlook", "gmail", "google_drive"])(
    "shows bounded recovery for %s without reflecting secrets", (provider) => {
      window.history.replaceState(null, "", `/?oauth_provider=${provider}&oauth_result=retry&error=secret&code=credential`);
      render(<OAuthCallbackNotice area={provider === "google_drive" ? "drive" : "calendar"} />);
      expect(screen.getByRole("alert")).toHaveTextContent("Start a new connection");
      expect(screen.getByRole("alert")).not.toHaveTextContent(/secret|credential/);
    },
  );

  it("explains that an interrupted claim expires rather than requesting repeated callbacks", () => {
    window.history.replaceState(null, "", "/?oauth_provider=google_calendar&oauth_result=in_flight");
    render(<OAuthCallbackNotice area="calendar" />);
    expect(screen.getByRole("alert")).toHaveTextContent("five minutes");
    expect(screen.getByRole("alert")).toHaveTextContent("Wait for it to finish");
  });

  it.each([
    "oauth_provider=google_calendar&oauth_result=connected",
    "oauth_provider=google_calendar&oauth_result=unknown",
    "oauth_provider=untrusted&oauth_result=retry",
    "oauth_provider=__proto__&oauth_result=retry",
    "oauth_provider=google_drive&oauth_result=retry",
  ])("does not establish success or reflect untrusted parameters: %s", (query) => {
    window.history.replaceState(null, "", `/?${query}`);
    render(<OAuthCallbackNotice area="calendar" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
