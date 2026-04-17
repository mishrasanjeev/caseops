import { Suspense } from "react";

import { SignInForm } from "./SignInForm";

export const dynamic = "force-dynamic";

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}
