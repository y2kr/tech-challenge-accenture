import logging
from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

Phase = Literal["NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
OverallStatus = Literal[
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
    "UNKNOWN",
]

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
SPONSOR = "AstraZeneca"
WATCHLIST_SIZE = 50
TIMEOUT_SECONDS = 8

logger = logging.getLogger(__name__)


class UpstreamError(Exception):
    def __init__(
        self, status_code: int, detail: str, upstream_status: int | None = None
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.upstream_status = upstream_status


class Study(BaseModel):
    nct_id: str
    title: str
    lead_sponsor: str
    phases: list[Phase]
    overall_status: OverallStatus
    last_update_posted: date


def _dict(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _module(protocol: dict, name: str) -> dict:
    value = protocol.get(name, {})
    if value is None:
        return {}
    return _dict(value, name)


def normalise_study(raw: dict) -> Study:
    raw = _dict(raw, "study")
    protocol = _dict(raw["protocolSection"], "protocolSection")
    identification = _module(protocol, "identificationModule")
    status = _module(protocol, "statusModule")
    sponsor = _module(protocol, "sponsorCollaboratorsModule")
    design = _module(protocol, "designModule")
    return Study(
        nct_id=identification["nctId"],
        title=identification["briefTitle"],
        lead_sponsor=sponsor["leadSponsor"]["name"],
        phases=design.get("phases", []),
        overall_status=status["overallStatus"],
        last_update_posted=status["lastUpdatePostDateStruct"]["date"],
    )


def _raw_nct_id(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    protocol = raw.get("protocolSection")
    if not isinstance(protocol, dict):
        return None
    identification = protocol.get("identificationModule")
    if not isinstance(identification, dict):
        return None
    nct_id = identification.get("nctId")
    return nct_id if isinstance(nct_id, str) else None


def normalise_studies(payload: dict) -> tuple[list[Study], int]:
    studies = []
    for raw in payload["studies"]:
        try:
            studies.append(normalise_study(raw))
        except (KeyError, TypeError, ValidationError) as error:
            logger.warning("Skipped study %s: %r", _raw_nct_id(raw), error)
    return studies, len(payload["studies"]) - len(studies)


async def fetch_lead_sponsor_studies() -> dict:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                STUDIES_URL,
                params={
                    "query.lead": SPONSOR,
                    "pageSize": WATCHLIST_SIZE,
                    "sort": "LastUpdatePostDate:desc",
                },
            )
    except httpx.TimeoutException as error:
        raise UpstreamError(
            504, "ClinicalTrials.gov did not respond in time."
        ) from error
    except httpx.HTTPError as error:
        raise UpstreamError(502, "ClinicalTrials.gov could not be reached.") from error
    if not response.is_success:
        raise UpstreamError(
            502,
            f"ClinicalTrials.gov returned HTTP {response.status_code}.",
            response.status_code,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
        raise UpstreamError(
            502,
            "ClinicalTrials.gov returned an unreadable response.",
            response.status_code,
        )
    return payload
