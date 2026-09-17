import json
from pathlib import Path

import pytest

from monitor.changes import (
    ENROLLMENT_REDUCTION_FRACTION,
    PRIMARY_COMPLETION_DELAY_DAYS,
    Snapshot,
    canonical_data,
    content_hash,
    diff_snapshots,
    normalise_snapshot,
    severity_for,
)

fixtures = Path(__file__).parents[1] / "src" / "monitor" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((fixtures / name).read_text())


def test_hash_is_stable_for_reordered_and_deduped_unordered_lists():
    raw = load_fixture("recruiting.json")
    reordered = json.loads(json.dumps(raw))
    protocol = reordered["protocolSection"]
    protocol["designModule"]["phases"] = ["PHASE3", "PHASE2", "PHASE2"]
    protocol["armsInterventionsModule"]["interventions"] *= 2
    protocol["outcomesModule"]["primaryOutcomes"] *= 2
    protocol["contactsLocationsModule"]["locations"] = [
        *reversed(protocol["contactsLocationsModule"]["locations"]),
        protocol["contactsLocationsModule"]["locations"][0],
    ]

    assert content_hash(normalise_snapshot(raw)) == content_hash(
        normalise_snapshot(reordered)
    )


def test_countries_are_derived_from_location_country_only():
    raw = load_fixture("recruiting.json")
    raw["protocolSection"]["contactsLocationsModule"]["countries"] = ["Neverland"]

    assert normalise_snapshot(raw).countries == ["United Kingdom", "United States"]


def test_location_zip_is_monitored_identity():
    before = normalise_snapshot(load_fixture("recruiting.json"))
    after_raw = load_fixture("recruiting.json")
    after_raw["protocolSection"]["contactsLocationsModule"]["locations"][0]["zip"] = (
        "SW1A"
    )

    changes = diff_snapshots(before, normalise_snapshot(after_raw))

    assert next(change for change in changes if change.field == "locations")
    assert severity_for(changes) == "medium"


def test_diff_reports_only_monitored_fields():
    before = load_fixture("recruiting.json")
    after = json.loads(json.dumps(before))
    after["protocolSection"]["identificationModule"]["briefTitle"] = "Unmonitored title"

    assert diff_snapshots(normalise_snapshot(before), normalise_snapshot(after)) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"primary_completion_date": "2026-01-30"}),
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"primary_completion_date": "2026-01-31"}),
            ),
            "high",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"primary_completion_date": "2026-02"}),
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"enrollment_count": 405}),
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"enrollment_count": 400}),
            ),
            "high",
        ),
        (
            lambda snapshot: (
                snapshot.model_copy(update={"enrollment_count": None}),
                snapshot.model_copy(update={"enrollment_count": 400}),
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot.model_copy(update={"enrollment_count": 0}),
                snapshot.model_copy(update={"enrollment_count": 1}),
            ),
            "low",
        ),
        *[
            (
                lambda snapshot, status=status: (
                    snapshot,
                    snapshot.model_copy(update={"overall_status": status}),
                ),
                "critical",
            )
            for status in ("TERMINATED", "WITHDRAWN", "SUSPENDED")
        ],
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"reason_stopped": "Added reason"}),
            ),
            "critical",
        ),
        (
            lambda snapshot: (
                snapshot.model_copy(update={"reason_stopped": "Old reason"}),
                snapshot.model_copy(update={"reason_stopped": "New reason"}),
            ),
            "critical",
        ),
        (
            lambda snapshot: (
                snapshot.model_copy(update={"reason_stopped": "Old reason"}),
                snapshot,
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(
                    update={
                        "interventions": [
                            snapshot.interventions[0].model_copy(
                                update={"name": "Changed intervention"}
                            )
                        ]
                    }
                ),
            ),
            "high",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(
                    update={
                        "primary_outcomes": [
                            snapshot.primary_outcomes[0].model_copy(
                                update={"measure": "Changed outcome"}
                            )
                        ]
                    }
                ),
            ),
            "high",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"countries": ["United States"]}),
            ),
            "medium",
        ),
        (
            lambda snapshot: (snapshot, snapshot.model_copy(update={"phases": []})),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(update={"eligibility_criteria": "Changed"}),
            ),
            "low",
        ),
        (
            lambda snapshot: (
                snapshot,
                snapshot.model_copy(
                    update={
                        "overall_status": "TERMINATED",
                        "interventions": [
                            snapshot.interventions[0].model_copy(
                                update={"name": "Changed intervention"}
                            )
                        ],
                    }
                ),
            ),
            "critical",
        ),
    ],
)
def test_severity_rules(mutate, expected):
    before, after = mutate(normalise_snapshot(load_fixture("recruiting.json")))

    assert PRIMARY_COMPLETION_DELAY_DAYS == 30
    assert ENROLLMENT_REDUCTION_FRACTION == 0.2
    assert severity_for(diff_snapshots(before, after)) == expected


def test_recruiting_to_terminated_fixture_is_critical_with_exact_evidence():
    changes = diff_snapshots(
        normalise_snapshot(load_fixture("recruiting.json")),
        normalise_snapshot(load_fixture("terminated.json")),
    )

    assert severity_for(changes) == "critical"
    assert {change.field for change in changes} >= {"overall_status", "reason_stopped"}
    assert (
        next(c for c in changes if c.field == "overall_status").before == "RECRUITING"
    )
    assert next(c for c in changes if c.field == "overall_status").after == "TERMINATED"
    assert "Synthetic" in next(c for c in changes if c.field == "reason_stopped").after


def test_canonical_data_is_json_compatible_and_monitored_only():
    data = canonical_data(normalise_snapshot(load_fixture("recruiting.json")))

    assert set(data) == set(Snapshot.model_fields)
    json.dumps(data)


@pytest.mark.parametrize("enrollment_count", [-1, True, "10"])
def test_enrollment_count_rejects_misleading_values(enrollment_count):
    raw = load_fixture("recruiting.json")
    raw["protocolSection"]["designModule"]["enrollmentInfo"]["count"] = enrollment_count

    with pytest.raises(ValueError):
        normalise_snapshot(raw)


@pytest.mark.parametrize(
    "date_value",
    ["2026-13", "2026-02-30", "2026-1", "20260101", "soon"],
)
def test_invalid_partial_dates_are_rejected(date_value):
    raw = load_fixture("recruiting.json")
    raw["protocolSection"]["statusModule"]["primaryCompletionDateStruct"]["date"] = (
        date_value
    )

    with pytest.raises(ValueError):
        normalise_snapshot(raw)


@pytest.mark.parametrize("date_value", ["2026", "2026-02", "2026-02-28"])
def test_valid_partial_dates_retain_precision(date_value):
    raw = load_fixture("recruiting.json")
    raw["protocolSection"]["statusModule"]["primaryCompletionDateStruct"]["date"] = (
        date_value
    )

    assert normalise_snapshot(raw).primary_completion_date == date_value


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"protocolSection": []},
        {"protocolSection": {"identificationModule": []}},
        {"protocolSection": {"designModule": []}},
        {
            "protocolSection": {
                **load_fixture("recruiting.json")["protocolSection"],
                "outcomesModule": {"primaryOutcomes": {}},
            }
        },
    ],
)
def test_malformed_snapshot_payloads_are_rejected(raw):
    with pytest.raises((TypeError, ValueError)):
        normalise_snapshot(raw)
