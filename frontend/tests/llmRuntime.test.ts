import assert from "node:assert/strict";
import test from "node:test";
import { generateResume } from "../src/api/client.ts";
import type { LLMRuntimeInfo } from "../src/api/types.ts";
import {
  buildLiveConfirmation,
  generationSourceLabel,
  isDryRunPreview,
  liveConfirmationKey,
  llmModeBadgeClass,
} from "../src/llmRuntime.ts";

const liveRuntime: LLMRuntimeInfo = {
  mode: "live",
  label: "真实调用",
  provider: "test-provider",
  model: "draft-model",
  operations: {
    resume_tailor: { label: "定制简历生成", model: "draft-model" },
  },
  live_ready: true,
  network_enabled: true,
  message: "真实调用会向外部 LLM provider 发出 API 请求",
};

test("runtime modes use visually distinct badges", () => {
  assert.equal(llmModeBadgeClass("fake"), "badge-yellow");
  assert.equal(llmModeBadgeClass("dry-run"), "badge-blue");
  assert.equal(llmModeBadgeClass("live"), "badge-red");
});

test("live confirmation names provider, model, operation, and external request", () => {
  const message = buildLiveConfirmation(liveRuntime, "resume_tailor");
  assert.match(message, /test-provider/);
  assert.match(message, /draft-model/);
  assert.match(message, /定制简历生成/);
  assert.match(message, /外部 API 请求/);
  assert.match(
    liveConfirmationKey(liveRuntime, "resume_tailor"),
    /test-provider:draft-model:resume_tailor/,
  );
});

test("dry-run response is not treated as a ResumeVersion", () => {
  const preview = {
    status: "dry-run" as const,
    created: false as const,
    message: "未调用模型，未生成正式结果",
    application_id: 7,
    runtime: {
      mode: "dry-run" as const,
      label: "预演模式",
      provider: "test-provider",
      model: "draft-model",
      operation: "resume_tailor",
      operation_label: "定制简历生成",
      live_ready: true,
      network_enabled: false as const,
    },
    request: {
      message_count: 2,
      response_format: "json_object",
      max_tokens: 8000,
      temperature: 0.2,
      validated: true,
      validation_errors: [],
      network_request_sent: false as const,
    },
  };
  assert.equal(isDryRunPreview(preview), true);
});

test("resume generation request cannot send a client-side mode override", async () => {
  const originalFetch = globalThis.fetch;
  let body: BodyInit | null | undefined;
  globalThis.fetch = async (_input, init) => {
    body = init?.body;
    return new Response(JSON.stringify({
      status: "dry-run",
      created: false,
      message: "未调用模型，未生成正式结果",
      application_id: 9,
      runtime: {
        mode: "dry-run",
        label: "预演模式",
        provider: "test-provider",
        model: "draft-model",
        operation: "resume_tailor",
        operation_label: "定制简历生成",
        live_ready: true,
        network_enabled: false,
      },
      request: {
        message_count: 2,
        response_format: "json_object",
        max_tokens: 8000,
        temperature: 0.2,
        validated: true,
        validation_errors: [],
        network_request_sent: false,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };

  try {
    await generateResume(9);
    assert.equal(body, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("persisted generation methods expose fake and live sources", () => {
  assert.equal(generationSourceLabel("llm_fake"), "FAKE");
  assert.equal(generationSourceLabel("llm_live"), "AI LIVE");
});
