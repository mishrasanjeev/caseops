"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { platformApi } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

import { PlatformSignInForm } from "./PlatformSignInForm";
import { PlatformResendInvitation } from "./PlatformResendInvitation";

export function PlatformSignIn() {
  const session = usePlatformSession();
  const router = useRouter();
  return <PlatformSignInForm onSignIn={async (input) => {
      const auth = await platformApi.login(input);
      session.accept(auth);
      router.replace(auth.state === "authenticated" ? "/platform/reports" : "/platform/security");
    }} footer={<div className="space-y-5 text-sm">
      <Link href="/platform/reset-password" prefetch={false} className="underline">Forgot password?</Link>
      <details className="border-t border-[var(--color-line)] pt-4"><summary className="cursor-pointer font-medium">Resend setup email</summary><div className="pt-4"><PlatformResendInvitation /></div></details>
    </div>} />;
}
