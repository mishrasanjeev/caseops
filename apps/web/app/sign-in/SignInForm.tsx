"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Logo } from "@/components/marketing/Logo";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { signIn } from "@/lib/api/auth";
import { apiErrorMessage } from "@/lib/api/config";
import { storeSession } from "@/lib/session";

import { NewWorkspaceForm } from "./NewWorkspaceForm";

const schema = z.object({
  companySlug: z
    .string()
    .min(2, "Enter your company slug.")
    .max(80)
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, digits, and hyphens only."),
  email: z.string().email("Enter a valid work email."),
  password: z.string().min(1, "Password is required."),
});

type FormValues = z.infer<typeof schema>;

export function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const nextPath = params.get("next") ?? "/app";
  const initialTab = params.get("tab") === "new" ? "new" : "signin";
  const [tab, setTab] = useState<"signin" | "new">(initialTab);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { companySlug: "", email: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      signIn({
        email: values.email,
        password: values.password,
        companySlug: values.companySlug,
      }),
    onSuccess: (session) => {
      storeSession(session);
      toast.success(`Welcome back, ${session.user.full_name.split(" ")[0]}`);
      router.replace(nextPath);
    },
    onError: (err) => {
      const message =
        apiErrorMessage(err, "We could not sign you in. Please try again.");
      toast.error(message);
    },
  });

  return (
    <main className="flex min-h-screen flex-col bg-[var(--color-bg)]">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <Logo />
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to site
        </Link>
      </header>

      <section className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 pb-16">
        <Card>
          <CardHeader>
            <CardTitle as="h1" className="text-lg">
              {tab === "new" ? "Create your CaseOps workspace" : "Sign in to your workspace"}
            </CardTitle>
            <CardDescription>
              {tab === "new"
                ? "Set up a workspace for your firm. You'll be the owner and can invite the rest of the team afterwards."
                : "Use your CaseOps credentials. You can find your company slug on the workspace URL or your invite email."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs
              value={tab}
              onValueChange={(next) => setTab(next as "signin" | "new")}
              className="w-full"
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="signin">Sign in</TabsTrigger>
                <TabsTrigger value="new" data-testid="tab-new-workspace">
                  New workspace
                </TabsTrigger>
              </TabsList>

              <TabsContent value="signin">
                <form
                  className="flex flex-col gap-4"
                  onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                  noValidate
                  aria-label="Sign in"
                >
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
                        {...form.register("email")}
                      />
                    )}
                  </FieldGroup>

                  <FieldGroup
                    id="password"
                    label="Password"
                    error={form.formState.errors.password?.message}
                  >
                    {({ invalid, describedBy }) => (
                      <PasswordInput
                        id="password"
                        autoComplete="current-password"
                        aria-invalid={invalid || undefined}
                        aria-describedby={describedBy}
                        {...form.register("password")}
                      />
                    )}
                  </FieldGroup>

                  <Button
                    type="submit"
                    size="lg"
                    disabled={mutation.isPending}
                    className="mt-2 w-full"
                  >
                    {mutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Signing in…
                      </>
                    ) : (
                      "Sign in"
                    )}
                  </Button>
                </form>
              </TabsContent>

              <TabsContent value="new">
                <NewWorkspaceForm />
              </TabsContent>
            </Tabs>
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
