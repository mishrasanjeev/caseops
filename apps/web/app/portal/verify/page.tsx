"use client";

import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { apiErrorMessage } from "@/lib/api/config";
import { verifyPortalMagicLink } from "@/lib/api/portal";

export default function PortalVerifyPage() {
  const params = useSearchParams();
  const token = params?.get("token") ?? "";
  const router = useRouter();
  const triggered = useRef(false);

  const mutation = useMutation({
    mutationFn: () => verifyPortalMagicLink(token),
    onSuccess: () => {
      router.replace("/portal");
    },
  });

  useEffect(() => {
    if (!token || triggered.current) return;
    triggered.current = true;
    mutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-[var(--color-bg)] px-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle as="h1" className="text-lg">
            Verifying your sign-in link
          </CardTitle>
          <CardDescription>
            One-time, single-use, expires in 30 minutes from when it was
            generated.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!token ? (
            <p className="text-sm text-[var(--color-warn-700)]">
              No token in URL. Open the magic link from your email.
            </p>
          ) : mutation.isError ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-[var(--color-warn-700)]">
                {apiErrorMessage(
                  mutation.error,
                  "This link is invalid or expired.",
                )}
              </p>
              <Button
                variant="outline"
                onClick={() => router.push("/portal/sign-in")}
                data-testid="portal-verify-retry"
              >
                Request a new link
              </Button>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              {mutation.isPending ? "Verifying" : "Loading workspace"}
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
