from __future__ import annotations

import json

from caseops_api.scripts import send_activity_report as command


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


def test_command_logs_only_bounded_delivery_metadata(monkeypatch, capsys) -> None:
    report = {
        "generated_at": "2026-08-01T13:00:00+05:30",
        "segments": {
            "law_firms": {
                "company_count": 1,
                "accounts": [
                    {
                        "company_id": "tenant-secret-id",
                        "name": "Tenant Secret Name",
                        "periods": {"day": {"outstanding_amount_minor": 999_00}},
                    }
                ],
            },
            "general_counsels": {"company_count": 2, "accounts": []},
        },
    }
    monkeypatch.setattr(command, "get_session_factory", lambda: _SessionContext)
    monkeypatch.setattr(command, "build_activity_report", lambda _session: report)
    monkeypatch.setattr(command, "send_activity_report", lambda _report: "sent")

    assert command.main([]) == 0

    output = capsys.readouterr().out
    assert json.loads(output) == {
        "account_count": 3,
        "generated_at": "2026-08-01T13:00:00+05:30",
        "status": "sent",
    }
    assert "Tenant Secret Name" not in output
    assert "tenant-secret-id" not in output
    assert "outstanding_amount_minor" not in output
