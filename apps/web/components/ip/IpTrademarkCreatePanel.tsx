"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { NICE_CLASS_QUERY_KEY, NiceClassPicker, useNiceClassCatalogue } from "@/components/ip/NiceClassPicker";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Textarea } from "@/components/ui/Textarea";
import { ApiError, apiErrorMessage, apiFieldErrors, apiValidationIssues } from "@/lib/api/config";
import { createManualTrademarkApplication, listMatters, type IpDocket } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";

/**
 * New trademark application form (BUG-001, BUG-002).
 *
 * Opens as a labelled region that scrolls into view and focuses its first
 * field. Classes are rows chosen from the Nice catalogue the API validates
 * against; each row is sent with the catalogue's edition, and a 422 on a row
 * is shown under that row's control.
 */

export const IP_NEW_TRADEMARK_PANEL_ID = "ip-new-trademark-panel";
const HEADING_ID = "ip-new-trademark-heading";
const SPECIFICATION_MIN = 3;
const SPECIFICATION_MAX = 4000;
const MATTER_PAGE = 50;
const TODAY = new Date().toISOString().slice(0, 10);
const SELECT_CLASS = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";
const ERROR_CLASS = "break-words text-xs text-[var(--color-danger-text)]";

type ClassRow = { key: number; classNumber: number | null; specification: string };
type RowErrors = Record<number, { class_number?: string; specification?: string }>;

const FIELD_IDS = {
  title: "ip-tm-title",
  matter: "ip-tm-matter",
  mark: "ip-tm-mark",
  applicant: "ip-tm-applicant",
  evidence: "ip-tm-evidence",
  jurisdiction: "ip-tm-jurisdiction",
  office: "ip-tm-office",
  phase: "ip-tm-phase",
  applicationNumber: "ip-tm-application-number",
} as const;

// API field paths (without source and list indices) -> control ids.
const FIELD_MAP: Record<string, string> = {
  title: FIELD_IDS.title,
  matter_id: FIELD_IDS.matter,
  asset_title: FIELD_IDS.mark,
  "representation.text": FIELD_IDS.mark,
  "representation.evidence_reference": FIELD_IDS.evidence,
  "filing_manifest.evidence_reference": FIELD_IDS.evidence,
  "parties.name": FIELD_IDS.applicant,
  parties: FIELD_IDS.applicant,
  jurisdiction: FIELD_IDS.jurisdiction,
  office: FIELD_IDS.office,
  filing_phase: FIELD_IDS.phase,
  application_number: FIELD_IDS.applicationNumber,
};
const CONTROL_IDS = new Set<string>(Object.values(FIELD_IDS));

export function classPickerId(key: number) {
  return `ip-tm-class-${key}`;
}

export function specificationId(key: number) {
  return `ip-tm-spec-${key}`;
}

/** Row-addressed refusals: `["body","particulars","classes",i,field]`. */
function classRowErrors(error: unknown): { rows: Record<number, { class_number?: string; specification?: string }>; list: string | null; edition: boolean } {
  const rows: Record<number, { class_number?: string; specification?: string }> = {};
  let list: string | null = null;
  let edition = false;
  if (!(error instanceof ApiError)) return { rows, list, edition };
  for (const issue of apiValidationIssues(error.data)) {
    const at = issue.loc.indexOf("classes");
    if (at < 0) continue;
    const index = issue.loc[at + 1];
    const field = issue.loc[at + 2];
    if (typeof index !== "number") {
      list = issue.msg;
      continue;
    }
    if (field === "nice_edition") edition = true;
    const slot = field === "specification" ? "specification" : "class_number";
    rows[index] = { ...rows[index], [slot]: issue.msg };
  }
  return { rows, list, edition };
}

function matterLabel(matter: Matter): string {
  return [matter.title, matter.matter_code, matter.client_name].filter(Boolean).join(" · ");
}

