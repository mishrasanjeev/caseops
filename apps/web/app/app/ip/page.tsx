"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgeIndianRupee, FileCheck2, Plus, Scale } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  addIpCostItem,
  addIpTitleInterest,
  createIpDocket,
  fetchIpDockets,
  type IpDocket,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

const TODAY = new Date().toISOString().slice(0, 10);

export default function IpDocketPage() {
  const queryClient = useQueryClient();
  const canView = useCapability("ip:view");
  const canWrite = useCapability("ip:write");
  const canReview = useCapability("ip:review");
  const canFinance = useCapability("ip:finance");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const listing = useQuery({
    queryKey: ["ip", "dockets"],
    queryFn: fetchIpDockets,
    enabled: canView,
  });
  const dockets = listing.data?.dockets ?? [];
  const selected = useMemo(
    () => dockets.find((row) => row.id === selectedId) ?? dockets[0] ?? null,
    [dockets, selectedId],
  );

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ip", "dockets"] });
  };

  if (!canView) {
    return (
      <EmptyState
        title="IP docket access required"
        description="Your role does not include permission to view intellectual-property records."
      />
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Intellectual property"
        title="Trademark docket"
        description="Form-versioned particulars, evidence links, deadline control, title history, and costs anchored to existing CaseOps owners."
        actions={
          canWrite ? (
            <Button size="sm" onClick={() => setShowCreate((value) => !value)}>
              <Plus className="h-4 w-4" aria-hidden /> New trademark
            </Button>
          ) : null
        }
      />

      {showCreate && canWrite ? (
        <CreateTrademarkCard
          onCreated={async (docket) => {
            setSelectedId(docket.id);
            setShowCreate(false);
            await refresh();
          }}
        />
      ) : null}

      {listing.isPending ? (
        <Card><CardContent className="py-10 text-sm">Loading IP docket…</CardContent></Card>
      ) : listing.isError ? (
        <EmptyState
          title="Could not load the IP docket"
          description={apiErrorMessage(listing.error, "The IP API did not respond.")}
          action={<Button onClick={() => listing.refetch()}>Retry</Button>}
        />
      ) : dockets.length === 0 ? (
        <EmptyState
          title="No IP records yet"
          description="Create a trademark record to validate filing particulars and begin the evidence-backed docket."
        />
      ) : (
        <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]">
          <Card className="min-w-0">
            <CardHeader><CardTitle as="h2">Portfolio</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              {dockets.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => setSelectedId(row.id)}
                  className={`min-w-0 rounded-lg border p-3 text-left ${
                    selected?.id === row.id
                      ? "border-[var(--color-brand-500)] bg-[var(--color-brand-50)]"
                      : "border-[var(--color-line)] bg-white"
                  }`}
                  data-testid={`ip-docket-${row.id}`}
                >
                  <span className="block truncate font-semibold">{row.title}</span>
                  <span className="mt-1 block text-xs text-[var(--color-mute)]">
                    {row.primary_identifier ?? "Unfiled"} · {row.status} · v{row.current_version}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          {selected ? (
            <DocketWorkspace
              docket={selected}
              canReview={canReview}
              canFinance={canFinance}
              onChanged={refresh}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}

function CreateTrademarkCard({ onCreated }: { onCreated: (docket: IpDocket) => void }) {
  const [title, setTitle] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [markText, setMarkText] = useState("");
  const [classNumber, setClassNumber] = useState("9");
  const [specification, setSpecification] = useState("");
  const [applicant, setApplicant] = useState("");
  const [evidence, setEvidence] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createIpDocket({
        title,
        primaryIdentifier: identifier || null,
        markText,
        classNumber: Number(classNumber),
        specification,
        applicantName: applicant,
        evidenceReference: evidence,
      }),
    onSuccess: (row) => {
      toast.success("Trademark docket created and readiness-validated.");
      onCreated(row);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create IP docket.")),
  });
  const valid =
    title.trim().length >= 2 &&
    markText.trim().length >= 1 &&
    specification.trim().length >= 3 &&
    applicant.trim().length >= 2 &&
    evidence.trim().length >= 3;

  return (
    <Card>
      <CardHeader><CardTitle as="h2">New trademark particulars</CardTitle></CardHeader>
      <CardContent>
        <form
          className="grid min-w-0 gap-4 md:grid-cols-2"
          onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}
        >
          <Field label="Docket title"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Application / client reference"><Input value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></Field>
          <Field label="Word mark"><Input value={markText} onChange={(e) => setMarkText(e.target.value)} /></Field>
          <Field label="Nice class"><Input type="number" min={1} max={45} value={classNumber} onChange={(e) => setClassNumber(e.target.value)} /></Field>
          <Field label="Goods / services specification"><Input value={specification} onChange={(e) => setSpecification(e.target.value)} /></Field>
          <Field label="Applicant"><Input value={applicant} onChange={(e) => setApplicant(e.target.value)} /></Field>
          <Field label="Representation evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="attachment:… or drive:…" /></Field>
          <div className="flex items-end"><Button type="submit" disabled={!valid || mutation.isPending}>Validate and create</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

function DocketWorkspace({
  docket,
  canReview,
  canFinance,
  onChanged,
}: {
  docket: IpDocket;
  canReview: boolean;
  canFinance: boolean;
  onChanged: () => Promise<void>;
}) {
  const classes = docket.current_particulars.classes_json;
  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid="ip-docket-workspace">
      <Card className="min-w-0">
        <CardHeader><CardTitle as="h2">{docket.title}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Readiness" value={docket.current_particulars.readiness_status} icon={FileCheck2} />
          <Metric label="Form" value={`${docket.current_particulars.form_key} ${docket.current_particulars.form_version}`} icon={Scale} />
          <Metric label="Deadline incidents" value={String(docket.deadline_incidents.length)} icon={AlertTriangle} />
          <Metric label="Cost items" value={String(docket.cost_items.length)} icon={BadgeIndianRupee} />
          <div className="sm:col-span-2 xl:col-span-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Class scope</div>
            <ul className="mt-2 flex min-w-0 flex-col gap-2">
              {classes.map((row) => (
                <li key={row.class_number} className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3 text-sm">
                  <strong>Class {row.class_number}</strong> · <span className="break-words">{row.specification}</span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        <TitleCard docket={docket} enabled={canReview} onChanged={onChanged} />
        <CostCard docket={docket} enabled={canFinance} onChanged={onChanged} />
      </div>

      <Card>
        <CardHeader><CardTitle as="h3">Operational links</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Metric label="Accepted notices" value={String(docket.notice_links.length)} icon={FileCheck2} />
          <Metric label="Deadline coverage" value={String(docket.deadline_coverages.length)} icon={FileCheck2} />
          <Metric label="Title entries" value={String(docket.title_interests.length)} icon={Scale} />
        </CardContent>
      </Card>
    </div>
  );
}

function TitleCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [party, setParty] = useState("");
  const [evidence, setEvidence] = useState("");
  const mutation = useMutation({
    mutationFn: () => addIpTitleInterest(docket.id, { interestType: "ownership", partyName: party, effectiveFrom: TODAY, evidenceReference: evidence }),
    onSuccess: async () => { toast.success("Title evidence added."); setParty(""); setEvidence(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add title evidence.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">Chain of title</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.title_interests.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <strong className="break-words">{row.party_name}</strong> · {row.interest_type} from {row.effective_from}
            {row.conflict_flags_json.length ? <div className="mt-1 text-xs text-red-700">Overlap requires review</div> : null}
          </div>
        ))}
        {enabled ? (
          <form className="grid min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
            <Field label="Owner / assignee"><Input value={party} onChange={(e) => setParty(e.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
            <Button size="sm" type="submit" disabled={party.length < 2 || evidence.length < 3 || mutation.isPending}>Add ownership evidence</Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CostCard({ docket, enabled, onChanged }: { docket: IpDocket; enabled: boolean; onChanged: () => Promise<void> }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const mutation = useMutation({
    mutationFn: () => addIpCostItem(docket.id, { category: "official_fee", description, amountMinor: Math.round(Number(amount) * 100), evidenceReference: evidence }),
    onSuccess: async () => { toast.success("Immutable cost evidence added."); setDescription(""); setAmount(""); setEvidence(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add cost evidence.")),
  });
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle as="h3">IP cost evidence</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {docket.cost_items.map((row) => (
          <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm">
            <strong className="break-words">{row.description}</strong> · {row.currency} {(row.amount_minor / 100).toFixed(2)}
          </div>
        ))}
        {enabled && docket.matter_id ? (
          <form className="grid min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
            <Field label="Description"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            <Field label="Amount (INR)"><Input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Evidence reference"><Input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></Field>
            <Button size="sm" type="submit" disabled={description.length < 3 || !amount || evidence.length < 3 || mutation.isPending}>Add cost evidence</Button>
          </form>
        ) : (
          <p className="text-xs text-[var(--color-mute)]">Cost items require a linked Matter so Matter billing remains the accounting owner.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex min-w-0 flex-col gap-1"><Label>{label}</Label>{children}</label>;
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Scale }) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
      <div className="flex items-center gap-2 text-xs text-[var(--color-mute)]"><Icon className="h-4 w-4" aria-hidden />{label}</div>
      <div className="mt-1 truncate font-semibold capitalize">{value.replaceAll("_", " ")}</div>
    </div>
  );
}
