"use client";

import { ArrowRight, Loader2, Smartphone } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiRequest } from "@/lib/api/client";
import { completeMfaLoginChallenge } from "@/lib/api/auth";
import { isApiErrorShape } from "@/lib/api/config";
import type { AuthContext } from "@/lib/api/schema-types";
import {
  openNativeApp,
  parseNativeAuthorization,
  prepareNativeHandoff,
} from "@/lib/native-authorization";
import { DISABLED_NATIVE_LINK_POLICY, type NativeLinkPolicy } from '@/lib/native-link-policy.cjs';

export function NativeSignIn({ policy = DISABLED_NATIVE_LINK_POLICY }: { policy?: NativeLinkPolicy }) {
  const params = useSearchParams();
  const parsed = parseNativeAuthorization(params.toString(), policy);
  const policyKey = JSON.stringify(policy);
  const rawQuery = params.toString();
  const query = `${policyKey}\n${rawQuery}`;
  const next = `/native/sign-in?${rawQuery}`;
  const [context, setContext] = useState<AuthContext | null>(null);
  const [contextQuery, setContextQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [pending, setPending] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [handoffReady, setHandoffReady] = useState(false);
  const [handoffExpired, setHandoffExpired] = useState(false);
  const [opening, setOpening] = useState(false);
  const handoff = useRef<{
    callback: string;
    query: string;
    owner: number;
    deadline: number;
  } | null>(null);
  const handoffTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openingRef = useRef(false);
  const submitting = useRef(false);
  const verifying = useRef(false);
  const epoch = useRef(0);
  const consent = contextQuery === query ? context : null;
  const hasHandoff =
    handoffReady &&
    handoff.current?.query === query &&
    handoff.current.owner === epoch.current;
  const discardHandoff = useCallback(() => {
    if (handoffTimer.current !== null) clearTimeout(handoffTimer.current);
    handoffTimer.current = null;
    handoff.current = null;
    openingRef.current = false;
    setHandoffReady(false);
    setOpening(false);
  }, []);

  useEffect(() => {
    const leave = () => {
      if (handoff.current) {
        discardHandoff();
        setHandoffExpired(true);
        setNotice(null);
      }
    };
    const visibility = () => {
      if (document.visibilityState === "hidden") leave();
    };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [discardHandoff]);

  useEffect(() => {
    const owner = ++epoch.current;
    discardHandoff();
    setHandoffExpired(false);
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
    if (!parseNativeAuthorization(rawQuery, policy)) setLoading(false);
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
      discardHandoff();
      if (owner === epoch.current) ++epoch.current;
    };
  }, [query, discardHandoff]);

  async function connect() {
    if (
      !parsed ||
      !consent ||
      mfaRequired ||
      handoff.current ||
      handoffExpired ||
      submitting.current ||
      verifying.current
    )
      return;
    const owner = epoch.current;
    const startedAt = performance.now();
    submitting.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiRequest<unknown>("/api/auth/native/authorize", {
        method: "POST",
        body: parsed,
      });
      if (owner !== epoch.current) return;
      const prepared = prepareNativeHandoff(parsed, response, policy);
      // Charge response latency to the server's lifetime, never extend a grant.
      const deadline = startedAt + prepared.expiresIn * 1000;
      const remaining = deadline - performance.now();
      if (remaining <= 0) {
        setHandoffExpired(true);
        return;
      }
      handoff.current = { callback: prepared.callback, query, owner, deadline };
      setHandoffReady(true);
      setNotice("Sign-in is ready. Open CaseOps to finish.");
      handoffTimer.current = setTimeout(() => {
        if (owner !== epoch.current) return;
        discardHandoff();
        setHandoffExpired(true);
        setNotice(null);
      }, remaining);
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

  function openApp() {
    const current = handoff.current;
    if (
      !current ||
      current.owner !== epoch.current ||
      current.query !== query ||
      openingRef.current
    )
      return;
    if (performance.now() >= current.deadline) {
      discardHandoff();
      setHandoffExpired(true);
      setNotice(null);
      return;
    }
    openingRef.current = true;
    setOpening(true);
    try {
      // Synchronous user gesture: no awaited network operation before app launch.
      openNativeApp(current.callback, policy);
    } catch {
      discardHandoff();
      setHandoffExpired(true);
      setNotice(null);
      setError(
        "The app could not be opened. Return to CaseOps and start sign-in again.",
      );
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
            {handoffExpired && !error && (
              <p role="alert">
                This app handoff is no longer available. Return to CaseOps and
                start sign-in again.
              </p>
            )}
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
                {hasHandoff ? (
                  <div className="space-y-3">
                    <Button
                      id="native-app-open"
                      className="min-h-12 w-full"
                      disabled={opening}
                      onClick={openApp}
                    >
                      <ArrowRight aria-hidden className="mr-2 h-4 w-4" />
                      Open CaseOps
                    </Button>
                    {opening && (
                      <p role="status">
                        Choose Open in your browser if prompted. If CaseOps does
                        not open, return to the app and start sign-in again.
                      </p>
                    )}
                  </div>
                ) : mfaRequired ? (
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
                ) : !handoffExpired ? (
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
                ) : null}
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
