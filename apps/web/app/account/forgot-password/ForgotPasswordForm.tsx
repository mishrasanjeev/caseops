"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { startPasswordReset } from "@/lib/api/auth";

const SUCCESS_COPY =
  "If an active CaseOps account exists for this workspace, we'll email a reset link.";
const GENERIC_ERROR =
  "We could not request a reset link. Please try again.";

const schema = z.object({
  companySlug: z
    .string()
    .trim()
    .toLowerCase()
    .min(2, "Enter your company slug.")
    .max(80, "Company slug must be 80 characters or fewer.")
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, digits, and hyphens only."),
  email: z
    .string()
    .trim()
    .toLowerCase()
    .email("Enter a valid work email."),
});

type FormValues = z.infer<typeof schema>;

function safeInitialSlug(value: string | null): string {
  const cleaned = (value ?? "").trim().toLowerCase().slice(0, 80);
  return /^[a-z0-9-]*$/.test(cleaned) ? cleaned : "";
}

function safeInitialEmail(value: string | null): string {
  return (value ?? "").trim().toLowerCase().slice(0, 254);
}

export function ForgotPasswordForm() {
  const params = useSearchParams();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      companySlug: safeInitialSlug(params.get("company_slug")),
      email: safeInitialEmail(params.get("email")),
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      startPasswordReset({
        companySlug: values.companySlug,
        email: values.email,
      }),
    onSuccess: () => {
      toast.success(SUCCESS_COPY);
    },
    onError: () => {
      toast.error(GENERIC_ERROR);
    },
  });

  const showSuccess = mutation.isSuccess;
  const showError = mutation.isError;

  return (
    <main className="flex min-h-screen flex-col bg-[var(--color-bg)]">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <Logo />
        <Link
          href="/sign-in"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to sign in
        </Link>
      </header>

      <section className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 pb-16">
        <Card>
          <CardHeader>
            <CardTitle as="h1" className="text-lg">
              Request a password reset
            </CardTitle>
            <CardDescription>
              Enter your workspace and work email. Reset links expire after 60
              minutes and can only be used once.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-4"
              onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
              noValidate
              aria-label="Request a password reset"
            >
              {showSuccess ? (
                <p
                  className="rounded-md border border-[var(--color-success-300,#9ae6b4)] bg-[var(--color-success-50,#f0fff4)] px-3 py-2 text-sm leading-relaxed text-[var(--color-success-700,#276749)]"
                  role="status"
                  data-testid="forgot-password-success"
                >
                  {SUCCESS_COPY}
                </p>
              ) : null}

              {showError ? (
                <p
                  className="rounded-md border border-[var(--color-danger-200,#fed7d7)] bg-[var(--color-danger-50,#fff5f5)] px-3 py-2 text-sm leading-relaxed text-[var(--color-danger-700,#9b2c2c)]"
                  role="alert"
                  data-testid="forgot-password-error"
                >
                  {GENERIC_ERROR}
                </p>
              ) : null}

              <FieldGroup
                id="company-slug"
                label="Company slug"
                error={form.formState.errors.companySlug?.message}
              >
                {({ invalid, describedBy }) => (
                  <Input
                    id="company-slug"
                    autoComplete="organization"
                    placeholder="aster-legal"
                    aria-invalid={invalid || undefined}
                    aria-describedby={describedBy}
                    data-testid="forgot-password-company-slug"
                    {...form.register("companySlug")}
                  />
                )}
              </FieldGroup>

              <FieldGroup
                id="email"
                label="Work email"
                error={form.formState.errors.email?.message}
              >
                {({ invalid, describedBy }) => (
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="you@firm.in"
                    aria-invalid={invalid || undefined}
                    aria-describedby={describedBy}
                    data-testid="forgot-password-email"
                    {...form.register("email")}
                  />
                )}
              </FieldGroup>

              <Button
                type="submit"
                size="lg"
                disabled={mutation.isPending}
                className="mt-2 w-full"
                data-testid="forgot-password-submit"
              >
                {mutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Sending link...
                  </>
                ) : showSuccess ? (
                  "Resend reset link"
                ) : (
                  "Request reset link"
                )}
              </Button>

              <Link
                href="/sign-in"
                className="text-center text-sm font-medium text-[var(--color-brand-700)] underline-offset-4 hover:underline"
              >
                Back to sign in
              </Link>
            </form>
          </CardContent>
        </Card>
      </section>
    </main>
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
