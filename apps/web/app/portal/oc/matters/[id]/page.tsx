"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  FileText,
  Receipt,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchPortalOcInvoices,
  fetchPortalOcMatter,
  fetchPortalOcTimeEntries,
  fetchPortalOcWorkProduct,
  submitPortalOcInvoice,
  submitPortalOcTimeEntry,
  uploadPortalOcWorkProduct,
} from "@/lib/api/portal";

export default function PortalOcMatterDetailPage() {
  const params = useParams<{ id: string }>();
  const matterId = params?.id ?? "";

  const matterQuery = useQuery({
    queryKey: ["portal", "oc", "matter", matterId],
    queryFn: () => fetchPortalOcMatter(matterId),
    enabled: matterId.length > 0,
    retry: 0,
  });

  if (matterQuery.isError) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
        <QueryErrorState
          error={matterQuery.error}
          title="We could not load this matter"
        />
        <Link href="/portal/oc">
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Back to your matters
          </Button>
        </Link>
      </main>
    );
  }

  const matter = matterQuery.data;
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 px-6 py-10">
      <PageHeader
        eyebrow={matter?.matter_code ?? "Matter"}
        title={matter?.title ?? "Matter"}
        description={
          matter
            ? [matter.court_name, matter.practice_area].filter(Boolean).join(" · ")
            : "Loading…"
        }
        actions={
          <Link href="/portal/oc">
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Back
            </Button>
          </Link>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="work-product">
            <FileText className="mr-1 h-3.5 w-3.5" /> Work product
          </TabsTrigger>
          <TabsTrigger value="invoices">
            <Receipt className="mr-1 h-3.5 w-3.5" /> Invoices
          </TabsTrigger>
          <TabsTrigger value="time">
            <Clock className="mr-1 h-3.5 w-3.5" /> Time
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewCard matter={matter} />
        </TabsContent>

        <TabsContent value="work-product">
          <WorkProductCard matterId={matterId} />
        </TabsContent>

        <TabsContent value="invoices">
          <InvoicesCard matterId={matterId} />
        </TabsContent>

        <TabsContent value="time">
          <TimeEntriesCard matterId={matterId} />
        </TabsContent>
      </Tabs>
    </main>
  );
}

function OverviewCard({
  matter,
}: {
  matter:
    | {
        title: string;
        matter_code: string | null;
        status: string;
        practice_area: string | null;
        forum_level: string | null;
        court_name: string | null;
        next_hearing_on: string | null;
      }
    | undefined;
}) {
  if (!matter) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Status</CardTitle>
        <CardDescription>
          You see only what your firm has shared with you on this matter.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm md:grid-cols-2">
        <Row label="Status" value={<Badge tone="brand">{matter.status}</Badge>} />
        <Row label="Practice area" value={matter.practice_area ?? "—"} />
        <Row label="Court" value={matter.court_name ?? "—"} />
        <Row label="Forum level" value={matter.forum_level ?? "—"} />
        <Row
          label="Next hearing"
          value={
            matter.next_hearing_on
              ? new Date(matter.next_hearing_on).toLocaleDateString()
              : "Not scheduled"
          }
        />
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--color-line)] px-3 py-2">
      <span className="text-xs uppercase tracking-wide text-[var(--color-mute)]">
        {label}
      </span>
      <span className="text-sm text-[var(--color-ink)]">{value}</span>
    </div>
  );
}

