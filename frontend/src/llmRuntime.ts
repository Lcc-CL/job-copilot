import type {
  LLMDryRunPreview,
  LLMRuntimeInfo,
  ResumeGenerationResponse,
} from "./api/types";

export function llmModeBadgeClass(mode: LLMRuntimeInfo["mode"]): string {
  if (mode === "live") return "badge-red";
  if (mode === "fake") return "badge-yellow";
  return "badge-blue";
}

export function isDryRunPreview(
  value: ResumeGenerationResponse,
): value is LLMDryRunPreview {
  return "status" in value && value.status === "dry-run" && value.created === false;
}

export function buildLiveConfirmation(
  runtime: LLMRuntimeInfo,
  operation: string,
): string {
  const operationInfo = runtime.operations[operation];
  const operationLabel = operationInfo?.label || operation;
  const model = operationInfo?.model || runtime.model;
  return [
    "即将进行真实 LLM 调用：",
    `Provider：${runtime.provider}`,
    `Model：${model}`,
    `任务：${operationLabel}`,
    "本次操作将产生外部 API 请求。是否继续？",
  ].join("\n");
}

export function liveConfirmationKey(
  runtime: LLMRuntimeInfo,
  operation: string,
): string {
  const model = runtime.operations[operation]?.model || runtime.model;
  return `llm-live-confirmed:${runtime.provider}:${model}:${operation}`;
}

export function generationSourceLabel(method: string | null): string {
  if (method === "llm_fake") return "FAKE";
  if (method === "llm_live") return "AI LIVE";
  if (method === "llm") return "AI LEGACY";
  if (method === "low_context_rule_based") return "DRAFT";
  return "RULE";
}
