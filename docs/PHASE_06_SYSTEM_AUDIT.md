# Phase 06 — Full System Audit

**Project:** Claro — Content Safety Intelligence
**Scope:** Phase 01–05 implementation, reviewed before any Phase 06 modification
**Audit date:** 2026-11-25
**Auditor role:** Implementation review (code, live services, live data)

Every statement below is backed by a command that was executed against the
running system or the repository at the commit `27b16dc`. Items that could not
be executed (Hive) are marked **Blocked**, not "passed".

---

## 1. Audit Environment

| Item | Value |
|---|---|
| OS | Windows 11 Pro for Workstations (Insider Preview), build 26340 |
| CPU | Intel Core i5-8300H @ 2.30 GHz (4C/8T) |
| Memory | 15.9 GB |
| Python | 3.12.10 (`.venv`) |
| PostgreSQL | 18.3 (service `postgresql-x64-18`, port 5432) |
| Apache Kafka | 3.9.2 (KRaft single node, ports 9092/9093) |
| Redis | 8.10.3 (taizod1024 Windows fork, port 6379) |
| Streamlit | 1.67.0 |
| SQLAlchemy / Alembic | 2.1.9 / 1.20.1 |
| scikit-learn / pandas | 1.9.1 / 3.1.1 |
| Java | OpenJDK 17.0.21.1 |
| Hive / Hadoop / Beeline | **Not installed** |
| Docker / WSL | Not used (prohibited by project constraints) |

### 1.1 Baseline test execution

```
.venv\Scripts\python.exe -m pytest -q                 → 237 passed, 46 deselected (10.15s)
.venv\Scripts\python.exe -m pytest -q -m integration   → 46 passed, 237 deselected (72.00s)
```

Integration tests ran against the live PostgreSQL, Kafka and Redis instances
above; they were not mocked.

### 1.2 Baseline data inventory (live PostgreSQL)

| Table | Rows | Note |
|---|---:|---|
| `message` | 50,008 | 50,003 `decided`, 5 `received` |
| `message_label` | 50,000 | synthetic ground truth |
| `processing_event` | 250,009 | 5 events per bulk message |
| `risk_event` | 8,856 | severity: medium 3,735 / high 2,829 / critical 1,206 / low 1,086 |
| `risk_finding` | 8,878 | 8,856 from `synthetic-rule-engine`, 24 from real detectors |
| `risk_result` | **7** | only 7 messages have a full detection record |
| `policy_decision` | 50,008 | **50,003 have `decision_status = NULL`** |
| `policy` / `policy_version` / `policy_rule` | 53 / 47 / 40 | 11 policy types |
| `moderation_case` | 4,039 | 4,035 `resolved`, 1 `open`, 2 `in_review`, 1 `pending` |
| `moderation_review` | 0 | no review rows |
| `enforcement_action` | 1,208 | 1,206 `message_block` executed, 2 `mute` expired |
| `governance_feedback` | 0 | no feedback rows |
| `audit_event` | 2,960 | append-only audit trail |
| `outbox_event` | 446 | all published at audit time |
| `analytics_replay_run` / `analytics_replay_case` | 10 / 3,100 | Phase 05 strategy replay |

---

## 2. Architecture Assessment

The layering is sound and was preserved:

```
src/claro/
  ui/                 Streamlit pages + theme + charts (no SQL, no business rules)
  application/        services: ingestion, risk, policy evaluation, decision,
                      moderation, enforcement, feedback/audit, analytics, replay
  domain/             enums, message and safety value objects
  governance/         pure decision/enforcement/moderation/policy logic
  risk_engine/        preprocessing, rules, ML, fusion, explainability, evaluation
  analytics/          SQL queries, KPI definitions, metrics, quality, reports
  data_access/        SQLAlchemy models, repositories, migrations
  infrastructure/     Kafka, Redis, memory bus, health, logging
  config/             pydantic-settings, YAML merge, validation
```

**Verified positive properties**

| Property | Evidence |
|---|---|
| UI never issues SQL | `grep -rn "text(\|execute(" src/claro/ui` → 0 hits |
| Services are mode-agnostic | `bootstrap.create_app_container` wires ports; development uses in-memory bus |
| Configuration precedence | `config/default.yaml` < mode YAML < `.env` < env vars, with `extra="forbid"` |
| Fail-fast configuration | full mode rejects missing PostgreSQL/Redis/Kafka URLs and `replace-me` placeholders |
| Secret redaction | `redact_database_url()` masks credentials and sensitive query keys |
| Idempotent ingestion | `inbox_event` keyed by `message_id`, payload-hash conflict raises |
| Idempotent risk persistence | `risk_result.message_id` unique; `detect()` returns `created=False` on replay |
| Outbox for governance events | `outbox_event` + `OutboxDispatcher`, dedupe keys, retry counters |
| Redis degradation | `RedisError` handled in safety cache, policy cache and governance cache with PostgreSQL fallback |
| Ownership-safe operations | `Test-ClaroOwnedProcess` validates PID **and** command line before stopping |

