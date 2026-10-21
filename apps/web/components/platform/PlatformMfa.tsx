"use client";

import { KeyRound, ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { consoleErrorMessage, platformApi } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

export function PlatformMfa() {
  const session = usePlatformSession();
  const router = useRouter();
  const [enrollmentState, setEnrollment] = useState<{
    expiresAt: string;
    data: Awaited<ReturnType<typeof platformApi.enroll>>;
  } | null>(null);
  const [factor, setFactor] = useState<"code" | "recovery">("code");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verified, setVerified] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const needsEnrollment = session.auth?.state === "mfa_enrollment_required";
  const enrollment = needsEnrollment && enrollmentState && enrollmentState.expiresAt === session.auth?.expires_at
    ? enrollmentState.data : null;

  async function enroll() {
    if (pending || !needsEnrollment || !session.auth) return;
    const expiresAt = session.auth.expires_at;
    setPending(true); setError(null); setCode("");
    try { setEnrollment({ expiresAt, data: await platformApi.enroll() }); } catch (failure) { setError(consoleErrorMessage(failure)); }
    finally { setPending(false); }
  }
  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError(null);
    try {
      const auth = await platformApi.verify(factor === "code" ? { code } : { recovery_code: code });
      session.accept(auth);
      if (auth.state === "authenticated") {
        setRecoveryCodes(auth.recovery_codes ?? []); setEnrollment(null); setVerified(true);
      }
    } catch (failure) { setError(consoleErrorMessage(failure)); }
    finally { setCode(""); setPending(false); }
  }
  if (verified) return (
    <section className="max-w-xl space-y-5">
      <h2 className="flex items-center gap-2 text-lg font-bold"><ShieldCheck className="h-5 w-5" aria-hidden />MFA verified</h2>
      {recoveryCodes.length ? <div><h3 className="mb-3 font-bold">Recovery codes</h3><ul aria-label="Recovery codes" className="grid grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2">{recoveryCodes.map((value) => <li key={value}><code>{value}</code></li>)}</ul></div> : null}
      <Button onClick={() => { setRecoveryCodes([]); router.replace("/platform/reports"); }}>Continue to reports</Button>
    </section>
  );
  return (
    <section className="max-w-xl space-y-5" aria-label="Multi-factor verification">
      <h2 className="text-lg font-bold">{needsEnrollment ? "Set up multi-factor authentication" : "Verify multi-factor authentication"}</h2>
      {needsEnrollment && !enrollment ? <Button onClick={() => void enroll()} disabled={pending}><KeyRound className="h-4 w-4" aria-hidden />Set up authenticator</Button> : null}
      {enrollment ? <div className="grid min-w-0 gap-4 sm:grid-cols-[256px_minmax(0,1fr)]">
        <QRCodeSVG
          value={enrollment.otpauth_url}
          size={256}
          marginSize={4}
          level="M"
          bgColor="#ffffff"
          fgColor="#000000"
          role="img"
          aria-label="Authenticator setup QR code"
          className="block aspect-square h-auto w-64 max-w-full"
        />
        <div className="min-w-0 space-y-3">
          <Label htmlFor="platform-setup-key">Authenticator setup key</Label>
          <Input id="platform-setup-key" readOnly autoComplete="off" value={enrollment.secret} className="font-mono" />
        </div>
      </div> : null}
      {!needsEnrollment || enrollment ? <form onSubmit={verify} className="space-y-4">
        {!needsEnrollment ? <fieldset className="flex flex-wrap gap-2"><legend className="mb-2 text-sm font-medium">Verification method</legend>
          <Button type="button" variant={factor === "code" ? "primary" : "outline"} aria-pressed={factor === "code"} onClick={() => { setFactor("code"); setCode(""); }}>Authenticator</Button>
          <Button type="button" variant={factor === "recovery" ? "primary" : "outline"} aria-pressed={factor === "recovery"} onClick={() => { setFactor("recovery"); setCode(""); }}>Recovery code</Button>
        </fieldset> : null}
        <div className="space-y-2"><Label htmlFor="platform-mfa-code">{factor === "code" ? "Six-digit code" : "Recovery code"}</Label>
          <Input id="platform-mfa-code" autoComplete="one-time-code" inputMode={factor === "code" ? "numeric" : "text"}
            pattern={factor === "code" ? "[0-9]{6}" : undefined} minLength={factor === "code" ? 6 : 8} maxLength={factor === "code" ? 6 : 64}
            value={code} required onChange={(event) => setCode(event.target.value)} disabled={pending} />
        </div>
        <Button type="submit" disabled={pending}>{pending ? "Verifying..." : "Verify MFA"}</Button>
      </form> : null}
      {error ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">{error}</p> : null}
    </section>
  );
}
