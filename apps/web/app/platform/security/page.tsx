import type { Metadata } from "next";

import { PlatformSecurity } from "@/components/platform/PlatformSecurity";

export const metadata: Metadata = { title: "Platform account security" };

export default function PlatformSecurityPage() {
  return <PlatformSecurity />;
}
