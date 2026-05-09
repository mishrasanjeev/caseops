import { Suspense } from "react";

import { AccountSetupForm } from "./AccountSetupForm";

// useSearchParams in the form requires Suspense + dynamic rendering
// (Next.js 14+ prerender constraint). Mirrors the sign-in page
// pattern at apps/web/app/sign-in/page.tsx.
export const dynamic = "force-dynamic";

export default function AccountSetupPage() {
  return (
    <Suspense>
      <AccountSetupForm />
    </Suspense>
  );
}