No duplicated domain models and no second implementation of the decision logic
were found. The Phase 05 analytics layer reads the same tables the operational
services write.

---

## 3. Business Flow Audit

Legend: **Verified** = executed end-to-end and observed; **Partial** = works but
with a documented gap; **Blocked** = cannot execute in this environment.

| Flow | Path | Result | Evidence |
|---|---|---|---|
| A — Message processing | raw → Kafka → ingest → preprocess → detect → risk event | **Partial** | `persist_raw_message` + `RiskPipelineService` verified by 46 integration tests; only 7 messages carry a real `risk_result`, the bulk 50k were generated with `synthetic-rule-engine` |
| B — Governance | risk event → policy evaluation → decision → auto/manual | **Verified** | 50,008 evaluations/decisions; `GovernancePipelineService` covered by `test_governance_kafka`, `test_governance_scenarios` |
| C — Moderation | case → review → approve/reject/override → feedback | **Partial** | state machine and optimistic locking tested, but `moderation_review` is empty in the bulk dataset, so review-driven metrics are not computable |
| D — Enforcement | decision → simulator → record → player state | **Verified** | 1,208 records, all with `decision_id`; expiration and release covered by tests |
| E — Analytics | PostgreSQL → analytics layer → KPI → dashboard | **Verified** | 29 named SQL statements execute; 6 analytics pages render |
| F — Strategy replay | policy version → replay → comparison | **Partial** | 10 replay runs / 3,100 cases, but every policy only has `v1`, so cross-version comparison has no historical baseline |

### 3.1 Flow A detail — the single most important gap

`risk_event` for the bulk dataset was written by a generator
(`detector = "synthetic-rule-engine"`), not by the detection pipeline. Only 7
messages went through `RiskService.detect()` and received a `risk_result` with
rule findings, ML findings, fusion explanation and detector versions.

Consequence: the product could not demonstrate "how rule + ML + fusion produced
this decision" on more than 7 messages. This is a **product-truthfulness** issue:
a UI that shows fusion evidence for arbitrary bulk messages would have to invent
it. Phase 06 therefore must (a) label the bulk layer correctly and (b) produce a
demonstration dataset that runs the **real** pipeline.

### 3.2 Flow B detail — decision lifecycle

`policy_decision` rows: `allow` 42,232, `warn` 3,735, `review` 2,833,
`block` 1,206, `mute` 2. Of these, **50,003 rows have `decision_status = NULL`**
because they were produced by the Phase 04 bulk governance run before the
lifecycle column was populated. The analytics layer already handles this
honestly: the automatic-handling rate uses only rows with a decision status, and
refuses to publish a rate when the denominator is below 30.

That is correct behaviour, but it means the Overview dashboard currently shows
"自动决策 2" next to "治理决策 50008", which reads like a defect to any viewer.
Phase 06 must explain the distinction in the UI rather than hide it.

---

## 4. Integration Findings

### P0 — Blocks a normal start of the system

| ID | Finding | Evidence | Resolution |
|---|---|---|---|
| P0-1 | `scripts/service_common.ps1` → `Resolve-ClaroJavaHome()` returns the **`bin` directory** when `java.exe` is on `PATH`, because it takes `Split-Path -Parent` of the resolved binary. Every caller then builds `<home>\bin\java.exe`, i.e. `...\bin\bin\java.exe`, and Kafka cannot start from a clean shell. | Reproduced: `start_services.ps1 -Service Kafka` → `Start-Process : 系统找不到指定的文件`. `Get-ClaroKafkaPaths` returned `...jdk-17...\bin`. | **Fixed** in Phase 06: normalise to the JDK home, validate `bin\java.exe`, raise an explicit error otherwise. |

### P1 — Core flow or capability defects

