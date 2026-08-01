import type { ResumeVersion } from "../api/types";

export type ResumeWorkflowAction = "review" | "use" | null;

export function getResumeWorkflowAction(
  status: ResumeVersion["status"],
): ResumeWorkflowAction {
  if (status === "DRAFT") return "review";
  if (status === "REVIEWED") return "use";
  return null;
}

export function canEditResumeVersion(
  status: ResumeVersion["status"],
): boolean {
  return status === "DRAFT";
}
