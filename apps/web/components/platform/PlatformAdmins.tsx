"use client";

import { UserMinus, UserPlus } from "lucide-react";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { ConsoleError, consoleErrorMessage, platformApi } from "@/lib/platform/client";
import type { ConsoleAdmin } from "@/lib/platform/schemas";
import { usePlatformSession } from "@/lib/platform/session";
import { usePlatformLoad } from "@/lib/platform/use-load";

import { PlatformGate } from "./PlatformGate";
import { PlatformPagination } from "./PlatformPagination";
import { PlatformShell } from "./PlatformShell";

const delivery = { pending: "Invitation pending. No delivery is confirmed.", accepted: "Mail provider accepted the invitation. Inbox delivery is not confirmed.", failed: "Invitation delivery failed.", outcome_unknown: "Invitation delivery outcome is unknown. Do not resend without checking its state." };

function AdminDirectory() {
  const session = usePlatformSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const load = useCallback((signal: AbortSignal) => platformApi.admins(cursor, signal), [cursor]);
  const result = usePlatformLoad(load);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<ConsoleAdmin | null>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unconfirmedEmail, setUnconfirmedEmail] = useState<string | null>(null);
  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || email.trim().toLowerCase() === unconfirmedEmail) return;
    setPending(true); setError(null); setNotice(null);
    try {
      const response = await platformApi.invite({ email: email.trim(), full_name: name.trim() });
      setNotice(delivery[response.delivery_status]);
      if (response.delivery_status === "outcome_unknown" || response.delivery_status === "pending") setUnconfirmedEmail(email.trim().toLowerCase());
      else { setEmail(""); setName(""); }
      result.reload();
    } catch (failure) {
      setError(consoleErrorMessage(failure));
      if (!(failure instanceof ConsoleError) || failure.kind === "unavailable") setUnconfirmedEmail(email.trim().toLowerCase());
    }
    finally { setPending(false); }
  }
  async function revoke(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || pending) return;
    setPending(true); setError(null); setNotice(null);
    try { await platformApi.revoke(selected.id, reason.trim()); setNotice("Administrator access revoked."); setSelected(null); setReason(""); result.reload(); }
    catch (failure) { setError(consoleErrorMessage(failure)); }
    finally { setPending(false); }
  }
  return <div className="min-w-0 space-y-6">
    <h1 className="text-2xl font-bold">Report administrators</h1>
    <form onSubmit={invite} aria-label="Invite report administrator" className="grid min-w-0 gap-4 border-y border-[var(--color-line)] py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
      <div className="space-y-2"><Label htmlFor="admin-invite-name">Full name</Label><Input id="admin-invite-name" autoComplete="off" maxLength={255} required value={name} onChange={(event) => setName(event.target.value)} disabled={pending} /></div>
      <div className="space-y-2"><Label htmlFor="admin-invite-email">Email</Label><Input id="admin-invite-email" autoComplete="off" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} disabled={pending} /></div>
      <Button type="submit" disabled={pending || email.trim().toLowerCase() === unconfirmedEmail}><UserPlus className="h-4 w-4" aria-hidden />Invite viewer</Button>
    </form>
    {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-[var(--color-danger-500)]">{error}</p> : null}
    {result.pending ? <p role="status">Loading administrators...</p> : null}
    {result.error ? <p role="alert">{result.error}</p> : null}
    {result.data ? <div className="relative min-w-0 overflow-x-auto" tabIndex={0} role="region" aria-label="Administrator directory"><table className="w-full min-w-[40rem] text-left text-sm">
      <thead className="border-b border-[var(--color-line)]"><tr>{["Name", "Email", "Role", "Status", "Access"].map((label) => <th key={label} scope="col" className="p-3">{label}</th>)}</tr></thead>
      <tbody>{result.data.items.map((row) => <tr key={row.id} className="border-b border-[var(--color-line)]">
        <td className="max-w-56 break-words p-3">{row.full_name}</td><td className="max-w-64 break-all p-3">{row.email}</td><td className="p-3">{row.role}</td><td className="p-3">{row.status}</td>
        <td className="p-3"><Button type="button" variant="outline" size="sm" disabled={pending || row.role !== "viewer" || row.status === "revoked" || row.id === session.auth?.admin?.id} onClick={() => { setSelected(row); setReason(""); }}><UserMinus className="h-4 w-4" aria-hidden />Revoke</Button></td>
      </tr>)}{!result.data.items.length ? <tr><td colSpan={5} className="p-6 text-[var(--color-mute)]">No administrators on this page.</td></tr> : null}</tbody>
    </table></div> : null}
    <PlatformPagination page={cursors.length - 1} pending={result.pending} hasNext={Boolean(result.data?.next_cursor)} onPrevious={() => setCursors((old) => old.slice(0, -1))} onNext={() => { if (result.data?.next_cursor) setCursors((old) => [...old, result.data!.next_cursor]); }} />
    {selected ? <form aria-label="Revoke administrator access" onSubmit={revoke} className="max-w-xl space-y-4 border-y border-[var(--color-line)] py-5">
      <h2 className="text-lg font-bold">Revoke {selected.full_name}</h2>
      <div className="space-y-2"><Label htmlFor="admin-revoke-reason">Reason</Label><Textarea id="admin-revoke-reason" required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} disabled={pending} /></div>
      <div className="flex flex-wrap gap-3"><Button type="submit" disabled={pending}>Revoke access</Button><Button type="button" variant="outline" disabled={pending} onClick={() => setSelected(null)}>Cancel</Button></div>
    </form> : null}
  </div>;
}

export function PlatformAdmins() {
  return <PlatformShell><PlatformGate managerOnly><AdminDirectory /></PlatformGate></PlatformShell>;
}
