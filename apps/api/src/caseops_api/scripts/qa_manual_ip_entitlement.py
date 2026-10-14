"""Explicit operator CLI; no bootstrap, provider transport or default grant mode."""

from __future__ import annotations

import argparse
import json

from caseops_api.db.session import get_session_factory
from caseops_api.services.qa_manual_ip_entitlement import (
    QaManualIpGrantError,
    grant_qa_manual_ip_entitlement,
    inspect_qa_manual_ip_entitlement,
    receipt_dict,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise QaManualIpGrantError("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    for mode in ("inspect", "grant"):
        command = commands.add_parser(mode)
        command.add_argument("--company-id", required=True)
        command.add_argument("--subscription-id", required=True)
        if mode == "grant":
            command.add_argument("--expected-before-sha256", required=True)
            command.add_argument("--operation-id", required=True)
    mode = None
    try:
        args = parser.parse_args(argv)
        mode = args.mode
        with get_session_factory()() as session:
            if args.mode == "inspect":
                receipt = inspect_qa_manual_ip_entitlement(
                    session,
                    company_id=args.company_id,
                    subscription_id=args.subscription_id,
                )
            else:
                receipt = grant_qa_manual_ip_entitlement(
                    session,
                    company_id=args.company_id,
                    subscription_id=args.subscription_id,
                    expected_before_sha256=args.expected_before_sha256,
                    operation_id=args.operation_id,
                )
        output = receipt_dict(receipt)
        exit_code = 0
    except QaManualIpGrantError as exc:
        output = {"schema_version": 1, "mode": mode, "error": {"code": exc.code}}
        exit_code = 2
    except Exception:
        output = {"schema_version": 1, "mode": mode, "error": {"code": "operator_failed"}}
        exit_code = 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
