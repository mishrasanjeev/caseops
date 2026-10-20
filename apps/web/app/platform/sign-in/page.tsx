import type { Metadata } from "next";

import { PlatformSignIn } from "@/components/platform/PlatformSignIn";

export const metadata: Metadata = { title: "Platform sign in" };

export default function PlatformSignInPage() {
  return <PlatformSignIn />;
}
