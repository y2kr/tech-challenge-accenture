from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from monitor.clinicaltrials import (
    Study,
    UpstreamError,
    fetch_lead_sponsor_studies,
    normalise_studies,
)
from monitor.monitoring import router
from monitor.settings import settings

app = FastAPI(title="Clinical Trial Monitoring API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST", "PATCH"],
)
app.include_router(router)


@app.exception_handler(SQLAlchemyError)
async def database_error_response(
    request: Request, error: SQLAlchemyError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Monitoring database is unavailable. Check configuration and migrations."
        },
    )


class UpstreamProblem(BaseModel):
    detail: str
    upstream_status: int | None


@app.exception_handler(UpstreamError)
async def upstream_error_response(
    request: Request, error: UpstreamError
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=UpstreamProblem(
            detail=error.detail, upstream_status=error.upstream_status
        ).model_dump(),
    )


class StudyList(BaseModel):
    studies: list[Study]
    skipped: int
    retrieved_at: datetime


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/studies",
    responses={502: {"model": UpstreamProblem}, 504: {"model": UpstreamProblem}},
)
async def list_studies() -> StudyList:
    studies, skipped = normalise_studies(await fetch_lead_sponsor_studies())
    return StudyList(studies=studies, skipped=skipped, retrieved_at=datetime.now(UTC))
