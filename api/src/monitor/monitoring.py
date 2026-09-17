import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.concurrency import run_in_threadpool
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field
from sqlalchemy import Engine, case, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from monitor.changes import FieldChange, Severity, Snapshot, normalise_snapshot
from monitor.clinicaltrials import fetch_lead_sponsor_studies
from monitor.settings import settings
from monitor.storage import (
    AuditEntry,
    ChangeEvent,
    FollowUpAction,
    StoredStudy,
    StudySnapshot,
    persist_snapshot,
)

Source = Literal["live", "replay"]
ActionStatus = Literal["proposed", "approved", "rejected"]
Decision = Literal["approved", "rejected"]
REPLAY_LABEL = "Synthetic replay: recruiting to terminated; not live registry history"
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class Problem(BaseModel):
    detail: str


@lru_cache(maxsize=1)
def _engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise HTTPException(503, "DATABASE_URL must reference PostgreSQL.")
    return create_engine(
        url.set(drivername="postgresql+psycopg"), connect_args={"connect_timeout": 5}
    )


def database_engine() -> Engine:
    if not settings.database_url:
        raise HTTPException(503, "Monitoring database is not configured.")
    return _engine(settings.database_url)


Database = Annotated[Engine, Depends(database_engine)]


class SyncResult(BaseModel):
    source: Source
    label: str
    processed: int
    skipped: int
    event_ids: list[int]
    retrieved_at: datetime


class AIAnalysis(BaseModel):
    headline: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    possible_significance: list[str] = Field(min_length=1, max_length=3)
    confidence: Literal["low", "medium", "high"]


class FollowUpActionView(BaseModel):
    id: int
    title: str
    status: ActionStatus
    created_at: datetime


class AuditEntryView(BaseModel):
    id: int
    action_id: int
    action_title: str
    decision: Decision
    created_at: datetime


class DecisionRequest(BaseModel):
    status: Decision


class ChangeSummary(BaseModel):
    id: int
    nct_id: str
    title: str
    sponsor: str
    source: Source
    label: str
    source_url: str | None
    severity: Severity
    category: str
    headline: str
    review_status: str
    created_at: datetime


class SnapshotEvidence(BaseModel):
    id: int
    retrieved_at: datetime
    content_hash: str
    normalised_data: Snapshot


class ChangeDetail(ChangeSummary):
    structured_diff: list[FieldChange]
    before: SnapshotEvidence
    after: SnapshotEvidence
    ai_analysis: AIAnalysis | None
    actions: list[FollowUpActionView]
    audit_timeline: list[AuditEntryView]


def _label(source: Source) -> str:
    return REPLAY_LABEL if source == "replay" else "Live ClinicalTrials.gov observation"


def _generate_ai_analysis(changes: list[FieldChange]) -> AIAnalysis | None:
    if not settings.openai_api_key:
        return None
    evidence = [change.model_dump(mode="json") for change in changes]
    completion = OpenAI(
        api_key=settings.openai_api_key, timeout=10
    ).chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Explain only the supplied before/after evidence for a clinical-trial "
                    "analyst. Do not add facts, causal claims, medical conclusions, "
                    "predictions, or company assertions. State uncertainty and use "
                    "qualified language for possible significance."
                ),
            },
            {"role": "user", "content": json.dumps({"evidence": evidence})},
        ],
        response_format=AIAnalysis,
    )
    analysis = completion.choices[0].message.parsed
    if analysis is None:
        raise ValueError("model returned no structured explanation")
    return analysis


def _save(
    engine: Engine, records: list[tuple[dict, Snapshot]], source: Source
) -> list[int]:
    event_ids = []
    if source == "live":
        records = sorted(
            records,
            key=lambda record: record[0]["protocolSection"]["identificationModule"][
                "nctId"
            ],
        )
    with Session(engine) as session, session.begin():
        for index, (raw, snapshot) in enumerate(records):
            event = persist_snapshot(
                session,
                raw,
                snapshot,
                source,
                baseline_only=source == "replay" and index == 0,
            )
            if event is not None:
                event_ids.append(event.id)
    analysis_event_ids = event_ids
    if settings.openai_api_key:
        with Session(engine) as session:
            pending = session.scalars(
                select(ChangeEvent.id)
                .join(StoredStudy, ChangeEvent.study_id == StoredStudy.id)
                .where(
                    StoredStudy.source == source,
                    ChangeEvent.ai_analysis.is_(None),
                )
                .order_by(ChangeEvent.created_at.desc())
                .limit(10)
            ).all()
        analysis_event_ids = list(dict.fromkeys([*event_ids, *pending]))
    for event_id in analysis_event_ids:
        try:
            with Session(engine) as session:
                event = session.get(ChangeEvent, event_id)
                if event is None:
                    continue
                changes = [
                    FieldChange.model_validate(change)
                    for change in event.structured_diff
                ]
            analysis = _generate_ai_analysis(changes)
            if analysis is not None:
                with Session(engine) as session, session.begin():
                    event = session.get(ChangeEvent, event_id)
                    if event is not None:
                        event.ai_analysis = analysis.model_dump(mode="json")
        except (OpenAIError, KeyError, IndexError, TypeError, ValueError) as error:
            logger.warning(
                "AI explanation unavailable for event %s: %s", event_id, error
            )
    return event_ids


