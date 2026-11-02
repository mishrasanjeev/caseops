import type { Metadata } from 'next';
import { Suspense } from 'react';
import { NativeSignIn } from './NativeSignIn';
import { loadNativeLinkPolicy } from '@/lib/native-link-policy.server';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = {
  title: 'Connect the CaseOps app',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export default function NativeSignInPage() {
  return <Suspense><NativeSignIn policy={loadNativeLinkPolicy()} /></Suspense>;
}
