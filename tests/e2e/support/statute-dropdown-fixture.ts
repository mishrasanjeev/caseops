import { spawnSync } from "node:child_process";
import path from "node:path";

import { e2eEnv, repoRoot } from "./env";

export type StatuteDropdownFixtureAct = {
  id: string;
  short_name: string;
  long_name: string;
  section_count: number;
  catalog_section_count: number;
  positive_section_id: string;
  pending_section_id: string;
};

export type StatuteDropdownFixture = {
  target: StatuteDropdownFixtureAct;
  competitor: StatuteDropdownFixtureAct;
};

/** Synthetic layout data, never legal-source evidence or a production seed. */
export function seedStatuteDropdownFixture(web: string, api: string): StatuteDropdownFixture {
  for (const origin of [web, api]) {
    const url = new URL(origin);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
      throw new Error("Synthetic statute dropdown fixtures are loopback-only.");
    }
  }
  const project = process.env.CASEOPS_E2E_DOCKER_PROJECT?.trim();
  const compose = process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE?.trim();
  if (Boolean(project) !== Boolean(compose)) throw new Error("Docker fixture metadata must be supplied together.");
  const script = `
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.engine import make_url
from caseops_api.api.routes.statutes import _is_selectable_statute_section
from caseops_api.core.settings import get_settings
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory

settings = get_settings()
if settings.env != "e2e":
    raise RuntimeError("Synthetic dropdown fixture requires the isolated e2e runtime")
database = make_url(settings.database_url)
if database.get_backend_name() == "sqlite":
    if not database.database or database.database == ":memory:" or not Path(database.database).resolve().is_relative_to(Path.cwd().resolve()):
        raise RuntimeError("Synthetic dropdown SQLite storage must belong to this test checkout")
elif os.environ.get("CASEOPS_B5_FIXTURE_DOCKER") != "1" or database.host not in {"postgres", "db", "localhost", "127.0.0.1"}:
    raise RuntimeError("Synthetic dropdown fixtures refuse remote database storage")
now = datetime.now(UTC)
with get_session_factory()() as session:
    for index in range(41):
        competitor = index == 40
        key = "b5-layout-short-decoy" if competitor else f"b5-layout-{index:02}"
        if session.get(Statute, key) is not None:
            continue
        session.add(Statute(id=key, short_name="ZZZ Short decoy" if competitor else f"ZZZ Layout {index:02}",
            long_name="Short synthetic caption" if competitor else "Synthetic dropdown fixture, not an enactment: " + "long readable caption " * 6,
            enacted_year=2026, jurisdiction="india", source_url="https://example.invalid/synthetic",
            issuing_body="Synthetic local fixture", source_status="official",
            verification_status="verified_official", exact_source_version="synthetic-b5-20261111",
            is_active=True, created_at=now, updated_at=now))
        session.flush()
        for number in range(1, 84 if competitor else 82 if index == 39 else 3):
            verified = number % 2 == 1
            text = f"Synthetic layout fixture {index}/{number}; not legal text."
            session.add(StatuteSection(id=f"{key}-{number}", statute_id=key,
                section_number=f"Section {number}", section_label="Synthetic local fixture: " + "readable section caption " * 5,
                section_text=text if verified else "", section_url="https://example.invalid/synthetic",
                section_text_source="synthetic", section_text_fetched_at=now if verified else None,
                is_provisional=not verified, verification_status="verified_official" if verified else "unverified",
                source_sha256=sha256(text.encode()).hexdigest() if verified else "",
                source_publisher="Synthetic local fixture", issuing_body="Synthetic local fixture",
                source_status="official", legal_status="enacted", exact_source_version="synthetic-b5-20261111",
                source_locator_type="section_deep_link", source_policy_json={"fixture": True},
                link_health_status="available" if verified else "unchecked", link_last_checked_at=now if verified else None,
                ordinal=number, is_active=True, created_at=now, updated_at=now))
    session.commit()

    def describe(key):
        act = session.get(Statute, key)
        sections = list(session.scalars(select(StatuteSection).where(
            StatuteSection.statute_id == act.id, StatuteSection.is_active.is_(True)
        ).order_by(StatuteSection.ordinal)))
        verified = [row for row in sections if _is_selectable_statute_section(row)]
        pending = next(row for row in sections if row.verification_status == "unverified")
        return dict(id=act.id, short_name=act.short_name, long_name=act.long_name,
            section_count=len(verified), catalog_section_count=len(sections),
            positive_section_id=verified[-1].id, pending_section_id=pending.id)

    print(json.dumps(dict(target=describe("b5-layout-39"), competitor=describe("b5-layout-short-decoy"))))
`;
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot,
    "apps", "api", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const result = spawnSync(project ? "docker" : python,
    project ? ["compose", "-p", project, "-f", compose!, "exec", "-T", "-e", "CASEOPS_B5_FIXTURE_DOCKER=1", "api", "python", "-c", script] : ["-c", script], {
    cwd: repoRoot, encoding: "utf8", timeout: 30_000,
    env: { ...process.env, ...e2eEnv, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.join(repoRoot, "apps/api/src") },
  });
  if (result.status !== 0) throw new Error(`Synthetic dropdown setup failed: ${result.stderr}`);
  return JSON.parse(result.stdout) as StatuteDropdownFixture;
}
