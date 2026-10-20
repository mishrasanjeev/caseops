import type { Metadata } from "next";

import { PlatformAdmins } from "@/components/platform/PlatformAdmins";

export const metadata: Metadata = { title: "Report administrators" };

export default function PlatformAdminsPage() {
  return <PlatformAdmins />;
}
