import json
from datetime import date
from pathlib import Path

from monitor.clinicaltrials import Study, normalise_studies

payload = json.loads((Path(__file__).parent / "fixtures" / "studies.json").read_text())


def test_normalises_a_multi_phase_study():
    studies, _ = normalise_studies(payload)

    assert studies[0] == Study(
        nct_id="NCT06137144",
        title="AZD3470 as Monotherapy or in Combination With Anticancer Agent(s) in Participants With Haematologic Malignancies.",
        lead_sponsor="AstraZeneca",
        phases=["PHASE1", "PHASE2"],
        overall_status="RECRUITING",
        last_update_posted=date(2026, 9, 14),
    )


def test_study_without_phases_has_empty_phases():
    studies, _ = normalise_studies(payload)

    assert [(s.nct_id, s.phases) for s in studies][1] == ("NCT07646600", [])


def test_study_with_unknown_status_is_skipped_counted_and_logged(caplog):
    studies, skipped = normalise_studies(payload)

    assert [s.nct_id for s in studies] == ["NCT06137144", "NCT07646600"]
    assert skipped == 1
    assert "NCT06677060" in caplog.text


def test_malformed_studies_are_skipped_counted_and_logged(caplog):
    malformed_payload = {
        "studies": [
            [],
            {"protocolSection": []},
            {"protocolSection": {"identificationModule": []}},
            {"protocolSection": {"designModule": []}},
        ]
    }

    studies, skipped = normalise_studies(malformed_payload)

    assert studies == []
    assert skipped == 4
    assert caplog.text.count("Skipped study") == 4