function MatterSelect({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (matter: Matter | null) => void;
  error?: string;
}) {
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<Matter | null>(null);
  const query = useDeferredValue(search.trim());
  const matters = useQuery({
    queryKey: ["matters", "ip-create-picker", query],
    queryFn: () => listMatters({ limit: MATTER_PAGE, q: query || undefined }),
  });
  const rows = matters.data?.matters ?? [];
  const forbidden = matters.error instanceof ApiError && matters.error.status === 403;
  const options = useMemo(() => {
    const listed = chosen && !rows.some((row) => row.id === chosen.id) ? [chosen, ...rows] : rows;
    return [
      { value: "", label: "No Matter (pre-engagement record)" },
      ...listed.map((row) => ({ value: row.id, label: matterLabel(row) })),
    ];
  }, [chosen, rows]);
  const statusId = `${FIELD_IDS.matter}-status`;
  const errorId = `${FIELD_IDS.matter}-error`;

  let status: React.ReactNode = null;
  if (matters.isPending) status = "Loading matters…";
  else if (forbidden) status = "Your role cannot list matters, so this record is created without a Matter. Link one later from the docket.";
  else if (matters.isError) status = null;
  else if (rows.length === 0 && query) status = `No Matter matches “${query}”.`;
  else if (rows.length === 0) status = (
    <>No matters yet. The record can be created without one, or <Link className="font-semibold text-[var(--color-brand-700)] underline" href="/app/matters">create a Matter</Link> first.</>
  );
  else if (matters.data?.next_cursor) status = `Showing the first ${rows.length} matches. Type to narrow the list.`;

  return (
    <div className="flex min-w-0 flex-col gap-1 md:col-span-2">
      <Label htmlFor={`${FIELD_IDS.matter}-search`}>Find a Matter (optional)</Label>
      <Input
        id={`${FIELD_IDS.matter}-search`}
        type="search"
        value={search}
        placeholder="Matter title, code or client"
        onChange={(event) => setSearch(event.target.value)}
        disabled={forbidden}
      />
      <RecordSelect
        id={FIELD_IDS.matter}
        label="Matter"
        className={SELECT_CLASS}
        value={value}
        options={options}
        // With nothing to choose the select would only offer "No Matter"; the status says why.
        disabled={matters.isPending || matters.isError || options.length === 1}
        aria-invalid={error ? true : undefined}
        aria-describedby={[status ? statusId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined}
        onChange={(event) => {
          const next = rows.find((row) => row.id === event.target.value) ?? (chosen?.id === event.target.value ? chosen : null);
          setChosen(next);
          onChange(next);
        }}
      />
      {status ? <p id={statusId} role="status" className="break-words text-xs text-[var(--color-mute)]">{status}</p> : null}
      {matters.isError && !forbidden ? (
        <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[var(--color-danger-text)]">
          <span className="break-words">{apiErrorMessage(matters.error, "Could not load matters.")}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => matters.refetch()}>Try again</Button>
        </div>
      ) : null}
      {error ? <p id={errorId} className={ERROR_CLASS}>{error}</p> : null}
    </div>
  );
}

