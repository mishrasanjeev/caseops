import type { Metadata } from "next";

import { PlatformAccountLink } from "@/components/platform/PlatformAccountLink";
import { PlatformLinkBoundary } from "@/components/platform/PlatformLinkBoundary";

export const metadata: Metadata = { title: "Accept report administrator invitation" };
export default function PlatformSetupPage() {
  return <PlatformLinkBoundary><PlatformAccountLink mode="setup" /></PlatformLinkBoundary>;
}
