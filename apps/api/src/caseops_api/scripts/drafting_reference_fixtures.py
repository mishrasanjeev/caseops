"""Expand the shared synthetic manual-format fixtures for offline evaluators."""
from __future__ import annotations


def reference_scenarios(data: dict) -> list[tuple[str, str, dict]]:
    scenarios = []
    for key, details in data["court_forms"].items():
        scenarios.append((
            key, "supplied-court-particulars",
            {**data["court_facts"], "procedure_details": details},
        ))
    for key, details in data["notice_forms"].items():
        scenarios.append((key, "supplied-correspondence", {**data["notice_facts"], **details}))
    for instrument in data["instruments"]:
        scenarios.append((
            "conveyancing_deed", instrument, {**data["deed_facts"], "instrument_type": instrument},
        ))
    for template, block in data["existing_variants"].items():
        for key, selection in block["variants"].items():
            scenarios.append((template, key, {**block["facts"], **selection}))
    return scenarios
