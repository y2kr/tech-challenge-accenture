import json
import logging
from copy import deepcopy
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
    VerificationDraft,
    VerificationDraftHistory,
    persist_snapshot,
)

Source = Literal["live", "replay"]
ActionStatus = Literal["proposed", "approved", "rejected"]
DraftStatus = Literal["proposed", "approved", "rejected"]
DraftOrigin = Literal["ai", "manual"]
DraftEvent = Literal["generated", "edited", "approved", "rejected"]
Decision = Literal["approved", "rejected"]
REPLAY_LABEL = (
    "Synthetic replay: five study-change scenarios; not live registry history"
)
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


class DraftPatchRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    revision: int = Field(default=0, ge=0)


class DraftDecisionRequest(BaseModel):
    status: Decision
    revision: int = Field(ge=1)


class VerificationDraftBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class VerificationDraftView(BaseModel):
    body: str
    revision: int
    status: DraftStatus
    origin: DraftOrigin
    updated_at: datetime


class VerificationDraftHistoryView(BaseModel):
    revision: int
    body: str
    status: DraftStatus
    event: DraftEvent
    created_at: datetime


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
    draft: VerificationDraftView | None
    draft_history: list[VerificationDraftHistoryView]


def _label(source: Source) -> str:
    return REPLAY_LABEL if source == "replay" else "Live ClinicalTrials.gov observation"


def _replay_studies() -> list[dict]:
    baseline = json.loads(
        files("monitor").joinpath("fixtures/recruiting.json").read_text()
    )

    def pair(nct_id: str, title: str) -> tuple[dict, dict]:
        before = deepcopy(baseline)
        after = deepcopy(baseline)
        for study in (before, after):
            identification = study["protocolSection"]["identificationModule"]
            identification["nctId"] = nct_id
            identification["briefTitle"] = title
        after["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"] = {
            "date": "2025-02-01",
            "type": "ACTUAL",
        }
        return before, after

    status_before, status_after = pair(
        "NCT90000001", "Synthetic recruitment status reconciliation"
    )
    status_after["protocolSection"]["statusModule"].update(
        {
            "overallStatus": "TERMINATED",
            "whyStopped": "Synthetic replay: recruitment terminated after feasibility review.",
        }
    )

    enrollment_before, enrollment_after = pair(
        "NCT90000002", "Synthetic enrolment reconciliation"
    )
    enrollment_after["protocolSection"]["designModule"]["enrollmentInfo"]["count"] = 350

    timeline_before, timeline_after = pair(
        "NCT90000003", "Synthetic timeline reconciliation"
    )
    timeline_after["protocolSection"]["statusModule"]["primaryCompletionDateStruct"][
        "date"
    ] = "2026-02-15"

    outcome_before, outcome_after = pair(
        "NCT90000004", "Synthetic primary outcome reconciliation"
    )
    outcome_after["protocolSection"]["outcomesModule"]["primaryOutcomes"][0][
        "measure"
    ] = "Synthetic revised primary outcome"

    location_before, location_after = pair(
        "NCT90000005", "Synthetic site footprint reconciliation"
    )
    location_after["protocolSection"]["contactsLocationsModule"]["locations"] = [
        location_after["protocolSection"]["contactsLocationsModule"]["locations"][1]
    ]

    return [
        status_before,
        status_after,
        enrollment_before,
        enrollment_after,
        timeline_before,
        timeline_after,
        outcome_before,
        outcome_after,
        location_before,
        location_after,
    ]


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


def _generate_verification_draft(
    event: ChangeEvent, study: StoredStudy
) -> VerificationDraftBody | None:
    if not settings.openai_api_key:
        return None
    evidence = {
        "study": {
            "nct_id": study.nct_id,
            "title": study.title,
            "source": study.source,
            "label": _label(study.source),
            "source_url": (
                f"https://clinicaltrials.gov/study/{study.nct_id}"
                if study.source == "live"
                else None
            ),
        },
        "changes": event.structured_diff,
    }
    completion = OpenAI(
        api_key=settings.openai_api_key, timeout=10
    ).chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Write a concise verification request to the study owner using only "
                    "the supplied study metadata and before/after evidence. Do not invent "
                    "recipients, causes, medical conclusions, predictions, or company "
                    "assertions. Ask them to verify the public-record change. If source "
                    "is replay, explicitly label it synthetic and do not imply it is live "
                    "public registry history."
                ),
            },
            {"role": "user", "content": json.dumps({"evidence": evidence})},
        ],
        response_format=VerificationDraftBody,
    )
    draft = completion.choices[0].message.parsed
    if draft is None:
        raise ValueError("model returned no verification draft")
    return draft


def _draft_view(draft: VerificationDraft | None) -> VerificationDraftView | None:
    if draft is None:
        return None
    return VerificationDraftView(
        body=draft.body,
        revision=draft.revision,
        status=draft.status,
        origin=draft.origin,
        updated_at=draft.updated_at,
    )


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
                baseline_only=source == "replay" and index % 2 == 0,
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
        raw_studies = _replay_studies()
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


