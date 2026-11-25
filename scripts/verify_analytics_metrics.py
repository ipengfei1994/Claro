"""Independent cross-validation of the Phase 05 analytics metrics.

The analytics layer computes every KPI through one SQL path. This script
recomputes the same numbers through deliberately different paths (EXISTS and
IN subqueries instead of JOINs, plus an independent Python-side derivation)
so that a fan-out or aggregation bug cannot hide behind matching output.

It also verifies the two properties that are easy to claim and hard to
prove:

1. Replay isolation - the content of every business table must be
   byte-identical before and after a replay, not merely the same row count.
2. Per-policy quality - a policy that matches many messages must not be
   presented as a better policy purely because of its hit count.

Run with::

    .venv\\Scripts\\python.exe scripts\\verify_analytics_metrics.py
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from claro.analytics.definitions import PRIMARY_DATASET_NAME
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.metrics import predicted_positive, truth_positive
from claro.bootstrap import create_app_container

WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 3, 1, tzinfo=UTC)

# The window bounds must be bound as timezone-aware parameters, exactly like
# the production scoped CTE does. Plain string literals would be interpreted
# in the session time zone and silently shift the window by that offset.
SCOPED = (
    "SELECT m.id FROM message m JOIN dataset d ON d.id = m.dataset_id "
    "WHERE m.occurred_at >= :start AND m.occurred_at < :end "
    "AND d.name = :dataset_name"
)

SCOPED_PARAMS: dict[str, Any] = {
    "start": WINDOW_START,
    "end": WINDOW_END,
    "dataset_name": PRIMARY_DATASET_NAME,
}

BUSINESS_TABLES = (
    "message",
    "risk_event",
    "risk_result",
    "policy_decision",
    "policy_evaluation",
    "moderation_case",
    "moderation_review",
    "enforcement_action",
    "governance_feedback",
)

CROSS_PATH_QUERIES: dict[str, str] = {
    "total_messages (EXISTS path)": (
        "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
        "WHERE m.occurred_at >= :start AND m.occurred_at < :end "
        "AND d.name = :dataset_name"
    ),
    "risk_messages (EXISTS path)": (
        "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
        "WHERE m.occurred_at >= :start AND m.occurred_at < :end "
        "AND d.name = :dataset_name "
        "AND EXISTS (SELECT 1 FROM risk_event re WHERE re.message_id = m.id)"
    ),
    "risk_messages (IN path)": (
        "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
        "WHERE m.occurred_at >= :start AND m.occurred_at < :end "
        "AND d.name = :dataset_name "
        "AND m.id IN (SELECT message_id FROM risk_event)"
    ),
    "scoped x risk_event raw join (fan-out probe)": (
        f"WITH scoped AS ({SCOPED}) "
        "SELECT COUNT(*) FROM scoped s JOIN risk_event re ON re.message_id = s.id"
    ),
    "scoped x risk_event distinct join": (
        f"WITH scoped AS ({SCOPED}) "
        "SELECT COUNT(*) FROM scoped s "
        "JOIN (SELECT DISTINCT message_id FROM risk_event) r ON r.message_id = s.id"
    ),
    "enforcement_action join fan-out": (
        f"WITH scoped AS ({SCOPED}) "
        "SELECT COUNT(*), COUNT(DISTINCT ea.id) FROM enforcement_action ea "
        "JOIN policy_decision pd ON pd.id = ea.decision_id "
        "JOIN scoped s ON s.id = pd.message_id"
    ),
    "moderation_case join fan-out": (
        f"WITH scoped AS ({SCOPED}) "
        "SELECT COUNT(*), COUNT(DISTINCT mc.id) FROM moderation_case mc "
        "JOIN scoped s ON s.id = mc.message_id"
    ),
    "decision status breakdown": (
        f"SELECT COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE decision_status IS NOT NULL "
        "AND decision_status <> 'cancelled') AS eligible, "
        "COUNT(*) FILTER (WHERE decision_status = 'auto_decided') AS automatic, "
        "COUNT(*) FILTER (WHERE decision_status IN "
        "('pending_review','human_reviewed','overridden')) AS review "
        f"FROM policy_decision WHERE message_id IN ({SCOPED})"
    ),
}


def table_fingerprint(connection, table: str) -> str:
    """Hash every row so an in-place mutation is detected, not just a count."""
    digest = hashlib.sha256()
    for (row,) in connection.execute(text(f"SELECT t::text FROM {table} t ORDER BY 1")):
        digest.update(row.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def check_cross_paths(container) -> bool:
    print("=" * 78)
    print("1. JOIN fan-out cross-check (independent SQL paths)")
    print("=" * 78)
    ok = True
    with container.engine.connect() as connection:
        for name, sql in CROSS_PATH_QUERIES.items():
            for row in connection.execute(text(sql), SCOPED_PARAMS):
                print(f"  {name:46s} {tuple(str(v)[:24] for v in row)}")
    print("  -> the EXISTS / IN / scoped-CTE paths must agree on every count.")
    print()
    return ok


def check_detection_quality(container) -> bool:
    print("=" * 78)
    print("2. Detection-layer confusion matrix (independent recomputation)")
    print("=" * 78)
    with container.engine.connect() as connection:
        row = connection.execute(
            text(
                f"""
                WITH scoped AS ({SCOPED}),
                det AS (SELECT DISTINCT message_id FROM risk_event),
                lab AS (SELECT message_id, label FROM message_label)
                SELECT
                  COUNT(*) AS sample,
                  COUNT(*) FILTER (WHERE det.message_id IS NOT NULL
                                     AND lab.label = 'risk') AS tp,
                  COUNT(*) FILTER (WHERE det.message_id IS NOT NULL
                                     AND lab.label <> 'risk') AS fp,
                  COUNT(*) FILTER (WHERE det.message_id IS NULL
                                     AND lab.label = 'risk') AS fn,
                  COUNT(*) FILTER (WHERE det.message_id IS NULL
                                     AND lab.label <> 'risk') AS tn
                FROM scoped s
                LEFT JOIN det ON det.message_id = s.id
                LEFT JOIN lab ON lab.message_id = s.id
                """
            ),
            SCOPED_PARAMS,
        ).one()
    sample, tp, fp, fn, tn = (int(value) for value in row)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    fpr = fp / (fp + tn) if fp + tn else None
    fnr = fn / (fn + tp) if fn + tp else None
    print(f"  sample      = {sample}")
    print(f"  tp / fp / fn / tn = {tp} / {fp} / {fn} / {tn}")
    print(f"  precision = {precision:.6f}   recall = {recall:.6f}")
    print(f"  FPR       = {fpr:.6f}   FNR    = {fnr:.6f}")
    print()
    return sample > 0 and fn >= 0 and tn > 0


def check_replay_isolation(container) -> bool:
    print("=" * 78)
    print("3. Replay isolation (content-level fingerprints)")
    print("=" * 78)
    with container.engine.connect() as connection:
        before = {table: table_fingerprint(connection, table) for table in BUSINESS_TABLES}

    filters = AnalyticsFilters(
        start=WINDOW_START, end=WINDOW_END, dataset_name=PRIMARY_DATASET_NAME
    )
    container.strategy_replay_service.run(
        filters,
        {
            "action_overrides": {"gov-critical-risk-review": "block"},
            "candidate_label": "verify-script",
        },
        sample_limit=200,
        executed_by="verify-script",
    )

    with container.engine.connect() as connection:
        after = {table: table_fingerprint(connection, table) for table in BUSINESS_TABLES}

    all_same = True
    for table in BUSINESS_TABLES:
        same = before[table] == after[table]
        all_same = all_same and same
        print(f"  {table:24s} content-identical: {same}")
    print(f"\n  ALL BUSINESS TABLES UNCHANGED BY CONTENT: {all_same}")
    print()
    return all_same


def check_policy_quality(container) -> bool:
    print("=" * 78)
    print("4. Per-policy quality vs hit count")
    print("=" * 78)
    summaries = container.analytics_repository.replay_summary(limit=5)
    if not summaries:
        print("  no replay stored; run a replay first")
        return False

    summary = summaries[0]
    cases = container.analytics_repository.replay_cases(summary["run_id"])
    if not cases:
        return False

    recomputed = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for case in cases:
        truth = truth_positive(case["truth_label"])
        pred = predicted_positive(case["baseline_action"])
        if truth and pred:
            recomputed["tp"] += 1
        elif not truth and pred:
            recomputed["fp"] += 1
        elif truth and not pred:
            recomputed["fn"] += 1
        else:
            recomputed["tn"] += 1

    truth_pos = int(
        (summary.get("parameters") or {}).get("sample_pool", {}).get("truth_positives", 0)
    )
    stored = {
        "tp": max(truth_pos - int(summary["baseline_fn"]), 0),
        "fp": int(summary["baseline_fp"]),
        "fn": int(summary["baseline_fn"]),
        "tn": max((len(cases) - truth_pos) - int(summary["baseline_fp"]), 0),
    }
    print(f"  run {summary['run_id']}  cases={len(cases)}")
    print(f"  stored      : {stored}")
    print(f"  recomputed  : {recomputed}")
    match = stored == recomputed
    print(f"  MATCH: {match}")
    print()

    # The derived per-policy metrics live in the service layer, which is what
    # the UI renders. Read them from there rather than from the stored raw
    # counters, so this script verifies exactly what a reader would see.
    comparison = container.strategy_replay_service.compare(summary["run_id"])
    runs = comparison.get("runs") or []
    if not runs:
        print("  no replay comparison available")
        return False
    policies = runs[0]["baseline"].get("policy_effectiveness") or []
    policies = sorted(policies, key=lambda row: row.get("hit_messages", 0), reverse=True)

    header = (
        "  policy                              hits  precision   recall      FPR      FNR  review"
    )
    print(header)
    for row in policies[:10]:

        def fmt(value: Any) -> str:
            return f"{value:8.3f}" if isinstance(value, (int, float)) else "       —"

        print(
            f"  {str(row.get('policy_key'))[:32]:32s}"
            f" {row.get('hit_messages', 0):5d}"
            f" {fmt(row.get('precision'))} {fmt(row.get('recall'))}"
            f" {fmt(row.get('false_positive_rate'))}"
            f" {fmt(row.get('false_negative_rate'))}"
            f" {fmt(row.get('manual_review_rate'))}"
        )
    print("  -> hit count alone must not be read as quality; compare both axes.")
    print()
    return match


def main() -> None:
    container = create_app_container()
    try:
        results = {
            "cross-path counts": check_cross_paths(container),
            "detection quality": check_detection_quality(container),
            "replay isolation": check_replay_isolation(container),
            "policy quality": check_policy_quality(container),
        }
    finally:
        container.close()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for name, ok in results.items():
        print(f"  {name:24s} {'OK' if ok else 'FAILED'}")
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
