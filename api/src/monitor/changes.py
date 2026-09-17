import hashlib
import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from monitor.clinicaltrials import OverallStatus, Phase, _module, normalise_study

Severity = Literal["critical", "high", "medium", "low"]
PRIMARY_COMPLETION_DELAY_DAYS = 30
ENROLLMENT_REDUCTION_FRACTION = 0.2
CRITICAL_STOPPED_STATUSES = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}


class Intervention(BaseModel):
    name: str
    type: str | None = None
    description: str | None = None


class Outcome(BaseModel):
    measure: str
    time_frame: str | None = None
    description: str | None = None


class Location(BaseModel):
    facility: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str


class Snapshot(BaseModel):
    overall_status: OverallStatus
    reason_stopped: str | None = None
    phases: list[Phase]
    enrollment_count: int | None = Field(default=None, ge=0, strict=True)
    primary_completion_date: str | None = None
    completion_date: str | None = None
    interventions: list[Intervention]
    primary_outcomes: list[Outcome]
    eligibility_criteria: str | None = None
    countries: list[str]
    locations: list[Location]


class FieldChange(BaseModel):
    field: str
    before: Any
    after: Any


def _list(module: dict, name: str) -> list:
    value = module.get(name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _dict_items(items: list, name: str) -> list[dict]:
    if not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{name} entries must be objects")
    return items


def _date_value(module: dict, name: str) -> str | None:
    value = module.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    date_value = value.get("date")
    if date_value is None:
        return None
    if not isinstance(date_value, str):
        raise TypeError(f"{name}.date must be a string")
    return _valid_source_date(date_value)


def _valid_source_date(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 1 and len(parts[0]) == 4 and parts[0].isdigit():
        date(int(parts[0]), 1, 1)
        return value
    if (
        len(parts) == 2
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and all(part.isdigit() for part in parts)
    ):
        date(int(parts[0]), int(parts[1]), 1)
        return value
    if (
        len(parts) == 3
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and len(parts[2]) == 2
        and all(part.isdigit() for part in parts)
    ):
        date.fromisoformat(value)
        return value
    raise ValueError("source date must be YYYY, YYYY-MM, or YYYY-MM-DD")


def normalise_snapshot(raw: dict) -> Snapshot:
    study = normalise_study(raw)
    protocol = raw["protocolSection"]
    if not isinstance(protocol, dict):
        raise TypeError("protocolSection must be an object")
    status = _module(protocol, "statusModule")
    design = _module(protocol, "designModule")
    arms = _module(protocol, "armsInterventionsModule")
    outcomes = _module(protocol, "outcomesModule")
    eligibility = _module(protocol, "eligibilityModule")
    contacts = _module(protocol, "contactsLocationsModule")
    enrollment = design.get("enrollmentInfo")
    if enrollment is not None and not isinstance(enrollment, dict):
        raise TypeError("enrollmentInfo must be an object")
    locations = _dict_items(_list(contacts, "locations"), "locations")
    countries = [item["country"] for item in locations if "country" in item]
    return Snapshot(
        overall_status=study.overall_status,
        reason_stopped=status.get("whyStopped"),
        phases=study.phases,
        enrollment_count=None if enrollment is None else enrollment.get("count"),
        primary_completion_date=_date_value(status, "primaryCompletionDateStruct"),
        completion_date=_date_value(status, "completionDateStruct"),
        interventions=[
            Intervention(
                name=item.get("name"),
                type=item.get("type"),
                description=item.get("description"),
            )
            for item in _dict_items(_list(arms, "interventions"), "interventions")
        ],
        primary_outcomes=[
            Outcome(
                measure=item.get("measure"),
                time_frame=item.get("timeFrame"),
                description=item.get("description"),
            )
            for item in _dict_items(
                _list(outcomes, "primaryOutcomes"), "primaryOutcomes"
            )
        ],
        eligibility_criteria=eligibility.get("eligibilityCriteria"),
        countries=countries,
        locations=[
            Location(
                facility=item.get("facility"),
                city=item.get("city"),
                state=item.get("state"),
                zip=item.get("zip"),
                country=item.get("country"),
            )
            for item in locations
        ],
    )


def _ordered_unique(values: list[Any]) -> list[Any]:
    by_key = {
        json.dumps(value, sort_keys=True, separators=(",", ":")): value
        for value in values
    }
    return [by_key[key] for key in sorted(by_key)]


def canonical_data(snapshot: Snapshot) -> dict[str, Any]:
    data = snapshot.model_dump(mode="json")
    for field in (
        "phases",
        "interventions",
        "primary_outcomes",
        "countries",
        "locations",
    ):
        data[field] = _ordered_unique(data[field])
    return data


def content_hash(snapshot: Snapshot) -> str:
    payload = json.dumps(
        canonical_data(snapshot), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[FieldChange]:
    before_data = canonical_data(before)
    after_data = canonical_data(after)
    return [
        FieldChange(field=field, before=before_data[field], after=after_data[field])
        for field in Snapshot.model_fields
        if before_data[field] != after_data[field]
    ]


def _full_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _changed(changes: list[FieldChange], field: str) -> FieldChange | None:
    return next((change for change in changes if change.field == field), None)


def severity_for(changes: list[FieldChange]) -> Severity:
    status = _changed(changes, "overall_status")
    if (
        status is not None
        and status.before == "RECRUITING"
        and status.after in CRITICAL_STOPPED_STATUSES
    ):
        return "critical"
    reason = _changed(changes, "reason_stopped")
    if reason is not None and reason.after is not None:
        return "critical"
    if _changed(changes, "interventions") or _changed(changes, "primary_outcomes"):
        return "high"
    primary_completion = _changed(changes, "primary_completion_date")
    if primary_completion is not None:
        before = _full_date(primary_completion.before)
        after = _full_date(primary_completion.after)
        if (
            before is not None
            and after is not None
            and (after - before).days >= PRIMARY_COMPLETION_DELAY_DAYS
        ):
            return "high"
    enrollment = _changed(changes, "enrollment_count")
    if (
        enrollment is not None
        and isinstance(enrollment.before, int)
        and enrollment.before > 0
        and isinstance(enrollment.after, int)
    ):
        reduction = (enrollment.before - enrollment.after) / enrollment.before
        if reduction >= ENROLLMENT_REDUCTION_FRACTION:
            return "high"
    for field in ("countries", "locations"):
        change = _changed(changes, field)
        if change is not None and set(map(json.dumps, change.before)) != set(
            map(json.dumps, change.after)
        ):
            return "medium"
    return "low"
