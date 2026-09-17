# Clinical Trial Monitoring

Decision-support workspace that monitors sponsors' public ClinicalTrials.gov records, detects meaningful changes, and proposes analyst follow-up for human approval.

## Language

**Study**:
A single ClinicalTrials.gov record, identified by its NCT ID.
_Avoid_: Trial, record, protocol

**Sponsor**:
The organisation named as lead sponsor of a Study. Collaborators are not Sponsors.
_Avoid_: Company, collaborator, funder

**Watchlist**:
The set of Studies monitored for one Sponsor.
_Avoid_: Portfolio, pipeline
