import type { Metadata } from "next";

import { PlatformReports } from "@/components/platform/PlatformReports";

export const metadata: Metadata = { title: "Platform reports" };

export default function PlatformReportsPage() {
  return <PlatformReports />;
}
