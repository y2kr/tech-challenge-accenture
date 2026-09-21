import type { components } from "@/api/schema";

export type StudyList = components["schemas"]["StudyList"];
export type Study = components["schemas"]["Study"];
export type ChangeSummary = components["schemas"]["ChangeSummary"];
export type ChangeDetail = components["schemas"]["ChangeDetail"];
export type Draft = components["schemas"]["VerificationDraftView"];
export type DraftStatus = Draft["status"];
export type DraftHistoryEntry =
  components["schemas"]["VerificationDraftHistoryView"];
export type Decision = components["schemas"]["DecisionRequest"]["status"];
type SyncResult = components["schemas"]["SyncResult"];
type Problem = components["schemas"]["Problem"];
type UpstreamProblem = components["schemas"]["UpstreamProblem"];

const apiBaseUrl = "";

export async function fetchStudies(): Promise<StudyList> {
  const response = await fetch(`${apiBaseUrl}/api/studies`).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) {
    const problem: Partial<UpstreamProblem> = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      problem.detail ?? `The monitoring API returned HTTP ${response.status}.`,
    );
  }
  return response.json();
}

export async function syncReplay(): Promise<SyncResult> {
  const response = await fetch(`${apiBaseUrl}/api/sync?mode=replay`, {
    method: "POST",
  }).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function fetchChanges(): Promise<ChangeSummary[]> {
  const response = await fetch(`${apiBaseUrl}/api/changes?source=replay`).catch(
    () => {
      throw new Error("The monitoring API could not be reached.");
    },
  );
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function fetchChange(id: number): Promise<ChangeDetail> {
  const response = await fetch(`${apiBaseUrl}/api/changes/${id}`).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function generateDraft(id: number): Promise<Draft> {
  const response = await fetch(`${apiBaseUrl}/api/changes/${id}/draft`, {
    method: "POST",
  }).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function saveDraft({
  id,
  body,
  revision,
}: {
  id: number;
  body: string;
  revision: number;
}): Promise<Draft> {
  const response = await fetch(`${apiBaseUrl}/api/changes/${id}/draft`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, revision }),
  }).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function decideDraft({
  id,
  status,
  revision,
}: {
  id: number;
  status: Decision;
  revision: number;
}): Promise<Draft> {
  const response = await fetch(
    `${apiBaseUrl}/api/changes/${id}/draft/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, revision }),
    },
  ).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

export async function decideAction({
  id,
  status,
}: {
  id: number;
  status: Decision;
}) {
  const response = await fetch(`${apiBaseUrl}/api/actions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).catch(() => {
    throw new Error("The monitoring API could not be reached.");
  });
  if (!response.ok) throw new Error(await problemMessage(response));
  return response.json();
}

async function problemMessage(response: Response) {
  const problem: Partial<Problem> = await response.json().catch(() => ({}));
  return (
    problem.detail ?? `The monitoring API returned HTTP ${response.status}.`
  );
}
