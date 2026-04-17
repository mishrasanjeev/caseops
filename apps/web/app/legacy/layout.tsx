import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./legacy.css";

export const metadata: Metadata = {
  title: { absolute: "Legacy workspace — CaseOps" },
  description: "Founder-stage CaseOps console, preserved while the new cockpit is rolling out.",
  robots: { index: false, follow: false },
};

export default function LegacyLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
