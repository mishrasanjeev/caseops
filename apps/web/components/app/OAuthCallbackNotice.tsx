"use client";

import { useEffect, useState } from "react";

const PROVIDERS = {
  google_calendar: "Google Calendar",
  outlook: "Outlook",
  gmail: "Gmail",
  google_drive: "Google Drive",
} as const;

const OUTCOMES = {
  consent_required: "The provider could not confirm the required permissions. Start a new connection and grant the requested permissions.",
  consumed: "This authorization callback was already used. Check the current connection below; start a new connection only if it is not connected.",
  in_flight: "A connection attempt is still running. Wait for it to finish, then reload. An interrupted attempt expires within five minutes.",
  access_changed: "Your access or security confirmation changed during authorization. Sign in again before starting a new connection.",
  changed: "The connection changed during authorization or still has pending cleanup. Reload to check its current status before connecting again.",
  unavailable: "The connector is unavailable. Check its configuration before starting a new connection.",
  retry: "Authorization could not be completed. Start a new connection from this page; do not reload the provider callback.",
} as const;

export function OAuthCallbackNotice({ area }: { area: "calendar" | "drive" }) {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const provider = params.get("oauth_provider");
    const outcome = params.get("oauth_result");
    if (
      provider && Object.hasOwn(PROVIDERS, provider) &&
      outcome && Object.hasOwn(OUTCOMES, outcome) &&
      (area === "drive" ? provider === "google_drive" : provider !== "google_drive")
    ) {
      setMessage(`${PROVIDERS[provider as keyof typeof PROVIDERS]}: ${OUTCOMES[outcome as keyof typeof OUTCOMES]}`);
    }
  }, [area]);

  // Only the fresh connection query, never a URL parameter, can establish success.
  if (!message) return null;
  return (
    <p role="alert" data-testid="oauth-callback-notice" className="min-w-0 break-words text-sm text-amber-800">
      {message}
    </p>
  );
}