@router.post(
    "/sync",
    responses={
        503: {"model": Problem},
        502: {"model": Problem},
        504: {"model": Problem},
    },
)
async def sync_studies(engine: Database, mode: Source = "live") -> SyncResult:
    if mode == "replay":
        raw_studies = [
            json.loads(files("monitor").joinpath(f"fixtures/{name}.json").read_text())
            for name in ("recruiting", "terminated")
        ]
    else:
        raw_studies = (await fetch_lead_sponsor_studies())["studies"]
    records = []
    skipped = 0
    for index, raw in enumerate(raw_studies):
        try:
            records.append((raw, normalise_snapshot(raw)))
        except (KeyError, TypeError, ValueError) as error:
            if mode == "replay":
                raise
            logger.warning("Skipped sync study at index %s: %s", index, error)
            skipped += 1
    event_ids = await run_in_threadpool(_save, engine, records, mode)
    return SyncResult(
        source=mode,
        label=_label(mode),
        processed=len(records),
        skipped=skipped,
        event_ids=event_ids,
        retrieved_at=datetime.now(UTC),
    )


def _summary(event: ChangeEvent, study: StoredStudy) -> ChangeSummary:
    status = next(
        (item for item in event.structured_diff if item["field"] == "overall_status"),
        None,
    )
    headline = (
        f"Study status changed: {status['before']} → {status['after']}"
        if status
        else "Study changed: "
        + ", ".join(item["field"].replace("_", " ") for item in event.structured_diff)
    )
    return ChangeSummary(
        id=event.id,
        nct_id=study.nct_id,
        title=study.title,
        sponsor=study.sponsor,
        source=study.source,
        label=_label(study.source),
        source_url=(
            f"https://clinicaltrials.gov/study/{study.nct_id}"
            if study.source == "live"
            else None
        ),
        severity=event.severity,
        category=event.category,
        headline=headline,
        review_status=event.review_status,
        created_at=event.created_at,
    )


@router.get("/changes", responses={503: {"model": Problem}})
def list_changes(
    engine: Database,
    source: Source = "live",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ChangeSummary]:
    priority = case(
        (ChangeEvent.severity == "critical", 0),
        (ChangeEvent.severity == "high", 1),
        (ChangeEvent.severity == "medium", 2),
        else_=3,
    )
    statement = (
        select(ChangeEvent, StoredStudy)
        .join(StoredStudy, ChangeEvent.study_id == StoredStudy.id)
        .where(StoredStudy.source == source)
        .order_by(priority, ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
        .limit(limit)
    )
    with Session(engine) as session:
        return [_summary(event, study) for event, study in session.execute(statement)]


@router.get(
    "/changes/{change_id}",
    responses={404: {"model": Problem}, 503: {"model": Problem}},
)
def change_detail(
    engine: Database, change_id: Annotated[int, Path(gt=0)]
) -> ChangeDetail:
    with Session(engine) as session:
        row = session.execute(
            select(ChangeEvent, StoredStudy)
            .join(StoredStudy, ChangeEvent.study_id == StoredStudy.id)
            .where(ChangeEvent.id == change_id)
        ).first()
        if row is None:
            raise HTTPException(404, "Change event not found.")
        event, study = row
        snapshots = [
            session.get(StudySnapshot, snapshot_id)
            for snapshot_id in (event.before_snapshot_id, event.after_snapshot_id)
        ]
        evidence = [
            SnapshotEvidence(
                id=snapshot.id,
                retrieved_at=snapshot.retrieved_at,
                content_hash=snapshot.content_hash,
                normalised_data=snapshot.normalised_data,
            )
            for snapshot in snapshots
        ]
        stored_actions = session.scalars(
            select(FollowUpAction)
            .where(FollowUpAction.change_event_id == event.id)
            .order_by(FollowUpAction.id)
        ).all()
        action_titles = {action.id: action.title for action in stored_actions}
        audit_entries = session.scalars(
            select(AuditEntry)
            .where(AuditEntry.change_event_id == event.id)
            .order_by(AuditEntry.created_at, AuditEntry.id)
        ).all()
        return ChangeDetail(
            **_summary(event, study).model_dump(),
            structured_diff=event.structured_diff,
            before=evidence[0],
            after=evidence[1],
            ai_analysis=event.ai_analysis,
            actions=[
                FollowUpActionView(
                    id=action.id,
                    title=action.title,
                    status=action.status,
                    created_at=action.created_at,
                )
                for action in stored_actions
            ],
            audit_timeline=[
                AuditEntryView(
                    id=entry.id,
                    action_id=entry.action_id,
                    action_title=action_titles[entry.action_id],
                    decision=entry.decision,
                    created_at=entry.created_at,
                )
                for entry in audit_entries
            ],
        )


@router.patch(
    "/actions/{action_id}",
    responses={404: {"model": Problem}, 503: {"model": Problem}},
)
def decide_action(
    engine: Database,
    action_id: Annotated[int, Path(gt=0)],
    decision: DecisionRequest,
) -> FollowUpActionView:
    with Session(engine) as session, session.begin():
        action = session.scalar(
            select(FollowUpAction)
            .where(FollowUpAction.id == action_id)
            .with_for_update()
        )
        if action is None:
            raise HTTPException(404, "Follow-up action not found.")
        action.status = decision.status
        event = session.get(ChangeEvent, action.change_event_id)
        if event is None:
            raise HTTPException(404, "Change event not found.")
        event.review_status = decision.status
        session.add(
            AuditEntry(
                change_event_id=event.id,
                action_id=action.id,
                decision=decision.status,
            )
        )
        session.flush()
        return FollowUpActionView(
            id=action.id,
            title=action.title,
            status=action.status,
            created_at=action.created_at,
        )
