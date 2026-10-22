"use client";

import { Mail, RefreshCw, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { ConsoleError, consoleErrorMessage, platformApi } from "@/lib/platform/client";
import type { ConsoleManagedAdmin } from "@/lib/platform/schemas";
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
  const load = useCallback((signal: AbortSignal) => platformApi.managedAdmins(cursor, signal), [cursor]);
  const result = usePlatformLoad(load);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<{ admin: ConsoleManagedAdmin; action: "revoke" | "remove" } | null>(null);
  const emailInput = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unconfirmedEmail, setUnconfirmedEmail] = useState<string | null>(null);
  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || email.trim().toLowerCase() === unconfirmedEmail) return;
    setPending(true); setError(null); setNotice(null);
    try {
      const response = await platformApi.invite({ email: email.trim(), full_name: name.trim(), reinvite_revoked: true });
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
  async function changeAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || pending) return;
    setPending(true); setError(null); setNotice(null);
    try {
      const { admin, action } = selected;
      if (action === "remove") await platformApi.removeAdmin(admin.id, reason.trim(), admin.version);
      else await platformApi.revoke(admin.id, reason.trim(), admin.version);
      setNotice(action === "remove" ? "Report administrator removed. Tenant accounts and audit history were retained." : "Administrator access revoked.");
      setSelected(null); setReason(""); result.reload();
    }
    catch (failure) { setError(consoleErrorMessage(failure)); }
    finally { setPending(false); }
  }
  async function resend(admin: ConsoleManagedAdmin) {
    if (pending || !admin.can_manage || admin.status !== "pending") return;
    setPending(true); setError(null); setNotice(null);
    try {
      const response = await platformApi.resendAdminInvitation(admin.id, admin.version);
      setNotice(delivery[response.delivery_status]); result.reload();
    } catch (failure) {
      setError(failure instanceof ConsoleError && failure.status === 409
        ? "This invitation is not currently eligible to resend. Reload the directory; if it was sent recently, wait five minutes."
        : consoleErrorMessage(failure));
    } finally { setPending(false); }
  }
  function prepareInvitation(admin: ConsoleManagedAdmin) {
    if (!admin.can_manage || admin.status !== "revoked") return;
    setEmail(admin.email); setName(admin.full_name); setUnconfirmedEmail(null);
    setError(null); setNotice(null); setSelected(null); emailInput.current?.focus();
  }
  return <div className="min-w-0 space-y-6">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-bold">Report administrators</h1>
      <Button type="button" variant="outline" size="sm" className="h-9 w-9 shrink-0 px-0" title="Reload administrators" aria-label="Reload administrators" disabled={pending || result.pending} onClick={() => { setSelected(null); setReason(""); result.reload(); }}><RefreshCw className="h-4 w-4" aria-hidden /></Button>
    </div>
    <form onSubmit={invite} aria-label="Invite report administrator" className="grid min-w-0 gap-4 border-y border-[var(--color-line)] py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
      <div className="space-y-2"><Label htmlFor="admin-invite-name">Full name</Label><Input id="admin-invite-name" autoComplete="off" maxLength={255} required value={name} onChange={(event) => setName(event.target.value)} disabled={pending} /></div>
      <div className="space-y-2"><Label htmlFor="admin-invite-email">Email</Label><Input ref={emailInput} id="admin-invite-email" autoComplete="off" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} disabled={pending} /></div>
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
        <td className="p-3"><div className="flex min-w-0 flex-wrap gap-2">
          {row.status === "pending" ? <Button type="button" variant="outline" size="sm" className="h-8 w-8 shrink-0 px-0" title="Resend invitation" aria-label={`Resend invitation for ${row.full_name}`} disabled={pending || !row.can_manage || row.role !== "viewer" || row.id === session.auth?.admin?.id} onClick={() => void resend(row)}><Mail className="h-4 w-4" aria-hidden /></Button> : null}
          {row.status === "revoked" && row.role === "viewer" ? <Button type="button" variant="outline" size="sm" className="h-8 w-8 shrink-0 px-0" title="Invite again" aria-label={`Invite ${row.full_name} again`} disabled={pending || !row.can_manage || row.id === session.auth?.admin?.id} onClick={() => prepareInvitation(row)}><UserPlus className="h-4 w-4" aria-hidden /></Button> : null}
          <Button type="button" variant="outline" size="sm" disabled={pending || !row.can_manage || row.role !== "viewer" || row.status === "revoked" || row.id === session.auth?.admin?.id} onClick={() => { setSelected({ admin: row, action: "revoke" }); setReason(""); }}><UserMinus className="h-4 w-4" aria-hidden />Revoke</Button>
          <Button type="button" variant="outline" size="sm" className="h-8 w-8 shrink-0 px-0" title="Delete report access" aria-label={`Delete report access for ${row.full_name}`} disabled={pending || !row.can_manage || row.role !== "viewer" || row.id === session.auth?.admin?.id} onClick={() => { setSelected({ admin: row, action: "remove" }); setReason(""); }}><Trash2 className="h-4 w-4" aria-hidden /></Button>
        </div></td>
      </tr>)}{!result.data.items.length ? <tr><td colSpan={5} className="p-6 text-[var(--color-mute)]">No administrators on this page.</td></tr> : null}</tbody>
    </table></div> : null}
    <PlatformPagination page={cursors.length - 1} pending={result.pending} hasNext={Boolean(result.data?.next_cursor)} onPrevious={() => setCursors((old) => old.slice(0, -1))} onNext={() => { if (result.data?.next_cursor) setCursors((old) => [...old, result.data!.next_cursor]); }} />
    {selected ? <form aria-label={selected.action === "remove" ? "Delete administrator access" : "Revoke administrator access"} onSubmit={changeAccess} className="max-w-xl space-y-4 border-y border-[var(--color-line)] py-5">
      <h2 className="text-lg font-bold">{selected.action === "remove" ? "Delete report access for" : "Revoke"} {selected.admin.full_name}</h2>
      {selected.action === "remove" ? <p className="text-sm">Tenant accounts and audit history will be retained.</p> : null}
      <div className="space-y-2"><Label htmlFor="admin-revoke-reason">Reason</Label><Textarea id="admin-revoke-reason" required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} disabled={pending} /></div>
      <div className="flex flex-wrap gap-3"><Button type="submit" disabled={pending}>{selected.action === "remove" ? "Delete report access" : "Revoke access"}</Button><Button type="button" variant="outline" disabled={pending} onClick={() => setSelected(null)}>Cancel</Button></div>
    </form> : null}
  </div>;
}

export function PlatformAdmins() {
  return <PlatformShell><PlatformGate managerOnly><AdminDirectory /></PlatformGate></PlatformShell>;
}
