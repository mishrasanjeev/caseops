import { Container } from "@/components/ui/Container";
import { siteConfig } from "@/lib/site";

export function ProductOwnershipNotice() {
  return (
    <aside
      aria-label="CaseOps product ownership"
      className="border-t border-[var(--color-line)] bg-[var(--color-bg)] py-4"
    >
      <Container>
        <div className="flex flex-col gap-2 text-xs leading-relaxed text-[var(--color-mute)] lg:flex-row lg:items-center lg:justify-between">
          <p>
            <strong className="font-semibold text-[var(--color-ink-2)]">CaseOps</strong> is
            owned by{" "}
            <strong className="font-semibold text-[var(--color-ink-2)]">
              {siteConfig.ownership.legalOwner}
            </strong>
            . Inventor/Owner:{" "}
            <strong className="font-semibold text-[var(--color-ink-2)]">
              {siteConfig.ownership.inventorOwner}
            </strong>
            .
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Owner emails">
            {siteConfig.ownership.emails.map((email) => (
              <a
                key={email}
                href={`mailto:${email}`}
                className="font-medium text-[var(--color-ink-2)] underline decoration-[var(--color-line)] underline-offset-2 hover:text-[var(--color-ink)]"
              >
                {email}
              </a>
            ))}
          </div>
        </div>
      </Container>
    </aside>
  );
}
