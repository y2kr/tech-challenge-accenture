from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from monitor.changes import (
    Snapshot,
    canonical_data,
    content_hash,
    diff_snapshots,
    severity_for,
)
from monitor.clinicaltrials import normalise_study

Source = Literal["live", "replay"]


class Base(DeclarativeBase):
    pass


class StoredStudy(Base):
    __tablename__ = "studies"
    __table_args__ = (
        CheckConstraint("source in ('live', 'replay')", name="ck_studies_source"),
        UniqueConstraint("source", "nct_id", name="uq_studies_source_nct_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    nct_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    sponsor: Mapped[str] = mapped_column(String, nullable=False)
    overall_status: Mapped[str] = mapped_column(String, nullable=False)
    last_source_update: Mapped[date] = mapped_column(Date, nullable=False)
    raw_current: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    current_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "study_snapshots.id", name="fk_studies_current_snapshot_id", use_alter=True
        ),
        nullable=True,
    )


class StudySnapshot(Base):
    __tablename__ = "study_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "study_id", "content_hash", name="uq_study_snapshots_study_hash"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    study_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalised_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    study_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    before_snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("study_snapshots.id"), nullable=False
    )
    after_snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("study_snapshots.id"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    structured_diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    ai_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(32), server_default="unreviewed", nullable=False
    )


class FollowUpAction(Base):
    __tablename__ = "follow_up_actions"
    __table_args__ = (
        CheckConstraint(
            "status in ('proposed', 'approved', 'rejected')",
            name="ck_follow_up_actions_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    change_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("change_events.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), server_default="proposed", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    change_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("change_events.id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("follow_up_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _locked_study(
    session: Session, source: Source, raw: dict[str, Any], update: bool
) -> StoredStudy:
    study = normalise_study(raw)
    values = {
        "source": source,
        "nct_id": study.nct_id,
        "title": study.title,
        "sponsor": study.lead_sponsor,
        "overall_status": study.overall_status,
        "last_source_update": study.last_update_posted,
        "raw_current": raw,
    }
    session.execute(
        insert(StoredStudy)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["source", "nct_id"])
    )
    stored = session.scalar(
        select(StoredStudy)
        .where(StoredStudy.source == source, StoredStudy.nct_id == study.nct_id)
        .with_for_update()
    )
    if stored is None:
        raise RuntimeError("study insert failed")
    if update or stored.current_snapshot_id is None:
        for key, value in values.items():
            setattr(stored, key, value)
    return stored


def _snapshot(
    session: Session, study_id: int, raw: dict[str, Any], snapshot: Snapshot
) -> StudySnapshot:
    digest = content_hash(snapshot)
    session.execute(
        insert(StudySnapshot)
        .values(
            study_id=study_id,
            content_hash=digest,
            normalised_data=canonical_data(snapshot),
            raw_data=raw,
        )
        .on_conflict_do_nothing(index_elements=["study_id", "content_hash"])
    )
    stored = session.scalar(
        select(StudySnapshot).where(
            StudySnapshot.study_id == study_id,
            StudySnapshot.content_hash == digest,
        )
    )
    if stored is None:
        raise RuntimeError("snapshot insert failed")
    return stored


def persist_snapshot(
    session: Session,
    raw: dict[str, Any],
    snapshot: Snapshot,
    source: Source,
    baseline_only: bool = False,
) -> ChangeEvent | None:
    study = _locked_study(session, source, raw, update=not baseline_only)
    if baseline_only and study.current_snapshot_id is not None:
        return None
    previous = (
        session.get(StudySnapshot, study.current_snapshot_id)
        if study.current_snapshot_id
        else None
    )
    current = _snapshot(session, study.id, raw, snapshot)
    study.current_snapshot_id = current.id
    if previous is None or previous.content_hash == current.content_hash:
        return None
    changes = diff_snapshots(
        Snapshot.model_validate(previous.normalised_data), snapshot
    )
    event = ChangeEvent(
        study_id=study.id,
        before_snapshot_id=previous.id,
        after_snapshot_id=current.id,
        severity=severity_for(changes),
        category=changes[0].field if len(changes) == 1 else "multiple",
        structured_diff=[change.model_dump(mode="json") for change in changes],
    )
    session.add(event)
    session.flush()
    session.add_all(
        FollowUpAction(change_event_id=event.id, title=title)
        for title in (
            "Review other studies involving the same intervention",
            "Assign the change to the relevant pipeline analyst",
        )
    )
    return event
