"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  completeMfaStepUp,
  disableMfa,
  fetchAccountSecurity,
  regenerateMfaRecoveryCodes,
  startMfaEnrollment,
  verifyMfaEnrollment,
} from "@/lib/api/endpoints";

export default function AccountSecurityPage() {
  const queryClient = useQueryClient();
  const [verifyCode, setVerifyCode] = useState("");
  const [stepUpCode, setStepUpCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableReason, setDisableReason] = useState("User requested MFA reset");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const status = useQuery({
    queryKey: ["account-security"],
    queryFn: fetchAccountSecurity,
  });
  const enroll = useMutation({
    mutationFn: startMfaEnrollment,
  });
  const verify = useMutation({
    mutationFn: verifyMfaEnrollment,
    onSuccess: (data) => {
      setRecoveryCodes(data.recovery_codes);
      queryClient.invalidateQueries({ queryKey: ["account-security"] });
      toast.success("MFA enrolled.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not verify MFA code.")),
  });
  const stepUp = useMutation({
    mutationFn: completeMfaStepUp,
    onSuccess: () => {
      setStepUpCode("");
      queryClient.invalidateQueries({ queryKey: ["account-security"] });
      toast.success("Step-up verified.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not verify step-up.")),
  });
  const regenerate = useMutation({
    mutationFn: regenerateMfaRecoveryCodes,
    onSuccess: (data) => {
      setRecoveryCodes(data.recovery_codes);
      queryClient.invalidateQueries({ queryKey: ["account-security"] });
      toast.success("Recovery codes regenerated.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not regenerate codes.")),
  });
  const disable = useMutation({
    mutationFn: disableMfa,
    onSuccess: () => {
      setDisableCode("");
      queryClient.invalidateQueries({ queryKey: ["account-security"] });
      toast.success("MFA disabled.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not disable MFA.")),
  });

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <PageHeader
        eyebrow="Account"
        title="Security"
        description="Manage account MFA and recent step-up authorization."
      />

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">MFA status</CardTitle>
            <CardDescription>
              TOTP protects platform administration and other high-risk actions.
            </CardDescription>
          </div>
          <ShieldCheck className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {status.isPending ? (
            <div className="flex items-center gap-2 text-[var(--color-mute)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Loading security status...
            </div>
          ) : null}
          {status.data ? (
            <>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">MFA</span>
                <span className="font-medium">{status.data.mfa_status}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Required</span>
                <span className="font-medium">{status.data.mfa_required ? "Yes" : "No"}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Recovery codes</span>
                <span className="font-medium">{status.data.recovery_codes_remaining}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-[var(--color-mute)]">Step-up expires</span>
                <span className="font-medium">
                  {status.data.recent_step_up_expires_at ?? "-"}
                </span>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Enroll TOTP</CardTitle>
          <CardDescription>Use an authenticator app, then verify the six-digit code.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button type="button" onClick={() => enroll.mutate()} disabled={enroll.isPending}>
            <KeyRound className="h-4 w-4" aria-hidden />
            Start enrollment
          </Button>
          {enroll.data ? (
            <div className="grid gap-4 md:grid-cols-[240px_1fr]">
              <div
                className="h-60 w-60 overflow-hidden rounded border border-[var(--color-line)] bg-white"
                dangerouslySetInnerHTML={{ __html: enroll.data.qr_svg }}
              />
              <div className="space-y-3">
                <div className="font-mono text-sm">{enroll.data.secret}</div>
                <Input
                  aria-label="MFA verification code"
                  placeholder="123456"
                  value={verifyCode}
                  onChange={(event) => setVerifyCode(event.target.value)}
                />
                <Button
                  type="button"
                  onClick={() => verify.mutate(verifyCode)}
                  disabled={verify.isPending || verifyCode.length < 6}
                >
                  Verify
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Step-up</CardTitle>
          <CardDescription>Complete a recent MFA challenge for protected actions.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          <Input
            aria-label="Step-up code"
            placeholder="Authenticator or recovery code"
            value={stepUpCode}
            onChange={(event) => setStepUpCode(event.target.value)}
          />
          <Button
            type="button"
            onClick={() => stepUp.mutate({ code: stepUpCode, purpose: "step_up" })}
            disabled={stepUp.isPending || stepUpCode.length < 6}
          >
            Verify step-up
          </Button>
        </CardContent>
      </Card>

      {recoveryCodes.length ? (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Recovery codes</CardTitle>
            <CardDescription>These codes are shown once and are single-use.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {recoveryCodes.map((code) => (
              <div key={code} className="rounded border border-[var(--color-line)] p-2 font-mono text-sm">
                {code}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div>
        <Button
          type="button"
          variant="outline"
          onClick={() => regenerate.mutate()}
          disabled={regenerate.isPending}
        >
          Regenerate recovery codes
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Disable MFA</CardTitle>
          <CardDescription>Disabling MFA requires a valid challenge and audit reason.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Input
            aria-label="MFA disable code"
            placeholder="Authenticator or recovery code"
            value={disableCode}
            onChange={(event) => setDisableCode(event.target.value)}
          />
          <Input
            aria-label="MFA disable reason"
            value={disableReason}
            onChange={(event) => setDisableReason(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => disable.mutate({ code: disableCode, reason: disableReason })}
            disabled={
              disable.isPending || disableCode.length < 6 || disableReason.trim().length < 8
            }
          >
            Disable MFA
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
