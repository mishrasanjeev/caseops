"use client";

import { ArrowRight, Loader2, Smartphone } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiRequest } from "@/lib/api/client";
import { completeMfaLoginChallenge } from "@/lib/api/auth";
import { isApiErrorShape } from "@/lib/api/config";
import type { AuthContext } from "@/lib/api/schema-types";
import { parseNativeAuthorization } from "@/lib/native-authorization";

export function NativeSignIn() {
  const params = useSearchParams();
  const parsed = parseNativeAuthorization(params.toString());
  const query = params.toString();
  const next = `/native/sign-in?${query}`;
  const [context, setContext] = useState<AuthContext | null>(null);
  const [contextQuery, setContextQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [pending, setPending] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const submitting = useRef(false);
  const verifying = useRef(false);
  const epoch = useRef(0);
  const consent = contextQuery === query ? context : null;

  useEffect(() => {
    const owner = ++epoch.current;
    submitting.current = false;
    verifying.current = false;
    setContext(null);
    setContextQuery("");
    setMfaCode("");
    setMfaRequired(false);
    setNotice(null);
    setError(null);
    setSignedOut(false);
    setPending(false);
    setLoading(true);
    const controller = new AbortController();
    if (!parseNativeAuthorization(query)) setLoading(false);
    else
      void apiRequest<AuthContext>("/api/auth/me", {
        signal: controller.signal,
      })
        .then((current) => {
          if (owner === epoch.current && !controller.signal.aborted) {
            setContext(current);
            setContextQuery(query);
          }
        })
        .catch((cause) => {
          if (controller.signal.aborted || owner !== epoch.current) return;
          if (isApiErrorShape(cause) && cause.status === 401)
            setSignedOut(true);
          else
            setError(
              "Your session could not be verified. Sign in and complete the required security checks.",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted && owner === epoch.current)
            setLoading(false);
        });
    return () => {
      controller.abort();
      if (owner === epoch.current) ++epoch.current;
    };
  }, [query]);

  async function connect() {
    if (
      !parsed ||
      !consent ||
      mfaRequired ||
      submitting.current ||
      verifying.current
    )
      return;
    const owner = epoch.current;
    submitting.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiRequest<{
        code: string;
        state: string;
        redirect_uri: string;
      }>("/api/auth/native/authorize", {
        method: "POST",
        body: parsed,
      });
      if (owner !== epoch.current) return;
      if (
        response.state !== parsed.state ||
        response.redirect_uri !== parsed.redirect_uri ||
        !/^[A-Za-z0-9_-]{32,256}$/.test(response.code)
      ) {
        throw new Error("Invalid native handoff response.");
      }
      const callback = new URL(response.redirect_uri);
      callback.searchParams.set("code", response.code);
      callback.searchParams.set("state", response.state);
      window.location.assign(callback.href);
    } catch (cause) {
      if (owner !== epoch.current) return;
      if (isApiErrorShape(cause) && cause.status === 401) {
        setContext(null);
        setContextQuery("");
        setSignedOut(true);
        setMfaRequired(false);
      }
      if (
        isApiErrorShape(cause) &&
        cause.status === 403 &&
        cause.problemType === "native_mfa_required"
      ) {
        setMfaRequired(true);
        setMfaCode("");
      }
      setError(
        isApiErrorShape(cause)
          ? cause.detail
          : "The app connection could not be completed. Return to the app and start sign-in again.",
      );
    } finally {
      if (owner === epoch.current) {
        submitting.current = false;
        setPending(false);
      }
    }
  }

  async function verifyMfa() {
    if (
      !parsed ||
      !consent ||
      !mfaRequired ||
      !/^\d{6}$/.test(mfaCode) ||
      submitting.current ||
      verifying.current
    )
      return;
    const owner = epoch.current;
    verifying.current = true;
    setPending(true);
    setError(null);
    const code = mfaCode;
    setMfaCode("");
    try {
      const result = await completeMfaLoginChallenge({ code });
      if (owner !== epoch.current) return;
      if (result.status !== "verified")
        throw new Error("MFA verification was not confirmed.");
      const current = await apiRequest<AuthContext>("/api/auth/me");
      if (owner !== epoch.current) return;
      if (!sameIdentity(consent, current)) {
        setContext(null);
        setContextQuery("");
        setSignedOut(true);
        setMfaRequired(false);
        setError(
          "Your browser account changed. Sign in again before connecting the app.",
        );
        return;
      }
      setContext(current);
      setContextQuery(query);
      setMfaRequired(false);
      setNotice("Code verified. Select Connect app to continue.");
    } catch (cause) {
      if (owner !== epoch.current) return;
      if (isApiErrorShape(cause) && cause.status === 401) {
        setContext(null);
        setContextQuery("");
        setSignedOut(true);
        setMfaRequired(false);
      }
      setError(
        isApiErrorShape(cause)
          ? cause.detail
          : "The security check could not be verified. Enter a fresh code to try again.",
      );
    } finally {
      if (owner === epoch.current) {
        verifying.current = false;
        setPending(false);
      }
    }
  }

  return (
    <main className="min-h-screen bg-[var(--color-bg)] px-6 py-8 text-[var(--color-ink)]">
      <div className="mx-auto max-w-md space-y-6">
        <Logo />
        <Smartphone
          aria-hidden
          className="h-6 w-6 text-[var(--color-accent)]"
        />
        <h1 className="text-2xl font-semibold">Connect the CaseOps app</h1>
        {!parsed ? (
          <p role="alert">
            This sign-in request is invalid or incomplete. Open CaseOps on your
            phone and start again.
          </p>
        ) : (
          <>
            {loading && (
              <p role="status" className="flex items-center gap-2">
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                Checking your workspace
              </p>
            )}
            {error && (
              <p role="alert" className="text-[var(--color-danger)]">
                {error}
              </p>
            )}
            {notice && <p role="status">{notice}</p>}
            {consent && (
              <>
                <dl className="space-y-3 border-y border-[var(--color-line)] py-5">
                  <div>
                    <dt className="text-sm text-[var(--color-mute)]">
                      Account
                    </dt>
                    <dd className="break-words">
                      <span className="block">{consent.user.full_name}</span>
                      <span className="block">{consent.user.email}</span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[var(--color-mute)]">
                      Workspace
                    </dt>
                    <dd className="break-words">
                      {consent.company.name} / {consent.company.slug}
                    </dd>
                  </div>
                </dl>
                <p>
                  Connect this account to the{" "}
                  {parsed.platform === "ios" ? "iPhone" : "Android"} app. The
                  app uses your current workspace permissions.
                </p>
                {mfaRequired ? (
                  <form
                    className="space-y-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void verifyMfa();
                    }}
                  >
                    <Label htmlFor="native-mfa-code">Six-digit code</Label>
                    <Input
                      id="native-mfa-code"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      value={mfaCode}
                      disabled={pending}
                      onChange={(event) =>
                        setMfaCode(
                          event.target.value.replace(/\D/g, "").slice(0, 6),
                        )
                      }
                      aria-describedby="native-mfa-help"
                    />
                    <p
                      id="native-mfa-help"
                      className="text-sm text-[var(--color-mute)]"
                    >
                      Enter the current code from your authenticator.
                    </p>
                    <Button
                      type="submit"
                      className="min-h-12 w-full"
                      disabled={pending || !/^\d{6}$/.test(mfaCode)}
                    >
                      {pending && (
                        <Loader2
                          aria-hidden
                          className="mr-2 h-4 w-4 animate-spin"
                        />
                      )}
                      Verify code
                    </Button>
                  </form>
                ) : (
                  <Button
                    className="min-h-12 w-full"
                    disabled={pending}
                    onClick={() => void connect()}
                  >
                    {pending ? (
                      <Loader2
                        aria-hidden
                        className="mr-2 h-4 w-4 animate-spin"
                      />
                    ) : (
                      <ArrowRight aria-hidden className="mr-2 h-4 w-4" />
                    )}
                    Connect app
                  </Button>
                )}
              </>
            )}
            {(signedOut || error || consent) && (
              <Link
                className="inline-flex min-h-12 items-center underline"
                href={`/sign-in?next=${encodeURIComponent(next)}`}
              >
                {consent ? "Use another account" : "Sign in securely"}
              </Link>
            )}
          </>
        )}
      </div>
    </main>
  );
}

function sameIdentity(before: AuthContext, after: AuthContext): boolean {
  return (
    [before.user.id, before.company.id, before.membership.id].every(
      (value) => typeof value === "string" && !!value.trim(),
    ) &&
    before.user.id === after.user.id &&
    before.company.id === after.company.id &&
    before.membership.id === after.membership.id
  );
}
