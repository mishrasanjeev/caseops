"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { completeAccountSetup } from "@/lib/api/auth";
import { apiErrorMessage } from "@/lib/api/config";
import { storeSession } from "@/lib/session";

// Backend `_complete_account_token` enforces the password policy and
// returns 400 if it fails; we keep a baseline 12-char client-side
// check (mirrors `AccountSetupCompleteRequest.password.min_length`)
// so the form refuses obviously short input before the round-trip.
const schema = z
  .object({
    password: z.string().min(12, "Use at least 12 characters."),
    confirmPassword: z.string(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "Passwords don't match.",
  });

type FormValues = z.infer<typeof schema>;

export function AccountSetupForm() {
  const router = useRouter();
  const params = useSearchParams();
  // The token is read from the URL into a local constant. We never
  // render it back to the user, never log it, and never put it in any
  // analytics/error-tracking payload — `apiErrorMessage` only sees
  // the server's `detail` text.
  const token = (params.get("token") ?? "").trim();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirmPassword: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      completeAccountSetup({ token, password: values.password }),
    onSuccess: (session) => {
      storeSession(session);
      toast.success(
        `Welcome to CaseOps, ${session.user.full_name.split(" ")[0]}.`,
      );
      router.replace("/app");
    },
    onError: (err) => {
      const message = apiErrorMessage(
        err,
        "We could not complete account setup. The link may be invalid, expired, or already used. Ask your admin to resend the invite.",
      );
      toast.error(message);
    },
  });

  return (
    <main className="flex min-h-screen flex-col bg-[var(--color-bg)]">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <Logo />
        <Link
          href="/sign-in"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Sign in instead
        </Link>
      </header>

      <section className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 pb-16">
        <Card>
          <CardHeader>
            <CardTitle as="h1" className="text-lg">
              Set up your CaseOps account
            </CardTitle>
            <CardDescription>
              Choose a password to finish setting up your account. Setup links
              expire 24 hours after they're sent and can only be used once.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!token ? (
              <MissingTokenState
                title="This setup link is missing a token."
                body="The link in your email may have been broken by your email client. Ask your admin to resend the invite, or paste the full URL from the email into your browser address bar."
              />
            ) : mutation.isError ? (
              <SubmitErrorState
                error={mutation.error}
                onDismiss={() => mutation.reset()}
              />
            ) : (
              <form
                className="flex flex-col gap-4"
                onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                noValidate
                aria-label="Set up your account"
              >
                <FieldGroup
                  id="password"
                  label="New password"
                  error={form.formState.errors.password?.message}
                >
                  {({ invalid, describedBy }) => (
                    <PasswordInput
                      id="password"
                      autoComplete="new-password"
                      aria-invalid={invalid || undefined}
                      aria-describedby={describedBy}
                      data-testid="account-setup-password"
                      {...form.register("password")}
                    />
                  )}
                </FieldGroup>

                <FieldGroup
                  id="confirm-password"
                  label="Confirm password"
                  error={form.formState.errors.confirmPassword?.message}
                >
                  {({ invalid, describedBy }) => (
                    <PasswordInput
                      id="confirm-password"
                      autoComplete="new-password"
                      aria-invalid={invalid || undefined}
                      aria-describedby={describedBy}
                      data-testid="account-setup-confirm"
                      {...form.register("confirmPassword")}
                    />
                  )}
                </FieldGroup>

                <Button
                  type="submit"
                  size="lg"
                  disabled={mutation.isPending}
                  className="mt-2 w-full"
                  data-testid="account-setup-submit"
                >
                  {mutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Activating
                      account…
                    </>
                  ) : (
                    "Activate account"
                  )}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </section>
    </main>
  );
}

function MissingTokenState({ title, body }: { title: string; body: string }) {
  return (
    <div
      className="flex flex-col gap-3 text-sm text-[var(--color-ink-2)]"
      role="alert"
      data-testid="account-setup-missing-token"
    >
      <p className="font-medium text-[var(--color-ink)]">{title}</p>
      <p className="leading-relaxed text-[var(--color-mute)]">{body}</p>
      <div className="mt-1">
        <Link
          href="/sign-in"
          className="text-sm font-medium text-[var(--color-brand-700)] underline-offset-4 hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}

function SubmitErrorState({
  error,
  onDismiss,
}: {
  error: unknown;
  onDismiss: () => void;
}) {
  const message = apiErrorMessage(
    error,
    "We could not complete account setup. The link may be invalid, expired, or already used. Ask your admin to resend the invite.",
  );
  return (
    <div
      className="flex flex-col gap-3 text-sm text-[var(--color-ink-2)]"
      role="alert"
      data-testid="account-setup-submit-error"
    >
      <p className="font-medium text-[var(--color-ink)]">
        We could not complete account setup.
      </p>
      <p className="leading-relaxed text-[var(--color-mute)]">{message}</p>
      <div className="mt-1 flex items-center gap-3">
        <button
          type="button"
          onClick={onDismiss}
          className="text-sm font-medium text-[var(--color-brand-700)] underline-offset-4 hover:underline"
          data-testid="account-setup-error-retry"
        >
          Try again
        </button>
        <Link
          href="/sign-in"
          className="text-sm font-medium text-[var(--color-mute)] underline-offset-4 hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}

function FieldGroup({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: (state: { invalid: boolean; describedBy: string | undefined }) => React.ReactNode;
}) {
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({ invalid: Boolean(error), describedBy: errorId })}
      {error ? (
        <p
          id={errorId}
          className="text-xs text-[var(--color-danger-500,#c53030)]"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