function TextField({
  id,
  label,
  error,
  className,
  ...props
}: React.ComponentProps<typeof Input> & { id: string; label: string; error?: string }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className ?? ""}`}>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined} {...props} />
      {error ? <p id={`${id}-error`} className={ERROR_CLASS}>{error}</p> : null}
    </div>
  );
}

export function IpTrademarkCreatePanel({
  onCreated,
  onCancel,
}: {
  onCreated: (docket: IpDocket) => void;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const catalogue = useNiceClassCatalogue();
  const panelRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const nextKey = useRef(1);
  const [title, setTitle] = useState("");
  const [matterId, setMatterId] = useState("");
  const [markText, setMarkText] = useState("");
  const [rows, setRows] = useState<ClassRow[]>([{ key: 0, classNumber: null, specification: "" }]);
  const [applicant, setApplicant] = useState("");
  const [evidence, setEvidence] = useState("");
  const [restricted, setRestricted] = useState(false);
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [office, setOffice] = useState("IP India");
  const [filingPhase, setFilingPhase] = useState<"draft" | "pre_filing" | "filed">("pre_filing");
  const [applicationNumber, setApplicationNumber] = useState("");
  const [numberSource, setNumberSource] = useState("manual");
  const [numberEffectiveFrom, setNumberEffectiveFrom] = useState(TODAY);
  const [pendingAllocation, setPendingAllocation] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<RowErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    panelRef.current?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
    titleRef.current?.focus({ preventScroll: true });
  }, []);

  const mutation = useMutation({
    mutationFn: () =>
      createManualTrademarkApplication({
        title,
        matterId: matterId || null,
        restricted,
        assetTitle: markText,
        jurisdiction,
        office,
        filingPhase,
        sourcePendingIdentifierAllocation: filingPhase === "filed" && !applicationNumber.trim() && pendingAllocation,
        applicationNumber: applicationNumber.trim() || null,
        identifierSource: numberSource,
        identifierEffectiveFrom: numberEffectiveFrom,
        markText,
        classes: rows.map((row) => ({ classNumber: row.classNumber!, specification: row.specification.trim() })),
        niceEdition: catalogue.data!.edition,
        applicantName: applicant,
        evidenceReference: evidence,
      }),
    onMutate: () => {
      setFieldErrors({});
      setRowErrors({});
      setFormError(null);
    },
    onSuccess: (result) => {
      toast.success(
        result.duplicate_candidates.length
          ? "Draft created. Review the possible duplicate before marking it filed."
          : "Trademark application created with its canonical identity records.",
      );
      onCreated(result.docket);
    },
    onError: (error) => {
      const classes = classRowErrors(error);
      const byRow: RowErrors = {};
      for (const [index, messages] of Object.entries(classes.rows)) {
        const row = rows[Number(index)];
        if (row) byRow[row.key] = messages;
      }
      const placed: Record<string, string> = {};
      const unplaced: string[] = classes.list ? [classes.list] : [];
      for (const [key, message] of Object.entries(apiFieldErrors(error, FIELD_MAP))) {
        if (CONTROL_IDS.has(key)) placed[key] = message;
        else if (!key.includes("classes")) unplaced.push(message);
      }
      setRowErrors(byRow);
      setFieldErrors(placed);
      if (classes.edition) {
        // The Nice edition changed since the list was loaded; reload it.
        void queryClient.invalidateQueries({ queryKey: NICE_CLASS_QUERY_KEY });
      }
      const anchored = Object.keys(byRow).length + Object.keys(placed).length;
      const message = unplaced.length ? unplaced.join(" ") : anchored ? null : apiErrorMessage(error, "Could not create the trademark application.");
      setFormError(message);
      toast.error(anchored ? "Check the highlighted fields." : message ?? "Could not create the trademark application.");
    },
  });

  const chosenClasses = rows.map((row) => row.classNumber).filter((value): value is number => value !== null);
  const duplicate = new Set(chosenClasses).size !== chosenClasses.length;
  const rowsValid = rows.every((row) => {
    const spec = row.specification.trim();
    return row.classNumber !== null && spec.length >= SPECIFICATION_MIN && spec.length <= SPECIFICATION_MAX;
  }) && !duplicate;
  const filedAllocationValid = filingPhase !== "filed" || Boolean(applicationNumber.trim()) || pendingAllocation;
  const missing: string[] = [];
  if (title.trim().length < 2) missing.push("a docket title");
  if (markText.trim().length < 1) missing.push("the word mark");
  if (rows.some((row) => row.classNumber === null)) missing.push("a Nice class for every class row");
  if (rows.some((row) => row.specification.trim().length < SPECIFICATION_MIN)) missing.push("goods or services (at least 3 characters) for every class row");
  if (applicant.trim().length < 2) missing.push("the applicant");
  if (evidence.trim().length < 3) missing.push("a representation evidence reference");
  if (jurisdiction.trim().length < 2) missing.push("the jurisdiction");
  if (office.trim().length < 2) missing.push("the registry office");
  if (!filedAllocationValid) missing.push("the application number, or confirmation that it is pending allocation");
  const valid = catalogue.isSuccess && rowsValid && missing.length === 0;

  const updateRow = (key: number, patch: Partial<ClassRow>) => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
    setRowErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };
  const addRow = () => {
    const key = nextKey.current++;
    setRows((current) => [...current, { key, classNumber: null, specification: "" }]);
    window.setTimeout(() => document.getElementById(classPickerId(key))?.focus(), 0);
  };
  const removeRow = (key: number) => {
    const index = rows.findIndex((row) => row.key === key);
    setRows((current) => current.filter((row) => row.key !== key));
    const neighbour = rows[index + 1] ?? rows[index - 1];
    window.setTimeout(() => neighbour && document.getElementById(classPickerId(neighbour.key))?.focus(), 0);
  };

  return (
    <section
      ref={panelRef}
      id={IP_NEW_TRADEMARK_PANEL_ID}
      role="region"
      aria-labelledby={HEADING_ID}
      className="min-w-0 scroll-mt-20 rounded-lg border border-[var(--color-line)] bg-white p-4"
      data-testid="ip-new-trademark-panel"
    >
      <div className="mb-3 flex min-w-0 items-start justify-between gap-2">
        <h2 id={HEADING_ID} className="text-base font-semibold tracking-tight text-[var(--color-ink)]">New trademark application</h2>
        <Button type="button" size="sm" variant="ghost" className="h-9 w-9 shrink-0 p-0" aria-label="Close new trademark application" onClick={onCancel}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <form
        className="grid min-w-0 gap-4 md:grid-cols-2"
        noValidate
        onSubmit={(event) => { event.preventDefault(); if (valid && !mutation.isPending) mutation.mutate(); }}
      >
        <TextField ref={titleRef} id={FIELD_IDS.title} label="Docket title" value={title} error={fieldErrors[FIELD_IDS.title]} onChange={(event) => setTitle(event.target.value)} />
        <TextField id={FIELD_IDS.mark} label="Word mark" value={markText} error={fieldErrors[FIELD_IDS.mark]} onChange={(event) => setMarkText(event.target.value)} />
        <MatterSelect value={matterId} error={fieldErrors[FIELD_IDS.matter]} onChange={(matter) => setMatterId(matter?.id ?? "")} />

        <fieldset className="flex min-w-0 flex-col gap-3 md:col-span-2">
          <legend className="text-sm font-semibold text-[var(--color-ink)]">Nice classes</legend>
          {catalogue.data ? (
            <p className="text-xs text-[var(--color-mute)]">
              Classified under {catalogue.data.edition}, in force from {catalogue.data.in_force_from}. List each class once with its goods or services.
            </p>
          ) : null}
          {rows.map((row, index) => {
            const classError = rowErrors[row.key]?.class_number
              ?? (duplicate && row.classNumber !== null && chosenClasses.indexOf(row.classNumber) < index
                ? `Nice class ${row.classNumber} is already listed in another row.`
                : undefined);
            const specError = rowErrors[row.key]?.specification;
            const specLength = row.specification.trim().length;
            return (
              <div key={row.key} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto]" data-testid={`ip-tm-class-row-${index}`}>
                <div className="min-w-0">
                  <NiceClassPicker
                    id={classPickerId(row.key)}
                    label={`Nice class, row ${index + 1}`}
                    value={row.classNumber}
                    onChange={(value) => updateRow(row.key, { classNumber: value })}
                    unavailable={rows.filter((other) => other.key !== row.key && other.classNumber !== null).map((other) => other.classNumber!)}
                    invalid={Boolean(classError)}
                    errorId={classError ? `${classPickerId(row.key)}-error` : undefined}
                  />
                  {classError ? <p id={`${classPickerId(row.key)}-error`} className={`mt-1 ${ERROR_CLASS}`}>{classError}</p> : null}
                </div>
                <div className="flex min-w-0 flex-col gap-1">
                  <Label htmlFor={specificationId(row.key)}>{`Goods and services, row ${index + 1}`}</Label>
                  <Textarea
                    id={specificationId(row.key)}
                    rows={2}
                    maxLength={SPECIFICATION_MAX}
                    value={row.specification}
                    aria-invalid={specError ? true : undefined}
                    aria-describedby={specError ? `${specificationId(row.key)}-error` : undefined}
                    onChange={(event) => updateRow(row.key, { specification: event.target.value })}
                  />
                  {specError ? (
                    <p id={`${specificationId(row.key)}-error`} className={ERROR_CLASS}>{specError}</p>
                  ) : specLength > 0 && specLength < SPECIFICATION_MIN ? (
                    <p className="text-xs text-[var(--color-mute)]">Describe the goods or services in at least 3 characters.</p>
                  ) : null}
                </div>
                <div className="flex items-start md:pt-6">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Remove class row ${index + 1}`}
                    title={rows.length === 1 ? "An application needs at least one class" : undefined}
                    disabled={rows.length === 1}
                    onClick={() => removeRow(row.key)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden /> <span className="md:sr-only">Remove</span>
                  </Button>
                </div>
              </div>
            );
          })}
          <div>
            <Button type="button" size="sm" variant="outline" onClick={addRow} disabled={!catalogue.isSuccess || rows.length >= 45}>
              <Plus className="h-4 w-4" aria-hidden /> Add class row
            </Button>
          </div>
        </fieldset>

        <TextField id={FIELD_IDS.applicant} label="Applicant" value={applicant} error={fieldErrors[FIELD_IDS.applicant]} onChange={(event) => setApplicant(event.target.value)} />
        <TextField id={FIELD_IDS.evidence} label="Representation evidence reference" value={evidence} placeholder="attachment:… or drive:…" error={fieldErrors[FIELD_IDS.evidence]} onChange={(event) => setEvidence(event.target.value)} />
        <TextField id={FIELD_IDS.jurisdiction} label="Jurisdiction" value={jurisdiction} error={fieldErrors[FIELD_IDS.jurisdiction]} onChange={(event) => setJurisdiction(event.target.value.toUpperCase())} />
        <TextField id={FIELD_IDS.office} label="Registry office" value={office} error={fieldErrors[FIELD_IDS.office]} onChange={(event) => setOffice(event.target.value)} />
        <div className="flex min-w-0 flex-col gap-1">
          <Label htmlFor={FIELD_IDS.phase}>Filing phase</Label>
          <select id={FIELD_IDS.phase} className={SELECT_CLASS} value={filingPhase} onChange={(event) => setFilingPhase(event.target.value as typeof filingPhase)}>
            <option value="draft">Draft</option>
            <option value="pre_filing">Pre-filing</option>
            <option value="filed">Filed</option>
          </select>
        </div>
        <TextField
          id={FIELD_IDS.applicationNumber}
          label="Application number (optional before filing)"
          value={applicationNumber}
          error={fieldErrors[FIELD_IDS.applicationNumber]}
          onChange={(event) => { setApplicationNumber(event.target.value); if (event.target.value) setPendingAllocation(false); }}
        />
        {applicationNumber ? (
          <>
            <TextField id="ip-tm-number-source" label="Number source" value={numberSource} onChange={(event) => setNumberSource(event.target.value)} />
            <TextField id="ip-tm-number-effective" label="Effective from" type="date" value={numberEffectiveFrom} onChange={(event) => setNumberEffectiveFrom(event.target.value)} />
          </>
        ) : null}
        {filingPhase === "filed" && !applicationNumber ? (
          <label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2">
            <input type="checkbox" className="mt-1" checked={pendingAllocation} onChange={(event) => setPendingAllocation(event.target.checked)} />
            Registry source confirms the application number is still pending allocation
          </label>
        ) : null}
        <label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2">
          <input type="checkbox" className="mt-1" checked={restricted} onChange={(event) => setRestricted(event.target.checked)} />
          Restrict this pre-engagement record to explicitly granted members
        </label>
        {formError ? <p role="alert" className={`md:col-span-2 ${ERROR_CLASS}`}>{formError}</p> : null}
        {!valid ? (
          <p id="ip-tm-create-requirements" className="break-words text-xs text-[var(--color-mute)] md:col-span-2">
            {!catalogue.isSuccess
              ? catalogue.isError
                ? "The Nice class list could not load. Use Try again on the class field. "
                : "Waiting for the Nice class list to load. "
              : null}
            {missing.length ? `To create the application, add ${missing.join("; ")}.` : duplicate ? "Choose a different Nice class for each row." : null}
          </p>
        ) : null}
        <div className="flex min-w-0 flex-wrap items-center gap-2 md:col-span-2">
          <Button type="submit" disabled={!valid || mutation.isPending} aria-describedby={!valid ? "ip-tm-create-requirements" : undefined}>
            {mutation.isPending ? "Creating…" : "Create application"}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </section>
  );
}