| ID | Finding | Evidence | Resolution |
|---|---|---|---|
| P1-1 | `Start-Process` aborts with *"An item with the same key has already been added"* when the parent environment carries case-duplicate variables (`HTTPS_PROXY` + `https_proxy`). Windows environment blocks are case-insensitive, PowerShell 5.1 copies them into a case-sensitive dictionary. | Reproduced in this session; `[Environment]::GetEnvironmentVariables()` returned both spellings. | **Fixed**: `Reset-ClaroDuplicateEnvironment` collapses duplicates to one canonical entry before any launch. |
| P1-2 | No unified end-to-end entry point. Message → risk → governance spans three separate CLI commands (`kafka-consume --persist`, `risk-pipeline`, `governance-pipeline`); there is no `process_message()` that yields one traceable result. | `cli.py` has 30+ commands, none covering the full chain for one message. | **Implemented**: `ClaroProcessingService.process_message()` plus `claro process-message` / `claro demo-run`. |
| P1-3 | Overview is an infrastructure status page, not a product dashboard: 8 technical metrics (`运行模式=full`, `事件传输=kafka`), a health table and a synthetic-data notice. No risk KPIs, no trends, no activity feed. | Screenshot `runtime/cur_overview_light.png`. | **Rebuilt** as a KPI + trend + distribution + activity page backed by `AnalyticsService`. |
| P1-4 | Navigation is a flat 12-item radio with mixed Chinese/English labels and no Message Explorer, Risk Intelligence or Settings page. | `ui/app.py` `PAGES` dict. | **Rebuilt**: grouped navigation, three new pages. |
| P1-5 | Charts hardcode `paper_bgcolor="white"` and `font.color="#111827"`. In dark mode the charts stay white while the page is dark. | Screenshot `runtime/cur_risk_dark.png`. | **Fixed**: theme-aware chart layer driven by `st.context.theme.type`. |
| P1-6 | Theme support is a CSS-variable override on top of a fixed `base = "light"` config. Native widgets (`st.dataframe`, inputs, buttons) remain light because they do not read those variables — text becomes invisible on the injected dark background. | Probe app `runtime/probe_light.png`: metrics disappeared, table and input stayed white on a dark page. | **Fixed**: native `[theme.light]` + `[theme.dark]` palettes, giving real Light / Dark / System switching. |
| P1-7 | Numbers and timestamps are rendered raw: `Risk Rate 0.177092`, `50008`, `2026-11-25T10:36:34.130338+00:00`. | `runtime/cur_risk_dark.png`, several pages. | **Fixed**: shared formatters (percent, thousands separator, local `YYYY-MM-DD HH:mm`). |
| P1-8 | No deterministic demonstration dataset. The bulk 50k cannot demonstrate review, override, feedback, punishment release or policy comparison because those rows do not exist. | `moderation_review = 0`, `governance_feedback = 0`, all policies `v1`. | **Implemented**: 14-scenario demo dataset with fixed seed, isolated namespace and cleanup. |
| P1-9 | Deployment scripts are incomplete versus the required operational surface: no `start_app.ps1`, `stop_app.ps1`, `run_migrations.ps1`, `generate_demo_data.ps1`, `run_demo.ps1`, `run_tests.ps1`, `start_claro.ps1`, `stop_claro.ps1`. | `ls scripts/`. | **Implemented**. |
| P1-10 | No performance baseline exists; Phase 05 reports only functional results. | No benchmark artifact in `docs/`. | **Implemented**: measured benchmark for 1k / 10k / 50k. |
| P1-11 | `models/` is git-ignored, so a clean clone has no ML model and the ML detector silently contributes nothing. | `.gitignore` contains `models/`; model directory is 112 KB. | **Decided**: commit the 112 KB synthetic-trained model and document its provenance; the file is small and required for the documented behaviour. |

### P2 — Quality, consistency, maintainability

| ID | Finding | Evidence | Resolution |
|---|---|---|---|
| P2-1 | Page titles, subtitles and section headers are written per page with no shared component contract; heading levels vary between `st.title` and `st.subheader`. | `grep -n "st.title" src/claro/ui/pages/*.py` → 12 different patterns. | Unified through `page_header` / `section` helpers. |
| P2-2 | 18 `st.dataframe` calls with ad-hoc column sets; no empty-state or "showing N of M" affordance. | `grep -c st.dataframe` → 18. | Shared table renderer with empty state and row count caption. |
| P2-3 | `docker-compose.yml` and `deploy/postgresql/init/001-create-claro.sql` are Phase 01 leftovers; the project explicitly prohibits containers, and nothing references the file. | `grep -rn docker` outside `.venv` → only `docker-compose.yml` itself. | Removed the compose file; the SQL bootstrap is kept and documented as an optional native bootstrap. |
| P2-4 | UI smoke tests are plain scripts (`tests/ui/*.py`) that pytest does not collect, so UI regressions are invisible to `pytest`. | `pytest --collect-only tests/ui` → 0 items. | **Fixed**: `tests/ui/test_screens_smoke.py` now renders all 15 screens inside `AppTest` and is collected by pytest (17 cases); the old Playwright scripts were retired and replaced by `tests/ui/browser_smoke.py`, a real-Chrome check for light and dark. |
| P2-5 | `analytics_ui.render_banner` prints raw ISO timestamps and labels definitions as `phase-05.2` without explanation. | `runtime/cur_risk_dark.png`. | Formatted and linked to `KPI_DEFINITIONS.md`. |

### P3 — Nice to have (not addressed)