function WorkProductCard({ matterId }: { matterId: string }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pickedFile, setPickedFile] = useState<File | null>(null);

  const itemsQuery = useQuery({
    queryKey: ["portal", "oc", "matter", matterId, "work-product"],
    queryFn: () => fetchPortalOcWorkProduct(matterId),
    enabled: matterId.length > 0,
  });
  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadPortalOcWorkProduct(matterId, file),
    onSuccess: () => {
      setPickedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      queryClient.invalidateQueries({
        queryKey: ["portal", "oc", "matter", matterId, "work-product"],
      });
      toast.success("Work product uploaded.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not upload."));
    },
  });
  const items = itemsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload work product</CardTitle>
          <CardDescription>
            Briefs, opinions, exhibits. Files are virus-scanned. Other
            outside counsel on this matter can&apos;t see your uploads
            unless the firm enables cross-counsel visibility.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2">
            <input
              ref={fileInputRef}
              type="file"
              data-testid="portal-oc-work-product-file"
              className="text-sm text-[var(--color-ink-2)] file:mr-2 file:rounded-md file:border file:border-[var(--color-line)] file:bg-[var(--color-surface)] file:px-3 file:py-1.5 file:text-sm file:text-[var(--color-ink)]"
              onChange={(e) => setPickedFile(e.target.files?.[0] ?? null)}
            />
            <Button
              type="button"
              disabled={!pickedFile || uploadMutation.isPending}
              onClick={() => pickedFile && uploadMutation.mutate(pickedFile)}
              data-testid="portal-oc-work-product-submit"
            >
              <Upload className="mr-1 h-3.5 w-3.5" />
              {uploadMutation.isPending ? "Uploading…" : "Upload"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your uploads</CardTitle>
        </CardHeader>
        <CardContent>
          {itemsQuery.isError ? (
            <QueryErrorState
              error={itemsQuery.error}
              title="Could not load uploads"
              onRetry={() => itemsQuery.refetch()}
            />
          ) : items.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No uploads yet"
              description="Drop a brief or opinion in the form above. Files are scanned before they appear on the firm side."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {items.map((it) => (
                <li
                  key={it.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-oc-wp-${it.id}`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {it.original_filename}
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      {(it.size_bytes / 1024).toFixed(1)} KB ·{" "}
                      {new Date(it.created_at).toLocaleString()}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InvoicesCard({ matterId }: { matterId: string }) {
  const queryClient = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [issuedOn, setIssuedOn] = useState(today);
  const [dueOn, setDueOn] = useState("");
  const [lineDescription, setLineDescription] = useState("");
  const [lineAmountMinor, setLineAmountMinor] = useState<string>("");
  const [notes, setNotes] = useState("");

  const invoicesQuery = useQuery({
    queryKey: ["portal", "oc", "matter", matterId, "invoices"],
    queryFn: () => fetchPortalOcInvoices(matterId),
    enabled: matterId.length > 0,
  });
  const submitMutation = useMutation({
    mutationFn: () =>
      submitPortalOcInvoice(matterId, {
        invoice_number: invoiceNumber.trim(),
        issued_on: issuedOn,
        due_on: dueOn || null,
        currency: "INR",
        line_items: [
          {
            description: lineDescription.trim(),
            amount_minor: Number(lineAmountMinor || 0),
          },
        ],
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      setInvoiceNumber("");
      setLineDescription("");
      setLineAmountMinor("");
      setNotes("");
      queryClient.invalidateQueries({
        queryKey: ["portal", "oc", "matter", matterId, "invoices"],
      });
      toast.success("Invoice submitted. The firm will review.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not submit invoice."));
    },
  });
  const invoices = invoicesQuery.data?.invoices ?? [];
  const canSubmit =
    invoiceNumber.trim().length > 0 &&
    lineDescription.trim().length > 0 &&
    Number(lineAmountMinor || 0) > 0 &&
    !submitMutation.isPending;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Submit an invoice</CardTitle>
          <CardDescription>
            Lands in the firm&apos;s billing inbox as &quot;needs review&quot;.
            They approve before any payment side-effects fire.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Label htmlFor="oc-inv-number">Invoice number</Label>
              <Input
                id="oc-inv-number"
                value={invoiceNumber}
                onChange={(e) => setInvoiceNumber(e.target.value)}
                placeholder="OC-2026-001"
                data-testid="portal-oc-invoice-number"
              />
            </div>
            <div>
              <Label htmlFor="oc-inv-issued">Issued on</Label>
              <Input
                id="oc-inv-issued"
                type="date"
                value={issuedOn}
                onChange={(e) => setIssuedOn(e.target.value)}
                data-testid="portal-oc-invoice-issued"
              />
            </div>
            <div>
              <Label htmlFor="oc-inv-due">Due on (optional)</Label>
              <Input
                id="oc-inv-due"
                type="date"
                value={dueOn}
                onChange={(e) => setDueOn(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="oc-inv-line-amount">
                Amount (paise / smallest unit)
              </Label>
              <Input
                id="oc-inv-line-amount"
                type="number"
                min={0}
                value={lineAmountMinor}
                onChange={(e) => setLineAmountMinor(e.target.value)}
                placeholder="500000"
                data-testid="portal-oc-invoice-amount"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="oc-inv-line-desc">Line item description</Label>
            <Input
              id="oc-inv-line-desc"
              value={lineDescription}
              onChange={(e) => setLineDescription(e.target.value)}
              placeholder="Drafting brief — bail application"
              data-testid="portal-oc-invoice-description"
            />
          </div>
          <div>
            <Label htmlFor="oc-inv-notes">Notes (optional)</Label>
            <Textarea
              id="oc-inv-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
            />
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              disabled={!canSubmit}
              onClick={() => submitMutation.mutate()}
              data-testid="portal-oc-invoice-submit"
            >
              <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
              {submitMutation.isPending ? "Submitting…" : "Submit invoice"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your submissions</CardTitle>
        </CardHeader>
        <CardContent>
          {invoicesQuery.isError ? (
            <QueryErrorState
              error={invoicesQuery.error}
              title="Could not load invoices"
              onRetry={() => invoicesQuery.refetch()}
            />
          ) : invoices.length === 0 ? (
            <EmptyState
              icon={Receipt}
              title="No invoices yet"
              description="Submit your first invoice above. The firm will see it in their billing inbox."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {invoices.map((inv) => (
                <li
                  key={inv.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-oc-invoice-${inv.id}`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {inv.invoice_number} ·{" "}
                      {(inv.total_amount_minor / 100).toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}{" "}
                      {inv.currency}
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      Issued {inv.issued_on}
                      {inv.due_on ? ` · Due ${inv.due_on}` : ""}
                    </span>
                  </div>
                  <Badge tone="neutral">{inv.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TimeEntriesCard({ matterId }: { matterId: string }) {
  const queryClient = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [workDate, setWorkDate] = useState(today);
  const [description, setDescription] = useState("");
  const [durationMinutes, setDurationMinutes] = useState<string>("");
  const [rateAmountMinor, setRateAmountMinor] = useState<string>("");

  const entriesQuery = useQuery({
    queryKey: ["portal", "oc", "matter", matterId, "time-entries"],
    queryFn: () => fetchPortalOcTimeEntries(matterId),
    enabled: matterId.length > 0,
  });
  const submitMutation = useMutation({
    mutationFn: () =>
      submitPortalOcTimeEntry(matterId, {
        work_date: workDate,
        description: description.trim(),
        duration_minutes: Number(durationMinutes || 0),
        billable: true,
        rate_currency: "INR",
        rate_amount_minor: rateAmountMinor ? Number(rateAmountMinor) : null,
      }),
    onSuccess: () => {
      setDescription("");
      setDurationMinutes("");
      setRateAmountMinor("");
      queryClient.invalidateQueries({
        queryKey: ["portal", "oc", "matter", matterId, "time-entries"],
      });
      toast.success("Time entry logged.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not log time entry."));
    },
  });
  const entries = entriesQuery.data?.entries ?? [];
  const canSubmit =
    description.trim().length > 0 &&
    Number(durationMinutes || 0) > 0 &&
    !submitMutation.isPending;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Log time</CardTitle>
          <CardDescription>
            Posts a time entry against this matter. The firm reviews and
            attaches it to an invoice; nothing auto-bills.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Label htmlFor="oc-te-date">Work date</Label>
              <Input
                id="oc-te-date"
                type="date"
                value={workDate}
                onChange={(e) => setWorkDate(e.target.value)}
                data-testid="portal-oc-time-date"
              />
            </div>
            <div>
              <Label htmlFor="oc-te-duration">Duration (minutes)</Label>
              <Input
                id="oc-te-duration"
                type="number"
                min={1}
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(e.target.value)}
                placeholder="90"
                data-testid="portal-oc-time-duration"
              />
            </div>
            <div className="md:col-span-2">
              <Label htmlFor="oc-te-desc">Description</Label>
              <Input
                id="oc-te-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Reviewed client documents"
                data-testid="portal-oc-time-description"
              />
            </div>
            <div>
              <Label htmlFor="oc-te-rate">
                Hourly rate (paise / smallest unit, optional)
              </Label>
              <Input
                id="oc-te-rate"
                type="number"
                min={0}
                value={rateAmountMinor}
                onChange={(e) => setRateAmountMinor(e.target.value)}
                placeholder="500000"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              disabled={!canSubmit}
              onClick={() => submitMutation.mutate()}
              data-testid="portal-oc-time-submit"
            >
              <Clock className="mr-1 h-3.5 w-3.5" />
              {submitMutation.isPending ? "Logging…" : "Log time"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your entries</CardTitle>
        </CardHeader>
        <CardContent>
          {entriesQuery.isError ? (
            <QueryErrorState
              error={entriesQuery.error}
              title="Could not load entries"
              onRetry={() => entriesQuery.refetch()}
            />
          ) : entries.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No time entries"
              description="Log your first time entry above."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {entries.map((te) => (
                <li
                  key={te.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-oc-te-${te.id}`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {te.work_date} · {te.duration_minutes} min
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      {te.description}
                    </span>
                  </div>
                  {te.total_amount_minor ? (
                    <Badge tone="neutral">
                      {(te.total_amount_minor / 100).toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}{" "}
                      {te.rate_currency}
                    </Badge>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
