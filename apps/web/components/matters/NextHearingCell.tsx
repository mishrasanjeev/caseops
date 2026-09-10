import Link from "next/link";

type HearingMatter = {
  id: string;
  cnr_number?: string | null;
  court_name?: string | null;
  case_number?: string | null;
  filing_number?: string | null;
  status: string;
};

export function NextHearingCell({ matter, date }: { matter: HearingMatter; date: string }) {
  const cnr = matter.cnr_number?.replace(/[^a-z0-9]/gi, "").toUpperCase();
  const invalidCnr = Boolean(matter.cnr_number?.trim()) && !/^[A-Z]{4}[0-9]{12}$/.test(cnr ?? "");
  const missingCourt = !cnr && !matter.court_name?.trim();
  const missingNumber = !cnr && ![matter.case_number, matter.filing_number].some(
    (value) => /^\s*(.*?)\s*[/ -]?\s*\d+\s*\/\s*(?:19|20)\d{2}\s*$/.test(value ?? ""),
  );
  const incomplete = invalidCnr || missingCourt || missingNumber;
  const terminal = ["closed", "disposed"].includes(matter.status);
  return (
    <div className="min-w-0 max-w-48 whitespace-normal">
      <span>{date}</span>
      {incomplete && !terminal && (
        <Link
          href={`/app/matters/${matter.id}`}
          className="mt-1 block text-xs text-[var(--color-ink-2)] underline"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {invalidCnr ? "Correct CNR for hearing sync" : missingCourt ? "Add court details for hearing sync" : "Add a case or filing number with year for hearing sync"}
        </Link>
      )}
    </div>
  );
}