- Streamlit reloads the whole script on each interaction; widget-level cache tuning is possible.
- `logs/` rotation is configured through `structlog`; no external log aggregation.
- Hive SQL remains unexecuted (see §6).

---

## 5. Reliability and Security Review

| Area | Finding | Status |
|---|---|---|
| Configuration | No hard-coded passwords; `DATABASE_URL` carries no password and relies on `pgpass.conf`. `.env` is git-ignored, `.env.example` and `.env.full.example` exist. | Pass |
| Session lifecycle | `session_scope` context manager commits/rolls back; engine `pool_size`/`max_overflow`/`pool_timeout` configurable. | Pass |
| Transactions | `persist_raw_message` and `save_detection` each commit a single unit of work; decision + case creation share one transaction. | Pass |
| Kafka | Manual commit, retry topic, dead-letter topic, inbox dedupe, consumer-group lag command. | Pass |
| Redis | TTLs on every cache key; `RedisError` handled with PostgreSQL fallback. | Pass |
| SQL injection | All statements parameterised through SQLAlchemy; the analytics layer uses bound parameters. No string interpolation of user input. | Pass |
| Policy expressions | Policies are structured JSON conditions evaluated by `governance/policy.py`; no `eval`, no user SQL, no shell. | Pass |
| Path traversal | Only `--output`/`--output-dir` CLI arguments write files, resolved relative to the project root. Streamlit uploads are not used. | Pass |
| Secrets in logs | `configure_logging` redacts the DB URL; health details never contain credentials. | Pass |
| Access control | **Simulated identities only** (`reviewer.alice/bob/carol`, `auditor.dave`) selected in the sidebar. No authentication, no RBAC enforcement, no session isolation. | **Documented limitation** — must not be described as production auth |
| Auditability | `audit_event` (append-only) + `case_event` + `processing_event` + outbox headers give a four-level trail. | Pass |
| Dependency risk | `pip list` shows current releases; no known-vulnerable pins identified by inspection. No automated `pip-audit` run. | Partial — documented |

---

## 6. Blocked Capabilities

| Capability | Reason | Handling in Phase 06 |
|---|---|---|
| Hive / DWD / DWS / ADS SQL execution | No native Hive, Hadoop or Beeline on this machine; containers and WSL are prohibited. | Keep the export + SQL artefacts, mark **Blocked**, surface the state in `check_environment.ps1`, the Settings page and `KNOWN_LIMITATIONS.md`. Never claim execution. |
| Semantic detector | Placeholder that raises `NotImplemented` by design. | Documented; the risk engine records it as unavailable instead of pretending. |
| LLM advisor | Disabled by default, no credentialed endpoint available. | Documented; configuration validated but never exercised against a real endpoint. |
| Production identity / RBAC | Out of scope for a local demonstration platform. | Simulated identities, explicitly labelled in the UI and in the docs. |
| Multi-version policy comparison | Every policy has only `v1`; no historical versions to compare. | Demo dataset creates a second policy version so at least one comparison is real. |

---

## 7. Remediation Plan Executed in Phase 06

Order follows the required workflow (P0 → P1 → integration → product → docs).

1. **P0-1, P1-1** — PowerShell launcher correctness (JDK home, duplicate env keys). *Done before any other change; without it services cannot be restarted.*
2. **P1-2** — unified `process_message()` service with per-stage status, retry and idempotency.
3. **P1-8** — deterministic 14-scenario demonstration dataset, isolated and removable.
4. **P1-3, P1-4** — navigation rebuild, real Overview dashboard, Message Explorer, Risk Intelligence, Settings.
5. **P1-5, P1-6, P1-7, P2-1, P2-2** — design system: native theming, theme-aware charts, formatters, shared table and header components.
6. **P1-9** — complete Windows script surface with a single `start_claro.ps1` entry point.
7. **P1-10** — measured performance baseline.
8. **P1-11** — model artefact committed with provenance.
9. **P2-3** — legacy container artefacts removed.
10. **Documentation and portfolio** — audit, test report, completion report, case study, demo script, limitations, troubleshooting, deployment.

## 8. Explicit Non-Goals

- No rewrite of Phase 01–05 modules.
- No new infrastructure technology, no containerisation.
- No fabricated metrics: any number in Phase 06 documents is reproducible by a
  command recorded next to it.
- No feature marked complete on the strength of "code exists".

---

## 9. Audit Conclusion

The Phase 01–05 codebase is structurally sound: layering, idempotency,
configuration validation and analytics honesty are better than a typical
portfolio project. The weaknesses are concentrated at the **edges** — the
PowerShell launcher (two real defects, one of them blocking), the product
surface (a status page instead of a dashboard, no exploration path, no working
dark theme) and the **demonstrability** of the pipeline (only 7 messages carry
real detection evidence, reviews and feedback are empty).

Phase 06 therefore addresses exactly those edges, and does not touch the
validated core.
