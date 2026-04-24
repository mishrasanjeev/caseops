"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, MailCheck, Send } from "lucide-react";
import Link from "next/link";
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
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import { requestPortalMagicLink } from "@/lib/api/portal";

export default function PortalSignInPage() {
  const [companySlug, setCompanySlug] = useState("");
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      requestPortalMagicLink({
        companySlug: companySlug.trim().toLowerCase(),
        email: email.trim().toLowerCase(),
      }),
    onSuccess: (result) => {
      setSubmitted(true);
      // Non-prod debug helper: deep-link straight to verify so smoke
      // tests don't have to scrape email. Prod returns null here and
      // the real magic link arrives via email.
      if (result.debug_token) {
        toast.success("Sign-in link generated. Redirecting…");
        const t = encodeURIComponent(result.debug_token);
        window.location.href = `/portal/verify?token=${t}`;
        return;
      }
      toast.success("Check your inbox for a sign-in link.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not request a sign-in link."));
    },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (companySlug.trim().length < 2 || !email.includes("@")) {
      toast.error("Workspace and email are required.");
      return;
    }
    mutation.mutate();
  };

  return (
    <main className="flex min-h-screen flex-col bg-[var(--color-bg)]">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <span className="text-sm font-semibold tracking-tight text-[var(--color-ink)]">
          CaseOps · Portal
        </span>
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
              Sign in to your workspace portal
            </CardTitle>
            <CardDescription>
              Enter your firm's workspace handle and your email. We'll send
              you a one-time sign-in link valid for 30 minutes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {submitted ? (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
                  <MailCheck className="h-6 w-6" aria-hidden />
                </span>
                <p className="text-sm text-[var(--color-ink-2)]">
                  If the email is registered with this workspace, a
                  sign-in link is on its way.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSubmitted(false)}
                  data-testid="portal-signin-restart"
                >
                  Send another link
                </Button>
              </div>
            ) : (
              <form className="space-y-4" onSubmit={submit}>
                <div>
                  <Label htmlFor="portal-company-slug">
                    Workspace handle
                  </Label>
                  <Input
                    id="portal-company-slug"
                    autoComplete="organization"
                    placeholder="e.g. aster-legal"
                    value={companySlug}
                    onChange={(e) => setCompanySlug(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <Label htmlFor="portal-email">Email</Label>
                  <Input
                    id="portal-email"
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <Button
                  type="submit"
                  className="w-full"
                  disabled={mutation.isPending}
                  data-testid="portal-signin-submit"
                >
                  <Send className="mr-1.5 h-4 w-4" />
                  {mutation.isPending ? "Sending…" : "Email me a link"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
        <p className="mt-4 text-center text-xs text-[var(--color-mute)]">
          Internal team member?{" "}
          <Link
            href="/sign-in"
            className="font-medium text-[var(--color-brand-700)] hover:underline"
          >
            Sign in to the workspace app
          </Link>
        </p>
      </section>
    </main>
  );
}
