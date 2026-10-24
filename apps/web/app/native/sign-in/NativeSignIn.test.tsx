import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NativeSignIn } from './NativeSignIn';

const mocks = vi.hoisted(() => ({ query: '', api: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(mocks.query) }));
vi.mock('@/lib/api/client', () => ({ apiRequest: mocks.api }));
vi.mock('@/components/marketing/Logo', () => ({ Logo: () => <span>CaseOps</span> }));
const identity = { user: { id: 'person-one', full_name: 'Example Person', email: 'person@example.test' }, company: { id: 'company-one', name: 'Example Legal', slug: 'fixture-legal' }, membership: { id: 'membership-one' }, capabilities: [] };
const query = new URLSearchParams({ code_challenge: 'a'.repeat(43), state: 'b'.repeat(64), platform: 'ios', redirect_uri: 'caseops://oauth/callback' }).toString();

describe('native browser handoff consent', () => {
  beforeEach(() => { mocks.query = query; mocks.api.mockReset(); });

  it('rejects malformed input before requesting or exposing the browser identity', async () => {
    mocks.query += '&redirect_uri=https://attacker.test';
    render(<NativeSignIn />);
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid or incomplete');
    expect(mocks.api).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Connect app' })).not.toBeInTheDocument();
  });

  it('names the actual person and workspace and does not authorize on page load', async () => {
    mocks.api.mockResolvedValue(identity);
    render(<NativeSignIn />);
    expect(await screen.findByText('person@example.test')).toBeVisible();
    expect(screen.getByText('Example Legal / fixture-legal')).toBeVisible();
    expect(mocks.api.mock.calls.map(call => call[0])).toEqual(['/api/auth/me']);
    expect(screen.getByRole('button', { name: 'Connect app' })).toBeEnabled();
  });

  it('offers the exact safe return path after anonymous browser authentication', async () => {
    mocks.api.mockRejectedValue({ name: 'ApiError', status: 401, detail: 'Sign in.', data: null });
    render(<NativeSignIn />);
    const link = await screen.findByRole('link', { name: 'Sign in securely' });
    expect(link).toHaveAttribute('href', `/sign-in?next=${encodeURIComponent(`/native/sign-in?${query}`)}`);
    expect(screen.queryByRole('button', { name: 'Connect app' })).not.toBeInTheDocument();
  });

  it('does not follow a forged returned redirect and preserves a visible recovery error', async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({ code: 'c'.repeat(43), state: 'b'.repeat(64), redirect_uri: 'https://attacker.test' });
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect app' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be completed');
    expect(mocks.api.mock.calls.filter(call => call[0] === '/api/auth/native/authorize')).toHaveLength(1);
    expect(mocks.api.mock.calls[1][1]).toMatchObject({ method: 'POST', body: { state: 'b'.repeat(64), platform: 'ios' } });
  });

  it('deduplicates a double-click and renders typed errors without class-identity assumptions', async () => {
    let fail: (error: unknown) => void = () => {};
    mocks.api.mockResolvedValueOnce(identity).mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    render(<NativeSignIn />);
    const button = await screen.findByRole('button', { name: 'Connect app' });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.api.mock.calls.filter(call => call[0] === '/api/auth/native/authorize')).toHaveLength(1);
    fail({ name: 'ApiError', status: 503, detail: 'Native sign-in is not enabled for this environment.', data: null });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('not enabled for this environment'));
  });
});
