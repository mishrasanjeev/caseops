import type { Metadata } from "next";

import { PlatformAccountLink } from "@/components/platform/PlatformAccountLink";
import { PlatformLinkBoundary } from "@/components/platform/PlatformLinkBoundary";

export const metadata: Metadata = { title: "Reset platform password" };
export default function PlatformResetPasswordPage() {
  return <PlatformLinkBoundary><PlatformAccountLink mode="reset" /></PlatformLinkBoundary>;
}
