# E2E Fixture Regression

Run with the existing API venv Python and the existing Node on PATH:

```text
apps/api/.venv/Scripts/python.exe scripts/e2e_fixture_regression.py --results-directory C:/owned-evidence/new-run
```

On Linux use `apps/api/.venv/bin/python`. `--scratch-root` optionally selects an
existing short scratch parent outside this checkout; the default is OS temp.
`--node` optionally selects an existing Node executable. Nothing is installed.
The results directory must not already exist. All reports, exact inventories,
phase journals, invocation arguments and before/after source hashes go there.
Runtime scratch is retained separately; its path is in `completion.json`.

The serial standard runner requires exactly 18 process tests, 51 SQLite tests
and 6 controller tests (75 total), zero skips/retries, complete Python phases
and matching JUnit identities. The controller cases mock only phase execution,
reconciliation and source snapshots; they exercise interruption propagation and
completion evidence without child processes, cloud calls or database access.
An interrupted run remains incomplete even if a partial report exists. The
180-second per-suite/210-second overall supervisor bounds leave cleanup room
inside the four-minute caller. They do not increase the 10-second fixture
child deadline or the unchanged browser deadlines.

PostgreSQL is a separate manual run of `test_ip_entitlement_fixture.py` with
`CASEOPS_IP_FIXTURE_TEST_BACKENDS=postgresql`, an explicitly owned EMPTY
`ip_fixture_test_<12hex>` database URL in `CASEOPS_IP_FIXTURE_TEST_POSTGRES_URL`,
and that exact name in `CASEOPS_IP_FIXTURE_TEST_POSTGRES_DATABASE`. The test
file retains every PostgreSQL/default/FK assertion. The standard runner never
uses these variables or connects to PostgreSQL. The canonical ORM table closure
is tested here; this is not migration or full browser/release certification.
