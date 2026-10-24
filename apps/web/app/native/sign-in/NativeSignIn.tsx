'use client';

import { ArrowRight, Loader2, Smartphone } from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Logo } from '@/components/marketing/Logo';
import { Button } from '@/components/ui/Button';
import { apiRequest } from '@/lib/api/client';
import { isApiErrorShape } from '@/lib/api/config';
import type { AuthContext } from '@/lib/api/schema-types';
import { parseNativeAuthorization } from '@/lib/native-authorization';

export function NativeSignIn() {
  const params = useSearchParams();
  const parsed = parseNativeAuthorization(params.toString());
  const query = params.toString();
  const next = `/native/sign-in?${query}`;
  const [context, setContext] = useState<AuthContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    if (!parseNativeAuthorization(query)) { setLoading(false); return; }
    const controller = new AbortController();
    apiRequest<AuthContext>('/api/auth/me', { signal: controller.signal }).then(setContext).catch(cause => {
      if (controller.signal.aborted) return;
      if (isApiErrorShape(cause) && cause.status === 401) setSignedOut(true);
      else setError('Your session could not be verified. Sign in and complete the required security checks.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query]);

  async function connect() {
    if (!parsed || !context || submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    try {
      const response = await apiRequest<{ code: string; state: string; redirect_uri: string }>('/api/auth/native/authorize', {
        method: 'POST', body: parsed,
      });
      if (response.state !== parsed.state || response.redirect_uri !== parsed.redirect_uri || !/^[A-Za-z0-9_-]{32,256}$/.test(response.code)) {
        throw new Error('Invalid native handoff response.');
      }
      const callback = new URL(response.redirect_uri);
      callback.searchParams.set('code', response.code);
      callback.searchParams.set('state', response.state);
      window.location.assign(callback.href);
    } catch (cause) {
      setError(isApiErrorShape(cause) ? cause.detail : 'The app connection could not be completed. Return to the app and start sign-in again.');
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return <main className="min-h-screen bg-[var(--color-bg)] px-6 py-8 text-[var(--color-ink)]">
    <div className="mx-auto max-w-md space-y-6">
      <Logo />
      <Smartphone aria-hidden className="h-6 w-6 text-[var(--color-accent)]" />
      <h1 className="text-2xl font-semibold">Connect the CaseOps app</h1>
      {!parsed ? <p role="alert">This sign-in request is invalid or incomplete. Open CaseOps on your phone and start again.</p> : <>
        {loading && <p role="status" className="flex items-center gap-2"><Loader2 aria-hidden className="h-4 w-4 animate-spin" />Checking your workspace</p>}
        {error && <p role="alert" className="text-[var(--color-danger)]">{error}</p>}
        {context && <>
          <dl className="space-y-3 border-y border-[var(--color-line)] py-5">
            <div><dt className="text-sm text-[var(--color-mute)]">Account</dt><dd className="break-words"><span className="block">{context.user.full_name}</span><span className="block">{context.user.email}</span></dd></div>
            <div><dt className="text-sm text-[var(--color-mute)]">Workspace</dt><dd className="break-words">{context.company.name} / {context.company.slug}</dd></div>
          </dl>
          <p>Connect this account to the {parsed.platform === 'ios' ? 'iPhone' : 'Android'} app. The app uses your current workspace permissions.</p>
          <Button className="min-h-12 w-full" disabled={pending} onClick={() => void connect()}>
            {pending ? <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" /> : <ArrowRight aria-hidden className="mr-2 h-4 w-4" />}Connect app
          </Button>
        </>}
        {(signedOut || error || context) && <Link className="inline-flex min-h-12 items-center underline" href={`/sign-in?next=${encodeURIComponent(next)}`}>{context ? 'Use another account' : 'Sign in securely'}</Link>}
      </>}
    </div>
  </main>;
}
