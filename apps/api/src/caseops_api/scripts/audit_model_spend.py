"""Spend audit — dumps the last 30 days of model_runs grouped by
(provider, model, purpose) so the operator can see exactly what's
burning tokens.

Per the user's `feedback_corpus_spend_audit` memory: every Anthropic
call writes a ModelRun row. This script is the read side.

CLI: ``python -m caseops_api.scripts.audit_model_spend``
"""
from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from caseops_api.db.models import ModelRun
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("audit_model_spend")


def _table_row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=False))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    cutoff_naive = cutoff.replace(tzinfo=None)
    with get_session_factory()() as session:
        # Aggregate by (provider, model, purpose) over last 30d.
        rows = list(
            session.execute(
                select(
                    ModelRun.provider,
                    ModelRun.model,
                    ModelRun.purpose,
                    func.count(ModelRun.id).label("calls"),
                    func.sum(ModelRun.prompt_tokens).label("prompt_tokens"),
                    func.sum(
                        ModelRun.completion_tokens
                    ).label("completion_tokens"),
                    func.avg(ModelRun.latency_ms).label("avg_latency_ms"),
                )
                .where(ModelRun.created_at >= cutoff_naive)
                .group_by(
                    ModelRun.provider, ModelRun.model, ModelRun.purpose,
                )
                .order_by(
                    func.sum(
                        ModelRun.prompt_tokens
                        + ModelRun.completion_tokens
                    ).desc()
                )
            ).all()
        )
        total_calls = session.scalar(
            select(func.count()).select_from(ModelRun)
            .where(ModelRun.created_at >= cutoff_naive)
        ) or 0
        total_prompt = session.scalar(
            select(func.sum(ModelRun.prompt_tokens))
            .where(ModelRun.created_at >= cutoff_naive)
        ) or 0
        total_completion = session.scalar(
            select(func.sum(ModelRun.completion_tokens))
            .where(ModelRun.created_at >= cutoff_naive)
        ) or 0

        # Recent burst: last 24h to spot active spenders.
        last24 = datetime.now(UTC) - timedelta(hours=24)
        last24_naive = last24.replace(tzinfo=None)
        burst = list(
            session.execute(
                select(
                    ModelRun.model,
                    ModelRun.purpose,
                    func.count(ModelRun.id).label("calls"),
                    func.sum(
                        ModelRun.prompt_tokens
                        + ModelRun.completion_tokens
                    ).label("tokens"),
                )
                .where(ModelRun.created_at >= last24_naive)
                .group_by(ModelRun.model, ModelRun.purpose)
                .order_by(
                    func.sum(
                        ModelRun.prompt_tokens
                        + ModelRun.completion_tokens
                    ).desc()
                )
            ).all()
        )

    print()
    print("=" * 78)
    print("ModelRun spend audit — last 30 days (grouped by provider/model/purpose)")
    print("=" * 78)
    print(
        f"  Total calls: {total_calls:>8}    "
        f"Total tokens: {(total_prompt + total_completion):>10} "
        f"(prompt={total_prompt}, completion={total_completion})"
    )
    print()
    widths = [12, 32, 32, 8, 14, 14, 12]
    header = ["provider", "model", "purpose", "calls",
              "prompt_tok", "completion_tok", "avg_lat_ms"]
    print(_table_row(header, widths))
    print("-" * sum(widths))
    for r in rows:
        print(_table_row(
            [
                str(r.provider or "?"),
                str(r.model or "?"),
                str(r.purpose or "?"),
                f"{int(r.calls or 0):>6}",
                f"{int(r.prompt_tokens or 0):>10}",
                f"{int(r.completion_tokens or 0):>10}",
                f"{int(r.avg_latency_ms or 0):>6}",
            ],
            widths,
        ))
    print()
    print("=" * 78)
    print("Last 24h burst (grouped by model/purpose, ordered by tokens)")
    print("=" * 78)
    widths24 = [32, 32, 8, 14]
    print(_table_row(["model", "purpose", "calls", "tokens"], widths24))
    print("-" * sum(widths24))
    for r in burst:
        print(_table_row(
            [
                str(r.model or "?"),
                str(r.purpose or "?"),
                f"{int(r.calls or 0):>6}",
                f"{int(r.tokens or 0):>10}",
            ],
            widths24,
        ))
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
