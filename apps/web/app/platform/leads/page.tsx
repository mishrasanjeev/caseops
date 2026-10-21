import type { Metadata } from "next";

import { PlatformLeads } from "@/components/platform/PlatformLeads";

export const metadata: Metadata = { title: "Platform leads" };

export default function PlatformLeadsPage() {
  return <PlatformLeads />;
}
