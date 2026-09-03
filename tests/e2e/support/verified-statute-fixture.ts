import { spawnSync } from "node:child_process";
import path from "node:path";

import { e2eEnv, repoRoot } from "./env";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

/** Seed one fully source-manifested section for local acceptance runs only. */
export function seedVerifiedLocalStatute(isLocal: boolean): void {
  if (!isLocal) return;
  const project = envOr("CASEOPS_E2E_DOCKER_PROJECT", "");
  const composeFile = envOr("CASEOPS_E2E_DOCKER_COMPOSE_FILE", "");
  if (Boolean(project) !== Boolean(composeFile)) {
    throw new Error(
      "Docker project and compose-file metadata must be supplied together.",
    );
  }
  const script = `
from datetime import UTC, datetime
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_statutes import _seed

now = datetime.now(UTC)
with get_session_factory()() as seed_session:
    _seed(seed_session)
with get_session_factory()() as session:
    statute = session.get(Statute, "e2e-verified-evidence-act")
    if statute is None:
        statute = Statute(
            id="e2e-verified-evidence-act",
            short_name="E2E Evidence Act",
            long_name="Deterministic verified-source acceptance fixture",
            enacted_year=2026,
            jurisdiction="india",
            source_url="https://www.indiacode.nic.in/",
            issuing_body="Legislative Department, Ministry of Law and Justice",
            source_status="official",
            verification_status="verified_official",
            exact_source_version="E2E acceptance fixture 2026-09-02",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(statute)
        session.flush()
    section = session.get(StatuteSection, "ram-sep02-verified-section")
    if section is None:
        section = StatuteSection(
            id="ram-sep02-verified-section",
            statute_id=statute.id,
            section_number="73",
            section_label="Deterministic acceptance evidence",
            section_text="A deterministic local fixture used only to verify the reference workflow.",
            section_text_source="indiacode",
            section_text_fetched_at=now,
            is_provisional=False,
            verification_status="verified_official",
            source_sha256="7b87df264c4fd520b9231f683c6de00553b8e48360547da816b1e09c78037ee0",
            source_publisher="Legislative Department, Ministry of Law and Justice",
            issuing_body="Legislative Department, Ministry of Law and Justice",
            source_status="official",
            legal_status="enacted",
            exact_source_version="E2E acceptance fixture 2026-09-02",
            source_locator_type="section_deep_link",
            source_policy_json={"fixture": True},
            link_health_status="available",
            link_last_checked_at=now,
            section_url="https://www.indiacode.nic.in/",
            ordinal=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(section)
    session.commit()
`;
  const seeded = project
    ? spawnSync(
        "docker",
        [
          "compose",
          "-p",
          project,
          "-f",
          composeFile,
          "exec",
          "-T",
          "api",
          "python",
          "-c",
          script,
        ],
        { encoding: "utf8" },
      )
    : spawnSync(
        process.platform === "win32"
          ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
          : path.join(repoRoot, "apps", "api", ".venv", "bin", "python"),
        ["-c", script],
        {
          cwd: repoRoot,
          encoding: "utf8",
          env: {
            ...process.env,
            ...e2eEnv,
            PYTHONPATH: [
              path.join(repoRoot, "apps", "api", "src"),
              process.env.PYTHONPATH,
            ]
              .filter(Boolean)
              .join(path.delimiter),
          },
        },
      );
  if (seeded.status !== 0) {
    throw new Error(
      `Could not seed verified statute fixture.\n${seeded.stdout}\n${seeded.stderr}`,
    );
  }
}
