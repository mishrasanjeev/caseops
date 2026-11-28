"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type ChangeEvent } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchBillingDocumentVerification,
  isVerificationToken,
  sha256Hex,
  type BillingDocumentVerification,
} from "@/lib/api/document-branding";

function formatAmount(minor: number, currency: string): string {
  const value = minor / 100;
  if (currency !== "INR") {
    return `${currency} ${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `INR ${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

type FileCheck = { name: string; matches: boolean } | null;

/** An outside counsel's invoice names a supplier the counsel typed in. */
function issuerLabel(result: BillingDocumentVerification): string {
  return result.issuer_supplied_by_counsel ? "Supplier (as entered by the counsel)" : "Issued by";
}

function Facts({ result }: { result: BillingDocumentVerification }) {
  const rows: Array<[string, string, string]> = [
    ["Document", result.document_type, "document"],
    ["Number", result.document_number, "number"],
    [issuerLabel(result), result.issuer_name, "issued-by"],
    ["Document date", formatDate(result.issued_on), "document-date"],
    ["Amount", formatAmount(result.amount_minor, result.currency), "amount"],
    ["Status on this copy", result.status_at_generation, "status-on-this-copy"],
    ["Status now", result.current_status, "status-now"],
    ["Copy generated", new Date(result.generated_at).toLocaleString("en-IN"), "copy-generated"],
  ];
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2 text-sm" data-testid="verify-facts">
      {rows.map(([label, value, id]) => (
        <div key={id} className="contents">
          <dt className="text-[var(--color-mute)]" data-testid={`verify-${id}-label`}>{label}</dt>
          <dd className="font-medium text-[var(--color-ink)] [overflow-wrap:anywhere]" data-testid={`verify-${id}`}>
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The headline: only an issued, unrevoked document is called genuine. */
function StateLine({ result }: { result: BillingDocumentVerification }) {
  if (result.state === "valid") {
    return (
      <>
        <Badge tone="success">Genuine document</Badge>
        <span className="text-sm text-[var(--color-ink)]">
          {result.issuer_supplied_by_counsel
            ? `Submitted by outside counsel. Supplier details as entered by the counsel: ${result.issuer_name}.`
            : `Issued by ${result.issuer_name}.`}
        </span>
      </>
    );
  }
  if (result.state === "not_issued") {
    return (
      <>
        <Badge tone="warning">Not an issued document</Badge>
        <span className="text-sm text-[var(--color-ink)]">
          {`This copy was generated as: ${result.status_at_generation}. It is not an issued document and must not be relied on as one.`}
        </span>
      </>
    );
  }
  return (
    <>
      <Badge tone="warning">Revoked</Badge>
      <span className="text-sm text-[var(--color-ink)]">
        {result.revoked_reason ?? "This document is no longer valid."}
      </span>
    </>
  );
}

function Fingerprint({ result }: { result: BillingDocumentVerification }) {
  const [check, setCheck] = useState<FileCheck>(null);
  const [checking, setChecking] = useState(false);
  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setChecking(true);
    try {
      setCheck({ name: file.name, matches: (await sha256Hex(file)) === result.pdf_sha256 });
    } finally {
      setChecking(false);
    }
  }
  const issued = result.state !== "not_issued";
  return (
    <section className="flex flex-col gap-2 border-t border-[var(--color-line)] pt-4" aria-labelledby="verify-fingerprint-title">
      <h2 id="verify-fingerprint-title" className="text-sm font-semibold text-[var(--color-ink)]">
        {issued ? "Fingerprint of the issued file" : "Fingerprint of this copy"}
      </h2>
      <p className="text-xs text-[var(--color-mute)]">
        {issued ? "SHA-256 of the exact PDF that was issued." : "SHA-256 of the exact PDF generated for this link."}{" "}
        Choose your copy to compare; the file is checked in this browser and is not uploaded.
      </p>
      <code className="block rounded-md bg-[var(--color-bg-2)] px-2 py-1.5 font-mono text-xs [overflow-wrap:anywhere]" data-testid="verify-sha256">
        {result.pdf_sha256}
      </code>
      <Label htmlFor="verify-file">Check a copy</Label>
      <input
        id="verify-file"
        type="file"
        accept="application/pdf"
        onChange={onFile}
        className="text-sm"
        data-testid="verify-file-input"
      />
      {checking ? <p className="text-xs text-[var(--color-mute)]">Checking…</p> : null}
      {check ? (
        <p role="status" className="text-sm font-medium text-[var(--color-ink)]" data-testid="verify-file-result">
          {check.matches
            ? issued
              ? `${check.name} is the issued file, unchanged.`
              : `${check.name} is the file generated for this link, unchanged. It is still not an issued document.`
            : `${check.name} does not match. It is not the copy that was ${issued ? "issued" : "generated for this link"}, or it has been altered.`}
        </p>
      ) : null}
    </section>
  );
}

export default function VerifyBillingDocumentPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";
  const valid = isVerificationToken(token);
  const query = useQuery({
    queryKey: ["verify", "billing-document", token],
    queryFn: () => fetchBillingDocumentVerification(token),
    enabled: valid,
    retry: false,
  });
  const result = query.data;
  const notFound = !valid || query.isError;
  return (
    <main className="flex min-h-screen justify-center bg-[var(--color-bg)] px-4 py-10">
      <Card className="h-fit w-full max-w-xl">
        <CardHeader>
          <CardTitle as="h1" className="text-lg">Billing document verification</CardTitle>
          <CardDescription>
            Confirms whether a billing PDF was generated through CaseOps, whether it is an issued document, and its current status.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {valid && query.isPending ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : null}
          {notFound ? (
            <div role="alert" className="flex flex-col gap-1" data-testid="verify-not-found">
              <p className="text-sm font-semibold text-[var(--color-ink)]">This link does not verify any document.</p>
              <p className="text-sm text-[var(--color-mute)]">
                {query.isError
                  ? apiErrorMessage(query.error, "This verification link is not valid.")
                  : "This verification link is not valid."}{" "}
                Check that the whole link was copied, or ask the issuer for a fresh copy.
              </p>
            </div>
          ) : null}
          {result ? (
            <>
              <div className="flex flex-wrap items-center gap-2" data-testid="verify-state" data-state={result.state}>
                <StateLine result={result} />
              </div>
              <Facts result={result} />
              <Fingerprint result={result} />
            </>
          ) : null}
        </CardContent>
      </Card>
    </main>
  );
}
