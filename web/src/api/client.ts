import type { components } from "@/api/schema";

export type StudyList = components["schemas"]["StudyList"];
export type Study = components["schemas"]["Study"];
type UpstreamProblem = components["schemas"]["UpstreamProblem"];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

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
