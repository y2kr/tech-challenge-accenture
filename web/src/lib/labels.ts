import type { Study } from "@/api/client";

const statusLabels: Record<Study["overall_status"], string> = {
  ACTIVE_NOT_RECRUITING: "Active, not recruiting",
  COMPLETED: "Completed",
  ENROLLING_BY_INVITATION: "Enrolling by invitation",
  NOT_YET_RECRUITING: "Not yet recruiting",
  RECRUITING: "Recruiting",
  SUSPENDED: "Suspended",
  TERMINATED: "Terminated",
  WITHDRAWN: "Withdrawn",
  AVAILABLE: "Available",
  NO_LONGER_AVAILABLE: "No longer available",
  TEMPORARILY_NOT_AVAILABLE: "Temporarily not available",
  APPROVED_FOR_MARKETING: "Approved for marketing",
  WITHHELD: "Withheld",
  UNKNOWN: "Unknown",
};

const stoppedStatuses: Study["overall_status"][] = [
  "SUSPENDED",
  "TERMINATED",
  "WITHDRAWN",
];

export function statusLabel(status: Study["overall_status"]) {
  return statusLabels[status];
}

export function isStoppedStatus(status: Study["overall_status"]) {
  return stoppedStatuses.includes(status);
}

export function phaseLabel(phases: Study["phases"]) {
  if (phases.length === 0) return "Not listed";
  if (phases.every((phase) => /^PHASE\d$/.test(phase)))
    return `Phase ${phases.map((phase) => phase.slice(-1)).join("/")}`;
  return phases
    .map((phase) => (phase === "NA" ? "Not applicable" : "Early phase 1"))
    .join(", ");
}