def _summary(
    event: ChangeEvent, study: StoredStudy, draft_status: str | None = None
) -> ChangeSummary:
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
        review_status=draft_status or event.review_status,
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
        select(ChangeEvent, StoredStudy, VerificationDraft.status)
        .join(StoredStudy, ChangeEvent.study_id == StoredStudy.id)
        .outerjoin(
            VerificationDraft, VerificationDraft.change_event_id == ChangeEvent.id
        )
        .where(StoredStudy.source == source)
        .order_by(priority, ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
        .limit(limit)
    )
    with Session(engine) as session:
        return [
            _summary(event, study, draft_status)
            for event, study, draft_status in session.execute(statement)
        ]


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
        draft = session.scalar(
            select(VerificationDraft).where(
                VerificationDraft.change_event_id == event.id
            )
        )
        draft_history = session.scalars(
            select(VerificationDraftHistory)
            .where(VerificationDraftHistory.change_event_id == event.id)
            .order_by(VerificationDraftHistory.created_at, VerificationDraftHistory.id)
        ).all()
        return ChangeDetail(
            **_summary(event, study, draft.status if draft else None).model_dump(),
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
            draft=_draft_view(draft),
            draft_history=[
                VerificationDraftHistoryView(
                    revision=entry.revision,
                    body=entry.body,
                    status=entry.status,
                    event=entry.event,
                    created_at=entry.created_at,
                )
                for entry in draft_history
            ],
        )


@router.post(
    "/changes/{change_id}/draft",
    responses={404: {"model": Problem}, 503: {"model": Problem}},
)
def generate_draft(
    engine: Database, change_id: Annotated[int, Path(gt=0)]
) -> VerificationDraftView:
    with Session(engine) as session:
        row = session.execute(
            select(ChangeEvent, StoredStudy)
            .join(StoredStudy, ChangeEvent.study_id == StoredStudy.id)
            .where(ChangeEvent.id == change_id)
        ).first()
        if row is None:
            raise HTTPException(404, "Change event not found.")
        event, study = row
        existing = session.scalar(
            select(VerificationDraft).where(
                VerificationDraft.change_event_id == event.id
            )
        )
        if existing is not None:
            return _draft_view(existing)
        try:
            generated = _generate_verification_draft(event, study)
        except (OpenAIError, KeyError, IndexError, TypeError, ValueError) as error:
            logger.warning(
                "AI verification draft unavailable for event %s: %s", change_id, error
            )
            raise HTTPException(503, "AI verification draft is unavailable.") from error
        if generated is None:
            raise HTTPException(503, "AI verification draft is unavailable.")
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(ChangeEvent).where(ChangeEvent.id == change_id).with_for_update()
        )
        if event is None:
            raise HTTPException(404, "Change event not found.")
        existing = session.scalar(
            select(VerificationDraft)
            .where(VerificationDraft.change_event_id == event.id)
            .with_for_update()
        )
        if existing is not None:
            return _draft_view(existing)
        draft = VerificationDraft(
            change_event_id=event.id,
            body=generated.body,
            revision=1,
            status="proposed",
            origin="ai",
            updated_at=datetime.now(UTC),
        )
        session.add(draft)
        session.add(
            VerificationDraftHistory(
                change_event_id=event.id,
                revision=1,
                body=generated.body,
                status="proposed",
                event="generated",
            )
        )
        session.flush()
        return _draft_view(draft)


@router.patch(
    "/changes/{change_id}/draft",
    responses={
        404: {"model": Problem},
        409: {"model": Problem},
        503: {"model": Problem},
    },
)
def edit_draft(
    engine: Database,
    change_id: Annotated[int, Path(gt=0)],
    request: DraftPatchRequest,
) -> VerificationDraftView:
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(ChangeEvent).where(ChangeEvent.id == change_id).with_for_update()
        )
        if event is None:
            raise HTTPException(404, "Change event not found.")
        draft = session.scalar(
            select(VerificationDraft)
            .where(VerificationDraft.change_event_id == event.id)
            .with_for_update()
        )
        if draft is None:
            if request.revision != 0:
                raise HTTPException(409, "Draft revision is stale.")
            draft = VerificationDraft(
                change_event_id=event.id,
                body=request.body,
                revision=1,
                status="proposed",
                origin="manual",
                updated_at=datetime.now(UTC),
            )
            session.add(draft)
        else:
            if request.revision != draft.revision:
                raise HTTPException(409, "Draft revision is stale.")
            if request.body == draft.body:
                return _draft_view(draft)
            draft.body = request.body
            draft.revision += 1
            draft.origin = "manual"
            draft.updated_at = datetime.now(UTC)
            draft.status = "proposed"
        session.add(
            VerificationDraftHistory(
                change_event_id=event.id,
                revision=draft.revision,
                body=draft.body,
                status=draft.status,
                event="edited",
            )
        )
        session.flush()
        return _draft_view(draft)


@router.post(
    "/changes/{change_id}/draft/decision",
    responses={
        404: {"model": Problem},
        409: {"model": Problem},
        503: {"model": Problem},
    },
)
def decide_draft(
    engine: Database,
    change_id: Annotated[int, Path(gt=0)],
    request: DraftDecisionRequest,
) -> VerificationDraftView:
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(ChangeEvent).where(ChangeEvent.id == change_id).with_for_update()
        )
        if event is None:
            raise HTTPException(404, "Change event not found.")
        draft = session.scalar(
            select(VerificationDraft)
            .where(VerificationDraft.change_event_id == event.id)
            .with_for_update()
        )
        if draft is None:
            raise HTTPException(404, "Draft not found.")
        if request.revision != draft.revision:
            raise HTTPException(409, "Draft revision is stale.")
        if draft.status == request.status:
            return _draft_view(draft)
        draft.status = request.status
        draft.updated_at = datetime.now(UTC)
        session.add(
            VerificationDraftHistory(
                change_event_id=event.id,
                revision=draft.revision,
                body=draft.body,
                status=draft.status,
                event=request.status,
            )
        )
        session.flush()
        return _draft_view(draft)


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
